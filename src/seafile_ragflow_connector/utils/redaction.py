from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


SECRET_KEY_PARTS = (
    "authorization",
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
)


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SECRET_KEY_PARTS)


def redact_value(value: Any) -> Any:
    if isinstance(value, str) and value:
        return "***"
    return value


def redact_mapping(mapping: MutableMapping[str, Any] | Mapping[str, Any]) -> MutableMapping[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        if is_secret_key(str(key)):
            redacted[str(key)] = redact_value(value)
        elif isinstance(value, Mapping):
            redacted[str(key)] = redact_mapping(value)
        else:
            redacted[str(key)] = value
    return redacted

