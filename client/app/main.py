"""Desktop PIN login. From the standalone client folder: python run.py."""
from __future__ import annotations

import base64
from io import BytesIO
import os
import re
from pathlib import Path
from typing import Any

import flet as ft
import segno
from dotenv import load_dotenv

from .api_client import ApiClient, ApiError


def qr_png_base64(url: str) -> str:
    """Encode the bot link locally, keeping the QR independent of external services."""
    output = BytesIO()
    segno.make(url, micro=False, error="m").save(
        output, kind="png", scale=6, border=4, dark="black", light="white",
    )
    return base64.b64encode(output.getvalue()).decode("ascii")


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
            hint_text="Введите текст (до 3000 символов)", text_align=ft.TextAlign.CENTER,
        )
        self.message_status = ft.Text("", color=ft.Colors.RED_700, text_align=ft.TextAlign.CENTER)
        self.send_button = ft.Button("Отправить", on_click=self.send_message)
        self.send_progress = ft.ProgressRing(width=24, height=24, visible=False)
        self.pin = ft.TextField(
            label="PIN из Telegram", hint_text="012345", max_length=6, text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.InputFilter(allow=True, regex_string="[0-9]"),
            on_submit=self.sign_in,
        )
        self.status = ft.Text("", color=ft.Colors.RED_700, text_align=ft.TextAlign.CENTER)
        self.login_button = ft.Button("Войти", on_click=self.sign_in)
        self.progress = ft.ProgressRing(width=24, height=24, visible=False)
        username = bot_username.strip().removeprefix("@")
        configured = bool(re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)) and username != "your_bot_username"
        bot_url = f"https://t.me/{username}" if configured else None
        self.bot_link = ft.Button(
            "Открыть бота в Telegram", url=bot_url, disabled=not configured,
        )
        self.bot_qr = ft.Image(
            src=qr_png_base64(bot_url) if bot_url else "",
            width=220, height=220, fit=ft.BoxFit.CONTAIN,
            semantics_label="QR-код для перехода в Telegram-бота",
            visible=configured,
        )
        qr_section = ([
            ft.Container(
                content=self.bot_qr, padding=12, bgcolor=ft.Colors.WHITE,
                border_radius=12,
            ),
            ft.Text(
                "Сканируйте QR-код телефоном или откройте бота кнопкой ниже.",
                text_align=ft.TextAlign.CENTER,
            ),
        ] if configured else [])
        self.login_view = ft.Column([
            ft.Text("Вход через Telegram", size=26, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text("Откройте бота, отправьте /start и введите полученный PIN. Код действует 15 минут.", text_align=ft.TextAlign.CENTER),
            *qr_section,
            self.bot_link,
            *([] if configured else [ft.Text("Укажите BOT_USERNAME в client/.env.", text_align=ft.TextAlign.CENTER)]),
            self.pin, ft.Row([self.login_button, self.progress], alignment=ft.MainAxisAlignment.CENTER), self.status,
        ], spacing=16, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        # The scrollable column shrinks to its content when there is room, and
        # is constrained by the viewport when the window becomes short.
        self.content = ft.Column(
            [self.login_view], spacing=20, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, scroll=ft.ScrollMode.AUTO,
        )

    def mount(self) -> None:
        self.page.title = "Вход через Telegram"
        self.page.padding = 24
        self.page.scroll = None
        self.page.on_disconnect = self.disconnect
        self.page.add(ft.Container(
            expand=True, alignment=ft.Alignment.CENTER,
            content=ft.Container(content=self.content, width=560),
        ))

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
        picture: ft.Control = ft.Text("Аватар отсутствует", text_align=ft.TextAlign.CENTER)
        if isinstance(avatar, dict) and isinstance(avatar.get("base64"), str) and avatar["base64"]:
            picture = ft.Image(
                src=avatar["base64"], width=120, height=120, fit=ft.BoxFit.COVER,
                border_radius=60, error_content=ft.Text("Аватар недоступен", text_align=ft.TextAlign.CENTER),
                semantics_label="Аватар пользователя",
            )
        username = display("username")
        if username != "Не указано":
            username = "@" + username.removeprefix("@")
        self.message.value = ""
        self.message_status.value = ""
        self.message_status.color = ft.Colors.RED_700
        self.profile_view = ft.Column([
            ft.Text("Ваш профиль", size=26, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            picture, ft.Text(f"Имя: {display('firstName')}", text_align=ft.TextAlign.CENTER),
            ft.Text(f"Фамилия: {display('lastName')}", text_align=ft.TextAlign.CENTER),
            ft.Text(f"Username: {username}", text_align=ft.TextAlign.CENTER),
            ft.Divider(), self.message,
            ft.Row([self.send_button, self.send_progress], alignment=ft.MainAxisAlignment.CENTER), self.message_status,
        ], spacing=16, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        self.content.controls = [self.profile_view]


async def main(page: ft.Page) -> None:
    # Resolve relative to this file, so launching from another directory works.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api = ApiClient(os.getenv("API_BASE_URL", "http://127.0.0.1:3000"))
    app = LoginApp(page, api, os.getenv("BOT_USERNAME", ""))
    app.mount()


if __name__ == "__main__":
    ft.run(main)
