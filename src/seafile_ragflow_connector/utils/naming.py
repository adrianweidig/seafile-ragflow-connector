from __future__ import annotations

import re
import unicodedata


_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_SLUG_DASH_RE = re.compile(r"-+")


def slugify(value: str, fallback: str = "library") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_INVALID_RE.sub("-", ascii_value)
    slug = _SLUG_DASH_RE.sub("-", slug).strip("-")
    return slug or fallback


def build_dataset_name(
    library_name: str,
    repo_id: str,
    *,
    prefix: str = "seafile__",
    max_length: int = 128,
    repo_prefix_length: int = 8,
) -> str:
    repo_prefix = repo_id.replace("-", "")[:repo_prefix_length].lower()
    suffix = f"__{repo_prefix}"
    available_slug_length = max_length - len(prefix) - len(suffix)
    if available_slug_length < 8:
        msg = "dataset name max_length is too small for prefix and repo suffix"
        raise ValueError(msg)
    slug = slugify(library_name)[:available_slug_length].strip("-") or "library"
    return f"{prefix}{slug}{suffix}"

