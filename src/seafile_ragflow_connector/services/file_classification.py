from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass, field

from seafile_ragflow_connector.utils.paths import normalize_seafile_path, source_extension


TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/sql",
}


@dataclass(frozen=True)
class FilePolicy:
    allow_unknown_text_files: bool = True
    allow_extensions: frozenset[str] = field(default_factory=frozenset)
    deny_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {".exe", ".dll", ".so", ".zip", ".tar", ".gz", ".7z", ".tmp", ".part"}
        )
    )
    text_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                ".ada",
                ".adb",
                ".ads",
                ".txt",
                ".md",
                ".rst",
                ".py",
                ".js",
                ".ts",
                ".java",
                ".c",
                ".cpp",
                ".h",
                ".sql",
                ".xml",
                ".json",
                ".yaml",
                ".yml",
                ".ini",
                ".cfg",
                ".log",
            }
        )
    )
    binary_direct_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset({".pdf", ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg"})
    )
    default_text_ingestion_strategy: str = "text_projection"
    max_file_size_bytes: int = 1024 * 1024 * 1024
    exclude_regex: str | None = r"(^/\.|/\.|~$|\.tmp$|\.part$)"


@dataclass(frozen=True)
class FileClassification:
    path: str
    normalized_path: str
    source_extension: str
    detected_mime: str | None
    detected_encoding: str | None
    is_text: bool
    ingestion_strategy: str
    should_ingest: bool
    reason: str


def _looks_like_text(data: bytes) -> tuple[bool, str | None]:
    if not data:
        return True, "utf-8"
    if b"\x00" in data[:8192]:
        return False, None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return True, encoding

    sample = data[:8192]
    control_bytes = sum(1 for byte in sample if byte < 32 and byte not in (9, 10, 12, 13))
    if sample and control_bytes / len(sample) > 0.05:
        return False, None

    try:
        data.decode("latin-1")
    except UnicodeDecodeError:
        return False, None
    return True, "latin-1"


def _detected_mime(path: str) -> str | None:
    guessed, _ = mimetypes.guess_type(path)
    return guessed


def classify_file(path: str, data: bytes, policy: FilePolicy | None = None) -> FileClassification:
    policy = policy or FilePolicy()
    normalized_path = normalize_seafile_path(path)
    extension = source_extension(path)
    mime = _detected_mime(path)

    if policy.exclude_regex and re.search(policy.exclude_regex, normalized_path):
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=None,
            is_text=False,
            ingestion_strategy="skip",
            should_ingest=False,
            reason="path_excluded",
        )

    if len(data) > policy.max_file_size_bytes:
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=None,
            is_text=False,
            ingestion_strategy="skip",
            should_ingest=False,
            reason="file_too_large",
        )

    if extension in policy.deny_extensions:
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=None,
            is_text=False,
            ingestion_strategy="skip",
            should_ingest=False,
            reason="extension_denied",
        )

    if policy.allow_extensions and extension not in policy.allow_extensions:
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=None,
            is_text=False,
            ingestion_strategy="skip",
            should_ingest=False,
            reason="extension_not_allowed",
        )

    if extension in policy.binary_direct_extensions:
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=None,
            is_text=False,
            ingestion_strategy="direct",
            should_ingest=True,
            reason="binary_direct_extension",
        )

    is_known_text_mime = bool(
        mime
        and (mime.startswith(TEXT_MIME_PREFIXES) or mime in TEXT_MIME_TYPES)
    )
    is_text, encoding = _looks_like_text(data)
    if extension in policy.text_extensions or is_known_text_mime or (
        policy.allow_unknown_text_files and is_text
    ):
        return FileClassification(
            path=path,
            normalized_path=normalized_path,
            source_extension=extension,
            detected_mime=mime,
            detected_encoding=encoding,
            is_text=is_text,
            ingestion_strategy=policy.default_text_ingestion_strategy,
            should_ingest=True,
            reason="text_detected",
        )

    return FileClassification(
        path=path,
        normalized_path=normalized_path,
        source_extension=extension,
        detected_mime=mime,
        detected_encoding=encoding,
        is_text=is_text,
        ingestion_strategy="skip",
        should_ingest=False,
        reason="unknown_binary_or_disallowed",
    )

