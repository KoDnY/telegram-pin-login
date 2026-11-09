"""Real local HTTP smoke test; no Telegram account, tunnel or credentials needed.

Cross-project check from workspace root:
 npm.cmd --prefix server/api run build
 server/.venv/Scripts/python.exe tests/local_smoke.py
"""
import asyncio
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER))

import httpx
from aiohttp import web
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, GetUserProfilePhotos
from aiogram.types import Message, UserProfilePhotos
from bot.app.main import Config, create_app
from client.app.api_client import ApiClient, ApiError


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.failure = None

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetUserProfilePhotos):
            return UserProfilePhotos(total_count=0, photos=[])
        if isinstance(method, SendMessage):
            self.sent.append(method)
            if method.chat_id == 999 and self.failure:
                if self.failure == 502:
                    raise TelegramBadRequest(method=method, message="simulated rejection")
                raise TimeoutError("simulated timeout")
            return Message(message_id=len(self.sent), date=1,
                           chat={"id": method.chat_id, "type": "private"}, text=method.text)
        raise AssertionError(type(method).__name__)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main():
    api_port, bot_port = free_port(), free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    secret, webhook = "smoke-internal-only", "smoke-webhook-only"
    env = {**os.environ, "API_PORT": str(api_port), "PORT": str(api_port), "INTERNAL_API_KEY": secret,
           "BOT_INTERNAL_URL": f"http://127.0.0.1:{bot_port}"}
    processes = []
    logs = []

    async def start_api():
        process = subprocess.Popen(["node", "api/dist/server.js"], cwd=SERVER,
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        processes.append(process)
        async with httpx.AsyncClient() as raw:
            for _ in range(100):
                try:
                    response = await raw.get(api_url + "/health")
                    assert response.json() == {"status": "ok"}
                    return process
                except httpx.RequestError:
                    await asyncio.sleep(.05)
        raise AssertionError("API did not start")

    def stop(process):
        if process.poll() is None:
            process.terminate()
        output, _ = process.communicate(timeout=10)
        logs.append(output.decode(errors="replace"))

    fake = FakeTelegram()
    bot = Bot("123456:smoke-token", session=fake)
    app = create_app(Config("123456:smoke-token", secret, webhook, "https://example.invalid",
                            api_url, bot_port, 999), bot=bot, manage_webhook=False)
    runner = web.AppRunner(app, access_log=None)
    clients = [ApiClient(api_url), ApiClient(api_url)]
    pins, tokens = [], []
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", bot_port).start()
        process = await start_api()
        async with httpx.AsyncClient() as raw:
            for i, client in enumerate(clients, 1):
                update = {"update_id": i, "message": {"message_id": i, "date": 1,
                    "chat": {"id": i, "type": "private"},
                    "from": {"id": i, "is_bot": False, "first_name": f"User{i}"},
                    "text": "/start", "entities": [{"offset": 0, "length": 6, "type": "bot_command"}]}}
                response = await raw.post(f"http://127.0.0.1:{bot_port}/telegram/webhook",
                    json=update, headers={"X-Telegram-Bot-Api-Secret-Token": webhook})
                assert response.status_code == 200
                for _ in range(100):
                    replies = [m for m in fake.sent if m.chat_id == i]
                    if replies:
                        break
                    await asyncio.sleep(.02)
                match = re.search(r"PIN: ([0-9]{6})", replies[-1].text)
                assert match, "PIN reply missing"
                pin = match[1]
                pins.append(pin)
                profile = await client.authenticate(pin)
                assert profile["telegramId"] == i and profile["firstName"] == f"User{i}"
                assert profile["avatar"] is None and profile["username"] is None
                tokens.append(client._access_token)
                assert (await raw.post(api_url + "/auth", json={"key": pin})).status_code == 401
                assert await client.send_message(f"message-{i}") == {"status": "sent"}
                sent = fake.sent[-1]
                assert sent.chat_id == 999 and f"ID: {i}" in sent.text and f"User{i}" in sent.text
                assert sent.text.endswith(f"message-{i}")
            for status, code in [(502, "DELIVERY_FAILED"), (504, "DELIVERY_UNCONFIRMED")]:
                fake.failure = status
                before = len(fake.sent)
                try:
                    await clients[0].send_message("failure-case")
                    raise AssertionError("failure reported success")
                except ApiError as exc:
                    assert exc.status_code == status and exc.code == code
                assert len(fake.sent) == before + 1, "automatic retry occurred"
            fake.failure = None
            stop(process)
            await start_api()
            try:
                await clients[0].send_message("old-session")
                raise AssertionError("old session survived restart")
            except ApiError as exc:
                assert exc.status_code == 401 and not clients[0].is_authenticated
        print("PASS: real Express + aiohttp/aiogram + desktop ApiClient; two profiles, single-use PIN, sender identity, confirmed delivery, 502/504 without retry, restart clears session")
    finally:
        for client in clients:
            await client.close()
        await runner.cleanup()
        for process in processes:
            if process.poll() is None:
                stop(process)
        text = "\n".join(logs)
        assert all(value not in text for value in [secret, webhook, "123456:smoke-token", *pins, *tokens])
        print("PASS: API process logs contain no test credentials, PINs or access tokens; all processes stopped")


if __name__ == "__main__":
    asyncio.run(main())
