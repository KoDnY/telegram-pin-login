"""Telegram /start: collect an optional avatar and request a server PIN."""

import asyncio
import base64
from io import BytesIO
import re

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from .api_client import ApiClient, ApiClientError

MAX_AVATAR_BYTES = 1024 * 1024


class _AvatarBuffer(BytesIO):
    """Bound downloads even when Telegram's size metadata is missing."""

    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > MAX_AVATAR_BYTES:
            raise ValueError("Avatar too large")
        return super().write(data)


async def _download_avatar(bot: Bot, user_id: int) -> dict[str, str] | None:
    photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
    if not photos.photos or not photos.photos[0]:
        return None
    photo = min(photos.photos[0], key=lambda item: item.width * item.height)
    if photo.file_size is not None and photo.file_size > MAX_AVATAR_BYTES:
        return None
    file = await bot.get_file(photo.file_id)
    if file.file_size is not None and file.file_size > MAX_AVATAR_BYTES:
        return None
    if not file.file_path:
        return None
    with _AvatarBuffer() as destination:
        await bot.download(file, destination=destination, timeout=10)
        data = destination.getvalue()
    if data.startswith(b"\xff\xd8\xff"):
        mime_type = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    else:
        return None
    return {"mimeType": mime_type, "base64": base64.b64encode(data).decode("ascii")}


async def _avatar_or_none(bot: Bot, user_id: int) -> dict[str, str] | None:
    try:
        return await asyncio.wait_for(_download_avatar(bot, user_id), timeout=10)
    except Exception:
        # An optional picture must never block login; do not log token-bearing URLs.
        return None


async def start(message: Message, bot: Bot, api_client: ApiClient) -> None:
    """Dependencies are supplied by Dispatcher as bot and api_client."""
    if message.chat.type != "private" or message.from_user is None:
        await message.answer("Для получения кода откройте личный чат с ботом.", parse_mode=None)
        return
    user = message.from_user
    username = user.username
    if username is not None and re.fullmatch(r"[A-Za-z0-9_]{1,32}", username) is None:
        username = None
    profile = {
        "telegramId": user.id,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "username": username,
        "avatar": await _avatar_or_none(bot, user.id),
    }
    try:
        result = await api_client.issue_pin(profile)
    except ApiClientError:
        await message.answer(
            "Не удалось получить код входа. Попробуйте /start немного позже.",
            parse_mode=None,
        )
        return
    await message.answer(
        f"Ваш PIN: {result.pin}\n"
        "Код действует 15 минут и используется один раз.\n"
        "Введите его в приложении. Новый /start отменит предыдущий код.",
        parse_mode=None,
    )


def create_router() -> Router:
    """Return a fresh router so independent dispatchers can register it safely."""
    router = Router(name="login")
    router.message.register(start, CommandStart())
    return router
