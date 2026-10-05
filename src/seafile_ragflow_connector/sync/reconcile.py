from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
from seafile_ragflow_connector.sync.delta_sync import SnapshotEntry


class RAGFlowDocumentReader(Protocol):
    def iter_documents(self, dataset_id: str) -> Iterable[dict[str, Any]]: ...


@dataclass(frozen=True)
class ReconcilePlan:
    repo_id: str | None = None
    dataset_id: str | None = None
    scope: str = "/"
    commit_id: str | None = None
    snapshot_id: int | None = None
    jobs: list[JobSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    categories: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def has_drift(self) -> bool:
        return any(self.categories.values())


class Reconciler:
    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        ragflow_client: RAGFlowDocumentReader | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.ragflow_client = ragflow_client

    def plan_library_reconcile(
        self,
        repo_id: str | None = None,
        dataset_id: str | None = None,
        *,
        source_entries: Iterable[SnapshotEntry] | None = None,
        target_documents: Iterable[Mapping[str, Any]] | None = None,
        scope: str = "/",
        commit_id: str | None = None,
        snapshot_id: int | None = None,
    ) -> ReconcilePlan:
        if self.session_factory is None or not repo_id or not dataset_id:
            return ReconcilePlan(
                repo_id=repo_id,
                dataset_id=dataset_id,
                scope=scope,
                commit_id=commit_id,
                snapshot_id=snapshot_id,
                warnings=["library reconcile planning requires repo, dataset and database state"]
            )
        source_files = {
            entry.normalized_path: entry
            for entry in (source_entries or [])
            if not entry.is_directory
        }
        with self.session_factory() as session:
            files = list(session.scalars(select(File).where(File.repo_id == repo_id)).all())
            versions = list(
                session.scalars(
                    select(FileDocumentVersion).where(
                        FileDocumentVersion.repo_id == repo_id
                    )
                ).all()
            )
        local_files = {row.normalized_path: row for row in files}
        documents = list(
            target_documents
            if target_documents is not None
            else self._target_documents(dataset_id)
        )
        target_ids = {
            document_id
            for document in documents
            if (document_id := _document_id(document)) is not None
        }
        known_target_ids = {
            version.document_id for version in versions if version.document_id is not None
        }
        categories: dict[str, list[dict[str, Any]]] = {
            "missing_local_state": [],
            "missing_source": [],
            "missing_target": [],
            "parse_stuck": [],
            "parse_failed": [],
            "orphan_managed_target": [],
        }
        jobs: list[JobSpec] = []
        scheduled_upload_paths: set[str] = set()

        for path in sorted(set(source_files) - set(local_files)):
            entry = source_files[path]
            categories["missing_local_state"].append(
                {"path": path, "object_id": entry.object_id}
            )
            jobs.append(
                JobSpec(
                    JobType.UPLOAD_FILE,
                    repo_id=repo_id,
                    file_path=path,
                    payload={"operation": "reconcile_missing_local"},
                )
            )
            scheduled_upload_paths.add(path)
        if source_entries is not None:
            for path in sorted(set(local_files) - set(source_files)):
                categories["missing_source"].append({"path": path})
                jobs.append(
                    JobSpec(
                        JobType.DELETE_FILE,
                        repo_id=repo_id,
                        file_path=path,
                        payload={"operation": "reconcile_missing_source"},
                    )
                )
                scheduled_upload_paths.add(path)
        for path, row in sorted(local_files.items()):
            if row.ragflow_document_id and row.ragflow_document_id not in target_ids:
                categories["missing_target"].append(
                    {"path": path, "document_id": row.ragflow_document_id}
                )
                jobs.append(
                    JobSpec(
                        JobType.UPLOAD_FILE,
                        repo_id=repo_id,
                        file_path=path,
                        payload={"operation": "reconcile_missing_target", "force": True},
                    )
                )
                scheduled_upload_paths.add(path)
        for version in versions:
            if version.state in {"uploaded", "parsing", "retryable_failed"}:
                categories["parse_stuck"].append(
                    {
                        "path": version.normalized_path,
                        "document_id": version.document_id,
                        "state": version.state,
                    }
                )
            elif version.state == "dead":
                tracked_file = local_files.get(version.normalized_path)
                if tracked_file is None:
                    continue
                categories["parse_failed"].append(
                    {
                        "path": version.normalized_path,
                        "document_id": version.document_id,
                        "retry_count": version.retry_count,
                        "error": version.error_message,
                    }
                )
                if version.normalized_path not in scheduled_upload_paths:
                    jobs.append(
                        JobSpec(
                            JobType.UPLOAD_FILE,
                            repo_id=repo_id,
                            file_path=version.normalized_path,
                            payload={
                                "operation": "reconcile_parse_failed",
                                "force": True,
                            },
                        )
                    )
                    scheduled_upload_paths.add(version.normalized_path)
        if categories["parse_stuck"]:
            jobs.append(
                JobSpec(
                    JobType.CHECK_PARSE_STATUS,
                    repo_id=repo_id,
                    payload={"dataset_id": dataset_id, "operation": "reconcile_parse"},
                )
            )
        for document_id in sorted(target_ids & known_target_ids):
            matching = [version for version in versions if version.document_id == document_id]
            if matching and all(version.state in {"superseded", "dead"} for version in matching):
                categories["orphan_managed_target"].append({"document_id": document_id})

        warnings: list[str] = []
        if categories["orphan_managed_target"]:
            warnings.append(
                "managed target orphans are reported but removed only through cleanup_outbox"
            )
        return ReconcilePlan(
            repo_id=repo_id,
            dataset_id=dataset_id,
            scope=scope,
            commit_id=commit_id,
            snapshot_id=snapshot_id,
            jobs=jobs,
            warnings=warnings,
            categories=categories,
        )

    def _target_documents(self, dataset_id: str) -> Iterable[dict[str, Any]]:
        if self.ragflow_client is None:
            return []
        return self.ragflow_client.iter_documents(dataset_id)


def _document_id(document: Mapping[str, Any]) -> str | None:
    value = document.get("id") or document.get("document_id")
    text = str(value or "").strip()
    return text or None
