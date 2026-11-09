"""Small asynchronous client for the bot-only PIN endpoint."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
import re

import httpx


class ApiClientError(Exception):
    """Sanitized failure: never carries response bodies, PINs or credentials."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class PinResult:
    pin: str
    expires_at: str


class ApiClient:
    def __init__(
        self,
        api_base_url: str,
        internal_api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide client or transport, not both")
        self._url = api_base_url.rstrip("/") + "/internal/pins"
        self._key = internal_api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(transport=transport)

    async def issue_pin(self, user: Mapping[str, Any]) -> PinResult:
        try:
            response = await self._client.post(
                self._url,
                headers={"X-Internal-Key": self._key},
                json={"user": dict(user)},
                timeout=10.0,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise ApiClientError("TIMEOUT") from None
        except httpx.RequestError:
            raise ApiClientError("NETWORK_ERROR") from None

        if response.status_code != 201:
            raise ApiClientError("HTTP_ERROR", status_code=response.status_code)
        try:
            data = response.json()
            pin, expires_at = data["pin"], data["expiresAt"]
            if not isinstance(pin, str) or re.fullmatch(r"[0-9]{6}", pin) is None:
                raise ValueError
            if not isinstance(expires_at, str):
                raise ValueError
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.utcoffset() is None or expiry.utcoffset().total_seconds() != 0:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ApiClientError("INVALID_RESPONSE") from None
        return PinResult(pin=pin, expires_at=expires_at)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "ApiClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
