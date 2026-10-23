"""Asynchronous desktop API connection; credentials live only in memory."""
from __future__ import annotations

from typing import Any

import httpx


class ApiError(Exception):
    """Safe error suitable for displaying to the user (never response bodies)."""

    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ApiClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if client is not None and transport is not None:
            raise ValueError("Pass client or transport, not both")
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=15.0, transport=transport
        )
        self._owns_client = client is None
        self._access_token: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def clear_session(self) -> None:
        self._access_token = None

    async def authenticate(self, key: str) -> dict[str, Any]:
        """Exchange a PIN string (preserving leading zeros) for a profile."""
        self.clear_session()
        data = await self._request("/auth", {"key": key})
        user, token = data.get("user"), data.get("accessToken")
        if not isinstance(user, dict) or not isinstance(token, str) or not token:
            raise ApiError("INVALID_RESPONSE", "Сервер вернул некорректный ответ.")
        self._access_token = token
        return user

    async def send_message(self, text: str) -> dict[str, Any]:
        if self._access_token is None:
            raise ApiError("UNAUTHORIZED", "Сначала войдите в приложение.", 401)
        data = await self._request(
            "/messages", {"text": text},
            headers={"Authorization": f"Bearer {self._access_token}"},
            delivery=True,
        )
        if data.get("status") != "sent":
            raise ApiError("DELIVERY_UNCONFIRMED", "Результат доставки неизвестен. Не повторяйте отправку автоматически.")
        return data

    async def _request(
        self, path: str, body: dict[str, Any], *,
        headers: dict[str, str] | None = None, delivery: bool = False,
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body, headers=headers, timeout=15.0)
        except httpx.RequestError as exc:
            if delivery:
                raise ApiError("DELIVERY_UNCONFIRMED", "Результат доставки неизвестен. Проверьте связь перед повторной отправкой.") from None
            raise ApiError("NETWORK_ERROR", "Не удалось связаться с сервером. Проверьте подключение.") from None
        if response.status_code == 401:
            self.clear_session()
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code != 200:
            error = data.get("error") if isinstance(data, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_messages = {
                "INVALID_PIN_FORMAT": "Введите PIN из шести цифр.",
                "INVALID_PIN": "PIN недействителен. Получите новый код в боте.",
                "UNAUTHORIZED": "Сеанс завершён. Войдите снова.",
                "INVALID_TEXT": "Введите сообщение длиной от 1 до 3000 символов.",
                "DELIVERY_FAILED": "Не удалось отправить сообщение администратору.",
                "DELIVERY_UNCONFIRMED": "Результат доставки неизвестен. Не повторяйте отправку автоматически.",
            }
            if not isinstance(code, str) or code not in safe_messages:
                code = "SERVER_ERROR"
            raise ApiError(code, safe_messages.get(code, "Ошибка сервера. Попробуйте позже."), response.status_code)
        if not isinstance(data, dict):
            if delivery:
                raise ApiError("DELIVERY_UNCONFIRMED", "Результат доставки неизвестен.")
            raise ApiError("INVALID_RESPONSE", "Сервер вернул некорректный ответ.")
        return data

    async def close(self) -> None:
        self.clear_session()
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
