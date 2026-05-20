from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from seafile_ragflow_connector.jobs.types import JobSpec, JobType

UPLOAD_OPERATIONS = {"new", "modified"}
DELETE_OPERATIONS = {"removed"}


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
