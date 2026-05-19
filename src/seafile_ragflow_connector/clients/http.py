from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def unwrap_response(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if response.is_error:
        raise ApiError(
            f"HTTP {response.status_code} returned by {response.request.method} {response.request.url}",
            status_code=response.status_code,
            payload=payload,
        )

    if isinstance(payload, Mapping):
        code = payload.get("code")
        if code not in (None, 0, "0", 200):
            raise ApiError("API returned an error code", status_code=response.status_code, payload=payload)
        if "data" in payload:
            return payload["data"]
    return payload


def make_client(base_url: str, headers: Mapping[str, str], timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(base_url=base_url.rstrip("/"), headers=dict(headers), timeout=timeout)

