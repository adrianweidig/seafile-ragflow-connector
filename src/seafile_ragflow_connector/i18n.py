from __future__ import annotations

import json
import locale
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from string import Formatter
from typing import Any

DEFAULT_LANGUAGE = "de"
FALLBACK_LANGUAGE = "de"
SUPPORTED_LANGUAGES = (
    "de",
    "en",
    "es",
    "fr",
    "it",
    "pt",
    "nl",
    "pl",
    "tr",
    "uk",
    "zh",
    "ja",
    "ar",
)
LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
    "uk": "Українська",
    "zh": "中文",
    "ja": "日本語",
    "ar": "العربية",
}


def normalize_language(value: str | None) -> str | None:
    """Return a supported language code from a locale-like value."""
    if not value:
        return None
    for raw_part in str(value).replace(";", ":").split(":"):
        part = raw_part.strip()
        if not part or part.upper() in {"C", "POSIX"}:
            continue
        language = part.split(".", 1)[0].split("@", 1)[0].replace("_", "-").lower()
        code = language.split("-", 1)[0]
        if code in SUPPORTED_LANGUAGES:
            return code
    return None


def detect_language(
    *,
    explicit: str | None = None,
    configured: str | None = None,
    environ: Mapping[str, str] | None = None,
    system_locale: str | None = None,
) -> str:
    """Choose the user-facing language with German as the stable fallback."""
    for candidate in (explicit, configured):
        language = normalize_language(candidate)
        if language:
            return language

    detected_system_locale = system_locale
    if detected_system_locale is None:
        try:
            message_locale = getattr(locale, "LC_MESSAGES", locale.LC_CTYPE)
            detected_system_locale = locale.getlocale(message_locale)[0]
        except (AttributeError, TypeError, ValueError):
            detected_system_locale = None
    language = normalize_language(detected_system_locale)
    if language:
        return language

    env = os.environ if environ is None else environ
    for key in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        language = normalize_language(env.get(key))
        if language:
            return language
    return DEFAULT_LANGUAGE


def language_from_settings(settings: object | None = None, *, explicit: str | None = None) -> str:
    configured = getattr(settings, "connector_language", None)
    language = normalize_language(explicit) or normalize_language(configured)
    return language or DEFAULT_LANGUAGE


@dataclass(frozen=True)
class Localizer:
    language: str = DEFAULT_LANGUAGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "language", normalize_language(self.language) or DEFAULT_LANGUAGE)

    def text(self, key: str, **params: Any) -> str:
        value = _lookup(self.language, key)
        if value is None and self.language != FALLBACK_LANGUAGE:
            value = _lookup(FALLBACK_LANGUAGE, key)
        if value is None:
            return key
        return _format_message(str(value), params)

    def plural(self, key: str, count: int, **params: Any) -> str:
        suffix = "one" if count == 1 else "other"
        values = dict(params)
        values.setdefault("count", count)
        return self.text(f"{key}.{suffix}", **values)


def localizer_for(settings: object | None = None, *, explicit: str | None = None) -> Localizer:
    return Localizer(language_from_settings(settings, explicit=explicit))


def t(key: str, **params: Any) -> str:
    return Localizer(detect_language()).text(key, **params)


def _format_message(template: str, params: Mapping[str, Any]) -> str:
    if not params:
        return template
    allowed = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    safe_params = {key: value for key, value in params.items() if key in allowed}
    return template.format(**safe_params)


def _lookup(language: str, key: str) -> Any:
    value: Any = _catalog(language)
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _catalog(language: str) -> dict[str, Any]:
    return _load_catalogs().get(language, _load_catalogs()[FALLBACK_LANGUAGE])


@lru_cache
def _load_catalogs() -> dict[str, dict[str, Any]]:
    catalogs: dict[str, dict[str, Any]] = {}
    for language in SUPPORTED_LANGUAGES:
        with resources.files(__package__).joinpath("locales", f"{language}.json").open(
            "r",
            encoding="utf-8",
        ) as handle:
            catalogs[language] = json.load(handle)
    return catalogs
