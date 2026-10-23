"""Local aiohttp webhook process; Telegram reaches it through ngrok."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import hmac
import logging
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from dotenv import dotenv_values

from .api_client import ApiClient
from .handlers import create_router

WEBHOOK_PATH = "/telegram/webhook"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    bot_token: str
    internal_api_key: str
    webhook_secret: str
    public_base_url: str
    api_base_url: str = "http://127.0.0.1:3000"
    port: int = 8080
    admin_chat_id: int | None = None

    @classmethod
    def from_env(cls) -> "Config":
        # Explicit file path works both from the project root and bot directory.
        values = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
        def required(name: str) -> str:
            value = str(values.get(name) or "").strip()
            if not value:
                raise ValueError(f"Missing configuration: {name}")
            return value
        public = required("PUBLIC_BASE_URL").rstrip("/")
        parsed = urlsplit(public)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment or parsed.path:
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
        secret = required("WEBHOOK_SECRET")
        key = required("INTERNAL_API_KEY")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret) or secret == key:
            raise ValueError("WEBHOOK_SECRET must be a separate valid Telegram secret")
        port = int(values.get("PORT") or 8080)
        if not 1 <= port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        api = str(values.get("API_BASE_URL") or "http://127.0.0.1:3000").rstrip("/")
        parsed_api = urlsplit(api)
        if parsed_api.scheme not in ("http", "https") or not parsed_api.netloc or parsed_api.username or parsed_api.query or parsed_api.fragment:
            raise ValueError("Invalid API_BASE_URL")
        admin = str(values.get("ADMIN_CHAT_ID") or "").strip()
        admin_id = int(admin) if admin else None
        if admin_id == 0:
            raise ValueError("ADMIN_CHAT_ID must not be zero")
        return cls(required("BOT_TOKEN"), key, secret, public, api, port, admin_id)

    @property
    def webhook_url(self) -> str:
        return self.public_base_url + WEBHOOK_PATH


class DeduplicatingRequestHandler(SimpleRequestHandler):
    """Reserve update IDs before scheduling; cap both completed and active IDs."""

    def __init__(self, *args, dedupe_ttl: float = 900, dedupe_capacity: int = 10000, **kwargs):
        super().__init__(*args, **kwargs)
        self._completed: OrderedDict[int, float] = OrderedDict()
        self._active: set[int] = set()
        self._ttl = dedupe_ttl
        self._capacity = dedupe_capacity

    async def _handle_request_background(self, bot: Bot, request: web.Request) -> web.Response:
        try:
            update = await request.json(loads=bot.session.json_loads)
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid update"}, status=400)
        update_id = update.get("update_id") if isinstance(update, dict) else None
        if not isinstance(update_id, int) or isinstance(update_id, bool):
            return web.json_response({"error": "Invalid update"}, status=400)
        now = time.monotonic()
        while self._completed and next(iter(self._completed.values())) <= now:
            self._completed.popitem(last=False)
        if update_id in self._active or update_id in self._completed:
            return web.json_response({})
        if len(self._active) + len(self._completed) >= self._capacity:
            if self._completed:
                self._completed.popitem(last=False)
            else:
                return web.json_response({"error": "Busy"}, status=503)
        self._active.add(update_id)
        task = asyncio.create_task(self._process(bot, update, update_id))
        self._background_feed_update_tasks.add(task)
        task.add_done_callback(self._background_feed_update_tasks.discard)
        return web.json_response({})

    async def _process(self, bot: Bot, update: dict, update_id: int) -> None:
        try:
            await super()._background_feed_update(bot, update)
        except Exception:
            # Never include Telegram exceptions: their URLs can contain BOT_TOKEN.
            LOGGER.error("Webhook update processing failed")
        finally:
            self._active.discard(update_id)
            self._completed[update_id] = time.monotonic() + self._ttl

    async def close(self) -> None:
        if self._background_feed_update_tasks:
            await asyncio.gather(*tuple(self._background_feed_update_tasks), return_exceptions=True)
        await super().close()


CONFIG_KEY = web.AppKey("config", Config)
BOT_KEY = web.AppKey("bot", Bot)
DISPATCHER_KEY = web.AppKey("dispatcher", Dispatcher)
API_CLIENT_KEY = web.AppKey("api_client", ApiClient)


def create_app(config: Config, *, bot: Bot | None = None, dispatcher: Dispatcher | None = None,
               api_client: ApiClient | None = None, manage_webhook: bool = True) -> web.Application:
    """Inject dependencies and disable registration for isolated local tests."""
    bot = bot if bot is not None else Bot(config.bot_token, session=AiohttpSession(timeout=10))
    api_client = api_client if api_client is not None else ApiClient(config.api_base_url, config.internal_api_key)
    if dispatcher is None:
        dispatcher = Dispatcher(api_client=api_client)
        dispatcher.include_router(create_router())
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app[CONFIG_KEY], app[BOT_KEY] = config, bot
    app[DISPATCHER_KEY], app[API_CLIENT_KEY] = dispatcher, api_client
    handler = DeduplicatingRequestHandler(dispatcher, bot, handle_in_background=True,
                                          secret_token=config.webhook_secret, api_client=api_client)

    async def lifecycle(application: web.Application):
        registered = False
        try:
            if manage_webhook:
                await bot.set_webhook(config.webhook_url, secret_token=config.webhook_secret,
                                      allowed_updates=["message"], drop_pending_updates=False)
                registered = True
                info = await bot.get_webhook_info()
                if info.url != config.webhook_url:
                    raise RuntimeError("Webhook registration verification failed")
                LOGGER.info("Webhook registered and verified")
            await dispatcher.emit_startup(bot=bot, api_client=api_client)
            yield
        finally:
            try:
                if registered:
                    await bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                LOGGER.error("Webhook removal failed")
            finally:
                try:
                    await handler.close()
                    await dispatcher.emit_shutdown(bot=bot, api_client=api_client)
                finally:
                    await api_client.aclose()
                    await bot.session.close()

    async def internal_messages(request: web.Request) -> web.Response:
        def failure(status: int, code: str, message: str) -> web.Response:
            return web.json_response({"error": {"code": code, "message": message}}, status=status)

        supplied = request.headers.get("X-Internal-Key", "")
        if not config.internal_api_key or not hmac.compare_digest(
            supplied.encode("utf-8"), config.internal_api_key.encode("utf-8")
        ):
            return failure(403, "INTERNAL_AUTH_FAILED", "Internal authentication failed")
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return failure(400, "INVALID_TEXT", "Invalid message")
        sender = body.get("sender") if isinstance(body, dict) else None
        text = body.get("text") if isinstance(body, dict) else None
        # Count UTF-16 units to match TypeScript while rejecting invalid Unicode.
        try:
            text_units = len(text.strip().encode("utf-16-le")) // 2 if isinstance(text, str) else 0
        except UnicodeEncodeError:
            return failure(400, "INVALID_TEXT", "Invalid Unicode text")
        if not isinstance(sender, dict) or not isinstance(text, str) or not 1 <= text_units <= 3000:
            return failure(400, "INVALID_TEXT", "Invalid message")
        user_id, name, username = sender.get("telegramId"), sender.get("firstName"), sender.get("username")
        if (type(user_id) is not int or not 1 <= user_id <= 9007199254740991
                or not isinstance(name, str) or not name.strip()
                or (username is not None and (not isinstance(username, str)
                    or re.fullmatch(r"[A-Za-z0-9_]{1,32}", username) is None))):
            return failure(400, "INVALID_TEXT", "Invalid sender")
        try:
            name.encode("utf-16-le")
        except UnicodeEncodeError:
            return failure(400, "INVALID_TEXT", "Invalid Unicode sender")
        if config.admin_chat_id is None or config.admin_chat_id == 0:
            return failure(502, "TELEGRAM_DELIVERY_FAILED", "ADMIN_CHAT_ID is not configured")
        # Bound the signature and remove line breaks; Unicode can take two UTF-16 units.
        safe_name = " ".join(name.split())[:64]
        signature = f"От: {safe_name} (ID: {user_id}" + (f", @{username}" if username else "") + ")"
        message_text = signature + "\n\n" + text.strip()
        # Do not silently truncate user text when non-BMP characters exceed Telegram limits.
        if len(message_text.encode("utf-16-le")) // 2 > 4096:
            return failure(400, "INVALID_TEXT", "Message exceeds Telegram length limit")
        try:
            result = await asyncio.wait_for(bot.send_message(
                chat_id=config.admin_chat_id, text=message_text, parse_mode=None, request_timeout=10
            ), timeout=10)
        except (TimeoutError, TelegramNetworkError):
            return failure(504, "DELIVERY_UNCONFIRMED", "Delivery result is unknown")
        except TelegramAPIError:
            return failure(502, "TELEGRAM_DELIVERY_FAILED", "Telegram rejected delivery")
        return web.json_response({"status": "sent", "telegramMessageId": result.message_id})

    app.router.add_post("/internal/messages", internal_messages)

    app.cleanup_ctx.append(lifecycle)
    # Lifecycle owns shutdown and sessions; register just the route to avoid double close.
    app.router.add_post(WEBHOOK_PATH, handler.handle)
    return app


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    # Avoid access logs and provider error messages containing identifiers/secrets.
    config = Config.from_env()
    web.run_app(create_app(config), host="127.0.0.1", port=config.port, access_log=None)


if __name__ == "__main__":
    main()
