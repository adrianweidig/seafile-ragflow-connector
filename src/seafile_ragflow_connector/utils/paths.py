from __future__ import annotations

from pathlib import PurePosixPath


def normalize_seafile_path(path: str) -> str:
    normalized = str(PurePosixPath("/", path.lstrip("/")))
    return normalized


def source_extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower()

