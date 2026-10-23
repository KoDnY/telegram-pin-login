"""Desktop PIN login. From root: python -m client.app.main; from client: python -m app.main."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import flet as ft
from dotenv import load_dotenv

from .api_client import ApiClient, ApiError


class LoginApp:
    """Keep controls and asynchronous request state together for one window."""

    def __init__(self, page: ft.Page, api: ApiClient, bot_username: str):
        self.page = page
        self.api = api
        self.busy = False
        self.message_busy = False
        self.profile_view: ft.Column | None = None
        self.message = ft.TextField(
            label="Сообщение администратору", multiline=True, min_lines=3, max_lines=8,
            hint_text="Введите текст (до 3000 символов)",
        )
        self.message_status = ft.Text("", color=ft.Colors.RED_700)
        self.send_button = ft.Button("Отправить", on_click=self.send_message)
        self.send_progress = ft.ProgressRing(width=24, height=24, visible=False)
        self.pin = ft.TextField(
            label="PIN из Telegram", hint_text="012345", max_length=6,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.InputFilter(allow=True, regex_string="[0-9]"),
            on_submit=self.sign_in,
        )
        self.status = ft.Text("", color=ft.Colors.RED_700)
        self.login_button = ft.Button("Войти", on_click=self.sign_in)
        self.progress = ft.ProgressRing(width=24, height=24, visible=False)
        username = bot_username.strip().removeprefix("@")
        configured = bool(re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)) and username != "your_bot_username"
        self.bot_link = ft.TextButton(
            "Открыть Telegram-бота", url=f"https://t.me/{username}" if configured else None,
            disabled=not configured,
        )
        self.login_view = ft.Column([
            ft.Text("Вход через Telegram", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Откройте бота, отправьте /start и введите полученный PIN. Код действует 15 минут."),
            self.bot_link,
            *([] if configured else [ft.Text("Укажите BOT_USERNAME в client/.env.")]),
            self.pin, ft.Row([self.login_button, self.progress]), self.status,
        ], spacing=16)
        self.content = ft.Column([self.login_view], spacing=20)

    def mount(self) -> None:
        self.page.title = "Вход через Telegram"
        self.page.padding = 24
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.on_disconnect = self.disconnect
        self.page.add(ft.Container(content=self.content, width=560))

    async def disconnect(self, event: Any = None) -> None:
        await self.api.close()

    async def sign_in(self, event: Any = None) -> None:
        if self.busy:
            return
        key = self.pin.value or ""
        if not re.fullmatch(r"[0-9]{6}", key):
            self.status.value = "Введите PIN из шести цифр от 0 до 9."
            self.page.update()
            return
        self.busy = True
        self.pin.disabled = self.login_button.disabled = True
        self.progress.visible = True
        self.status.value = ""
        self.page.update()
        try:
            user = await self.api.authenticate(key)
            self.pin.value = ""
            self.show_profile(user)
        except ApiError as error:
            self.status.value = error.message
        finally:
            self.busy = False
            self.pin.disabled = self.login_button.disabled = False
            self.progress.visible = False
            self.page.update()

    async def send_message(self, event: Any = None) -> None:
        if self.message_busy:
            return
        text = (self.message.value or "").strip()
        try:
            units = len(text.encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            units = 3001
        self.message_status.color = ft.Colors.RED_700
        if not 1 <= units <= 3000:
            self.message_status.value = "Введите сообщение длиной от 1 до 3000 символов."
            self.page.update()
            return
        self.message_busy = True
        self.message.disabled = self.send_button.disabled = True
        self.send_progress.visible = True
        self.message_status.value = ""
        self.page.update()
        try:
            await self.api.send_message(text)
            self.message.value = ""
            self.message_status.value = "Сообщение отправлено администратору."
            self.message_status.color = ft.Colors.GREEN_700
        except ApiError as error:
            if error.status_code == 401:
                self.api.clear_session()
                self.message.value = ""
                self.message_status.value = ""
                self.profile_view = None
                self.content.controls = [self.login_view]
                self.pin.value = ""
                self.status.value = "Сеанс завершён. Получите новый PIN в боте и войдите снова."
            else:
                # Keep the draft, especially when delivery may already have happened.
                self.message_status.value = error.message
        finally:
            self.message_busy = False
            self.message.disabled = self.send_button.disabled = False
            self.send_progress.visible = False
            self.page.update()

    def show_profile(self, user: dict[str, Any]) -> None:
        def display(field: str) -> str:
            value = user.get(field)
            return value if isinstance(value, str) and value.strip() else "Не указано"

        avatar = user.get("avatar")
        picture: ft.Control = ft.Text("Аватар отсутствует")
        if isinstance(avatar, dict) and isinstance(avatar.get("base64"), str) and avatar["base64"]:
            picture = ft.Image(
                src=avatar["base64"], width=120, height=120, fit=ft.BoxFit.COVER,
                border_radius=60, error_content=ft.Text("Аватар недоступен"),
                semantics_label="Аватар пользователя",
            )
        username = display("username")
        if username != "Не указано":
            username = "@" + username.removeprefix("@")
        self.message.value = ""
        self.message_status.value = ""
        self.message_status.color = ft.Colors.RED_700
        self.profile_view = ft.Column([
            ft.Text("Ваш профиль", size=26, weight=ft.FontWeight.BOLD),
            picture, ft.Text(f"Имя: {display('firstName')}"),
            ft.Text(f"Фамилия: {display('lastName')}"),
            ft.Text(f"Username: {username}"),
            ft.Divider(), self.message,
            ft.Row([self.send_button, self.send_progress]), self.message_status,
        ], spacing=16)
        self.content.controls = [self.profile_view]


async def main(page: ft.Page) -> None:
    # Resolve relative to this file, so launching from another directory works.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api = ApiClient(os.getenv("API_BASE_URL", "http://127.0.0.1:3000"))
    app = LoginApp(page, api, os.getenv("BOT_USERNAME", ""))
    app.mount()


if __name__ == "__main__":
    ft.run(main)
