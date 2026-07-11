from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any


class JobType(StrEnum):
    DISCOVER_LIBRARIES = "DISCOVER_LIBRARIES"
    ENSURE_RAGFLOW_DATASET = "ENSURE_RAGFLOW_DATASET"
    REFRESH_DATASET_SETTINGS = "REFRESH_DATASET_SETTINGS"
    SYNC_LIBRARY_FULL = "SYNC_LIBRARY_FULL"
    SYNC_LIBRARY_DELTA = "SYNC_LIBRARY_DELTA"
    CLASSIFY_FILE = "CLASSIFY_FILE"
    PREPARE_INGESTION_ARTIFACT = "PREPARE_INGESTION_ARTIFACT"
    UPLOAD_FILE = "UPLOAD_FILE"
    DELETE_FILE = "DELETE_FILE"
    PARSE_DOCUMENTS = "PARSE_DOCUMENTS"
    REPARSE_DOCUMENTS = "REPARSE_DOCUMENTS"
    CHECK_PARSE_STATUS = "CHECK_PARSE_STATUS"
    RECONCILE_LIBRARY = "RECONCILE_LIBRARY"
    RECONCILE_RAGFLOW_DATASET = "RECONCILE_RAGFLOW_DATASET"
    SYNC_OPENWEBUI = "SYNC_OPENWEBUI"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    DEAD = "dead"
    CANCELLED = "cancelled"


class JobPriority:
    HIGH = 10
    NORMAL = 100
    LOW = 500


HIGH_PRIORITY_TYPES = {
    JobType.DELETE_FILE,
    JobType.ENSURE_RAGFLOW_DATASET,
}

LOW_PRIORITY_TYPES = {
    JobType.RECONCILE_LIBRARY,
    JobType.RECONCILE_RAGFLOW_DATASET,
    JobType.REPARSE_DOCUMENTS,
    JobType.REFRESH_DATASET_SETTINGS,
    JobType.SYNC_OPENWEBUI,
}


@dataclass(frozen=True)
class JobSpec:
    job_type: JobType
    repo_id: str | None = None
    file_path: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int | None = None
    max_attempts: int | None = None

    def resolved_priority(self) -> int:
        if self.priority is not None:
            return self.priority
        if self.job_type in HIGH_PRIORITY_TYPES:
            return JobPriority.HIGH
        if self.job_type in LOW_PRIORITY_TYPES:
            return JobPriority.LOW
        return JobPriority.NORMAL

    def dedup_key(self) -> str:
        identity = {
            "job_type": self.job_type.value,
            "repo_id": self.repo_id,
            "file_path": self.file_path.replace("\\", "/") if self.file_path else None,
            "payload": self.payload,
        }
        canonical = json.dumps(
            identity,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"v1:{sha256(canonical).hexdigest()}"
