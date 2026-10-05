from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.utils.paths import normalize_seafile_path

UPLOAD_OPERATIONS = {"new", "modified"}
DELETE_OPERATIONS = {"removed"}


class CommitSnapshotClient(Protocol):
    def list_dir_at_commit(
        self,
        repo_id: str,
        commit_id: str,
        path: str = "/",
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    normalized_path: str
    object_id: str | None
    size: int | None
    mtime: int | None
    is_directory: bool
    raw: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "normalized_path": self.normalized_path,
            "object_id": self.object_id,
            "size": self.size,
            "mtime": self.mtime,
            "is_directory": self.is_directory,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class SnapshotChange:
    operation: str
    path: str
    entry: SnapshotEntry | None = None
    old_path: str | None = None


def capture_commit_snapshot(
    client: CommitSnapshotClient,
    repo_id: str,
    commit_id: str,
    *,
    scope: str = "/",
) -> list[SnapshotEntry]:
    normalized_scope = normalize_seafile_path(scope)
    pending = [normalized_scope]
    visited: set[str] = set()
    entries: list[SnapshotEntry] = []
    while pending:
        directory = pending.pop()
        if directory in visited:
            raise RuntimeError(f"Seafile snapshot directory loop detected: {directory}")
        visited.add(directory)
        for raw in client.list_dir_at_commit(repo_id, commit_id, directory):
            name = str(raw.get("name") or "").strip()
            if not name or "/" in name or "\\" in name:
                continue
            path = _join_path(directory, name)
            is_directory = _is_directory(raw)
            entry = SnapshotEntry(
                path=path,
                normalized_path=normalize_seafile_path(path),
                object_id=_string_or_none(
                    raw.get("id") or raw.get("obj_id") or raw.get("oid")
                ),
                size=_int_or_none(raw.get("size")),
                mtime=_int_or_none(raw.get("mtime")),
                is_directory=is_directory,
                raw=dict(raw),
            )
            entries.append(entry)
            if is_directory:
                pending.append(entry.normalized_path)
    entries.sort(key=lambda entry: entry.normalized_path)
    return entries


def snapshot_entries_from_records(
    records: Iterable[Mapping[str, Any]],
) -> list[SnapshotEntry]:
    return [
        SnapshotEntry(
            path=str(record["path"]),
            normalized_path=str(record["normalized_path"]),
            object_id=_string_or_none(record.get("object_id")),
            size=_int_or_none(record.get("size")),
            mtime=_int_or_none(record.get("mtime")),
            is_directory=bool(record.get("is_directory", False)),
            raw=dict(record.get("raw") or {}),
        )
        for record in records
    ]


def diff_snapshots(
    baseline: Iterable[SnapshotEntry],
    target: Iterable[SnapshotEntry],
) -> list[SnapshotChange]:
    old = {entry.normalized_path: entry for entry in baseline if not entry.is_directory}
    new = {entry.normalized_path: entry for entry in target if not entry.is_directory}
    removed_paths = set(old) - set(new)
    added_paths = set(new) - set(old)
    changes: list[SnapshotChange] = []

    removed_by_object = _unique_paths_by_object(old, removed_paths)
    added_by_object = _unique_paths_by_object(new, added_paths)
    for object_id in sorted(set(removed_by_object) & set(added_by_object)):
        old_path = removed_by_object[object_id]
        new_path = added_by_object[object_id]
        changes.append(
            SnapshotChange(
                "renamed",
                path=new_path,
                old_path=old_path,
                entry=new[new_path],
            )
        )
        removed_paths.remove(old_path)
        added_paths.remove(new_path)

    changes.extend(
        SnapshotChange("removed", path=path, entry=old[path])
        for path in sorted(removed_paths)
    )
    changes.extend(
        SnapshotChange("new", path=path, entry=new[path])
        for path in sorted(added_paths)
    )
    for path in sorted(set(old) & set(new)):
        if _entry_changed(old[path], new[path]):
            changes.append(SnapshotChange("modified", path=path, entry=new[path]))
    return changes


def snapshot_changes_to_jobs(repo_id: str, changes: Iterable[SnapshotChange]) -> list[JobSpec]:
    return map_commit_diff_to_jobs(
        repo_id,
        [
            {
                "op": change.operation,
                "path": change.path,
                "old_path": change.old_path,
                "new_path": change.path if change.operation == "renamed" else None,
                "object_id": change.entry.object_id if change.entry else None,
            }
            for change in changes
        ],
    )


def _operation(entry: dict[str, Any]) -> str:
    value = entry.get("op") or entry.get("operation") or entry.get("type") or entry.get("status")
    return str(value or "").lower()


def _path(entry: dict[str, Any]) -> str | None:
    value = entry.get("path") or entry.get("file_path") or entry.get("name")
    return str(value) if value else None


def map_commit_diff_to_jobs(repo_id: str, entries: Iterable[dict[str, Any]]) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    for entry in entries:
        op = _operation(entry)
        path = _path(entry)
        if op in UPLOAD_OPERATIONS and path:
            jobs.append(
                JobSpec(
                    JobType.UPLOAD_FILE,
                    repo_id=repo_id,
                    file_path=path,
                    payload={"operation": op},
                )
            )
        elif op == "renamed":
            old_path = entry.get("old_path") or entry.get("oldname")
            new_path = entry.get("new_path") or entry.get("newname") or path
            if old_path:
                jobs.append(
                    JobSpec(
                        JobType.DELETE_FILE,
                        repo_id=repo_id,
                        file_path=str(old_path),
                        payload={"operation": op},
                    )
                )
            if new_path:
                jobs.append(
                    JobSpec(
                        JobType.UPLOAD_FILE,
                        repo_id=repo_id,
                        file_path=str(new_path),
                        payload={"operation": op},
                    )
                )
        elif op in DELETE_OPERATIONS and path:
            jobs.append(
                JobSpec(
                    JobType.DELETE_FILE,
                    repo_id=repo_id,
                    file_path=path,
                    payload={"operation": op},
                )
            )
        elif op == "deldir" and path:
            jobs.append(
                JobSpec(
                    JobType.DELETE_FILE,
                    repo_id=repo_id,
                    file_path=path,
                    payload={"operation": op, "recursive": True},
                )
            )
        elif op == "newdir" and path:
            jobs.append(
                JobSpec(
                    JobType.SYNC_LIBRARY_FULL,
                    repo_id=repo_id,
                    file_path=path,
                    payload={"operation": op, "scope": path},
                )
            )
    return jobs


def _unique_paths_by_object(
    entries: Mapping[str, SnapshotEntry],
    paths: set[str],
) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for path in paths:
        object_id = entries[path].object_id
        if object_id:
            grouped.setdefault(object_id, []).append(path)
    return {
        object_id: object_paths[0]
        for object_id, object_paths in grouped.items()
        if len(object_paths) == 1
    }


def _entry_changed(old: SnapshotEntry, new: SnapshotEntry) -> bool:
    if old.object_id and new.object_id:
        return old.object_id != new.object_id
    return (old.object_id, old.size, old.mtime) != (
        new.object_id,
        new.size,
        new.mtime,
    )


def _join_path(parent: str, name: str) -> str:
    if parent == "/":
        return f"/{name}"
    return f"{parent.rstrip('/')}/{name}"


def _is_directory(item: Mapping[str, Any]) -> bool:
    return str(item.get("type") or item.get("kind") or "").lower() in {
        "dir",
        "directory",
        "folder",
    }


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
