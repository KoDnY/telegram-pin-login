import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendMessage

from bot.app.main import Config, create_app


class FakeBot:
    def __init__(self):
        self.session = SimpleNamespace(json_loads=json.loads, close=AsyncMock())
        self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=77))
        self.set_webhook = AsyncMock()
        self.get_webhook_info = AsyncMock(return_value=SimpleNamespace(url="https://example.com/telegram/webhook"))
        self.delete_webhook = AsyncMock()
        self.id = 123


class FakeDispatcher:
    def __init__(self):
        self.emit_startup = AsyncMock()
        self.emit_shutdown = AsyncMock()
        self.feed_raw_update = AsyncMock(return_value=None)


async def setup_client(admin=123, manage=False):
    bot, dispatcher = FakeBot(), FakeDispatcher()
    api = SimpleNamespace(aclose=AsyncMock())
    app = create_app(Config("123:test", "internal-key", "webhook-secret", "https://example.com", admin_chat_id=admin),
                     bot=bot, dispatcher=dispatcher, api_client=api, manage_webhook=manage)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, bot, dispatcher, api


BODY = {"sender": {"telegramId": 123, "firstName": "Иван", "username": None}, "text": "  Привет!  "}
HEADERS = {"X-Internal-Key": "internal-key"}


@pytest.mark.asyncio
async def test_admin_delivery():
    client, bot, _, _ = await setup_client()
    try:
        response = await client.post("/internal/messages", json=BODY, headers=HEADERS)
        assert response.status == 200
        assert await response.json() == {"status": "sent", "telegramMessageId": 77}
        arguments = bot.send_message.call_args.kwargs
        assert arguments["text"].endswith("\n\nПривет!")
        assert "Иван" in arguments["text"] and "123" in arguments["text"]
        assert arguments["parse_mode"] is None and arguments["request_timeout"] == 10
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
async def test_internal_secret(headers):
    client, bot, _, _ = await setup_client()
    try:
        response = await client.post("/internal/messages", json=BODY, headers=headers)
        assert response.status == 403
        bot.send_message.assert_not_called()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {**BODY, "text": "  "}, {**BODY, "text": "x" * 3001}, {**BODY, "text": "😀" * 1501},
    {**BODY, "sender": {"telegramId": True, "firstName": "A"}},
    {**BODY, "sender": {"telegramId": 9007199254740992, "firstName": "A"}},
    {**BODY, "text": "\ud800"},
    {**BODY, "sender": {"telegramId": 1, "firstName": "\ud800"}},
    {**BODY, "sender": {"telegramId": 1, "firstName": "A", "username": "<bad>"}}])
async def test_invalid_message(body):
    client, bot, _, _ = await setup_client()
    try:
        response = await client.post("/internal/messages", json=body, headers=HEADERS)
        assert response.status == 400
        bot.send_message.assert_not_called()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [None, 0])
async def test_missing_admin(admin):
    client, bot, _, _ = await setup_client(admin)
    try:
        response = await client.post("/internal/messages", json=BODY, headers=HEADERS)
        assert response.status == 502
        assert "ADMIN_CHAT_ID" in (await response.json())["error"]["message"]
        bot.send_message.assert_not_called()
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status,code", [
    (TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="sensitive"), 502, "TELEGRAM_DELIVERY_FAILED"),
    (TimeoutError("sensitive"), 504, "DELIVERY_UNCONFIRMED"),
    (TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="sensitive"), 504, "DELIVERY_UNCONFIRMED")])
async def test_delivery_failure(failure, status, code):
    client, bot, _, _ = await setup_client()
    bot.send_message.side_effect = failure
    try:
        response = await client.post("/internal/messages", json=BODY, headers=HEADERS)
        assert response.status == status
        payload = await response.json()
        assert payload["error"]["code"] == code
        assert "sensitive" not in json.dumps(payload)
        assert bot.send_message.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_webhook_secret_and_dedupe():
    import asyncio
    client, bot, dispatcher, _ = await setup_client()
    update = {"update_id": 42}
    try:
        assert (await client.post("/telegram/webhook", json=update)).status == 401
        headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"}
        for _ in range(2):
            assert (await client.post("/telegram/webhook", json=update, headers=headers)).status == 200
        await asyncio.sleep(0)
        assert dispatcher.feed_raw_update.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("manage", [False, True])
async def test_lifecycle(manage):
    client, bot, dispatcher, api = await setup_client(manage=manage)
    await client.close()
    assert bot.set_webhook.call_count == int(manage)
    assert bot.delete_webhook.call_count == int(manage)
    dispatcher.emit_startup.assert_awaited_once()
    dispatcher.emit_shutdown.assert_awaited_once()
    api.aclose.assert_awaited_once()
    assert bot.session.close.await_count >= 1


@pytest.mark.asyncio
async def test_long_sender_name_is_bounded_without_truncating_text():
    client, bot, _, _ = await setup_client()
    try:
        body = {**BODY, "sender": {"telegramId": 1, "firstName": "😀" * 1000, "username": None}, "text": "😀" * 1500}
        response = await client.post("/internal/messages", json=body, headers=HEADERS)
        assert response.status == 200
        sent = bot.send_message.call_args.kwargs["text"]
        assert sent.endswith(body["text"])
        assert len(sent.encode("utf-16-le")) // 2 <= 4096
    finally:
        await client.close()
