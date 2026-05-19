from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscoveredLibrary:
    repo_id: str
    name: str
    owner_email: str | None
    encrypted: bool
    virtual: bool
    seafile_mtime: int | None
    head_commit_id: str | None


def normalize_library(raw: dict[str, Any]) -> DiscoveredLibrary:
    repo_id = str(raw.get("id") or raw.get("repo_id") or raw.get("repoID") or "")
    if not repo_id:
        msg = f"Seafile library record has no repo id: {raw}"
        raise ValueError(msg)
    return DiscoveredLibrary(
        repo_id=repo_id,
        name=str(raw.get("name") or raw.get("repo_name") or repo_id),
        owner_email=raw.get("owner") or raw.get("owner_email"),
        encrypted=bool(raw.get("encrypted", False)),
        virtual=bool(raw.get("virtual", False) or raw.get("is_virtual", False)),
        seafile_mtime=raw.get("mtime"),
        head_commit_id=raw.get("head_commit_id") or raw.get("head_cmmt_id"),
    )


def should_skip_library(
    library: DiscoveredLibrary,
    *,
    skip_encrypted: bool = True,
    skip_virtual: bool = True,
) -> tuple[bool, str | None]:
    if skip_encrypted and library.encrypted:
        return True, "encrypted"
    if skip_virtual and library.virtual:
        return True, "virtual"
    return False, None

