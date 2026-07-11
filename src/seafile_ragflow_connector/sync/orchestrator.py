from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from structlog.contextvars import bind_contextvars, unbind_contextvars

from seafile_ragflow_connector.app.metrics import libraries_seen_total
from seafile_ragflow_connector.clients import RAGFlowClient, SeafileAdminClient, SeafileSyncClient
from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, new_sync_id
from seafile_ragflow_connector.domain.file_classification import FilePolicy, classify_file
from seafile_ragflow_connector.domain.ingestion_artifacts import (
    build_ragflow_document_metadata,
    prepare_ingestion_artifact,
)
from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.template import DatasetSettingsSnapshot
from seafile_ragflow_connector.sync.dataset_provisioning import (
    DatasetProvisioner,
    DatasetProvisioningResult,
    LibrarySource,
)
from seafile_ragflow_connector.sync.dataset_settings import DatasetSettingsService
from seafile_ragflow_connector.sync.discovery import (
    DiscoveredLibrary,
    normalize_library,
    should_skip_library,
)
from seafile_ragflow_connector.utils.hashing import sha256_bytes
from seafile_ragflow_connector.utils.paths import normalize_seafile_path


@dataclass(frozen=True)
class SyncSummary:
    libraries_seen: int = 0
    libraries_synced: int = 0
    files_seen: int = 0
    files_uploaded: int = 0
    files_deleted: int = 0
    files_skipped: int = 0


@dataclass(frozen=True)
class FileSyncResult:
    uploaded: bool
    skipped: bool
    document_id: str | None
    change_type: str | None = None


class SyncOrchestrator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        admin_client: SeafileAdminClient,
        sync_client: SeafileSyncClient,
        ragflow_client: RAGFlowClient,
        file_policy: FilePolicy,
        template_dataset_name: str,
        template_auto_create: bool = True,
        template_required: bool = True,
        skip_encrypted_libraries: bool = True,
        skip_virtual_repos: bool = True,
        delete_ragflow_docs_on_seafile_delete: bool = True,
        delete_dataset_when_library_deleted: bool = True,
        refresh_dataset_settings: bool = True,
        dashboard_store: DashboardEventStore | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.admin_client = admin_client
        self.sync_client = sync_client
        self.ragflow_client = ragflow_client
        self.file_policy = file_policy
        self.skip_encrypted_libraries = skip_encrypted_libraries
        self.skip_virtual_repos = skip_virtual_repos
        self.delete_ragflow_docs_on_seafile_delete = delete_ragflow_docs_on_seafile_delete
        self.delete_dataset_when_library_deleted = delete_dataset_when_library_deleted
        self.refresh_dataset_settings = refresh_dataset_settings
        self.dashboard_store = dashboard_store
        self.dataset_provisioner = DatasetProvisioner(
            ragflow_client,
            template_dataset_name=template_dataset_name,
            template_auto_create=template_auto_create,
            template_required=template_required,
        )
        self.dataset_settings_service = DatasetSettingsService(ragflow_client)
        self.log = structlog.get_logger(__name__)

    def discover_libraries(self) -> list[DiscoveredLibrary]:
        discovered: list[DiscoveredLibrary] = []
        current_repo_ids: set[str] = set()
        for raw in self.admin_client.iter_libraries():
            libraries_seen_total.inc()
            library = normalize_library(raw)
            current_repo_ids.add(library.repo_id)
            skipped, reason = should_skip_library(
                library,
                skip_encrypted=self.skip_encrypted_libraries,
                skip_virtual=self.skip_virtual_repos,
            )
            with self.session_factory() as session:
                db_library = self._upsert_library(session, library)
                if skipped:
                    db_library.status = f"skipped:{reason}"
                session.commit()
            if skipped:
                self.log.info("library.skipped", repo_id=library.repo_id, reason=reason)
                continue
            discovered.append(library)
        self._cleanup_missing_libraries(current_repo_ids)
        return discovered

    def discover_job_specs(self) -> list[JobSpec]:
        return [
            JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id=library.repo_id)
            for library in self.discover_libraries()
        ]

    def sync_once(self) -> SyncSummary:
        libraries = self.discover_libraries()
        summary = SyncSummary(libraries_seen=len(libraries))
        for library in libraries:
            try:
                library_summary = self.sync_library_full(library.repo_id)
            except Exception as exc:
                self._mark_library_error(library.repo_id, exc)
                self.log.warning(
                    "library.sync_failed",
                    repo_id=library.repo_id,
                    name=library.name,
                    error=str(exc),
                )
                continue
            self.log.info(
                "library.synced",
                repo_id=library.repo_id,
                name=library.name,
                files_seen=library_summary.files_seen,
                files_uploaded=library_summary.files_uploaded,
                files_deleted=library_summary.files_deleted,
                files_skipped=library_summary.files_skipped,
            )
            summary = SyncSummary(
                libraries_seen=summary.libraries_seen,
                libraries_synced=summary.libraries_synced + library_summary.libraries_synced,
                files_seen=summary.files_seen + library_summary.files_seen,
                files_uploaded=summary.files_uploaded + library_summary.files_uploaded,
                files_deleted=summary.files_deleted + library_summary.files_deleted,
                files_skipped=summary.files_skipped + library_summary.files_skipped,
            )
        return summary

    def ensure_dataset_for_repo(self, repo_id: str) -> str:
        with self.session_factory() as session:
            db_library = self._get_library(session, repo_id)
            previous_dataset_id = db_library.ragflow_dataset_id
            previous_dataset_name = db_library.ragflow_dataset_name
            source = LibrarySource(
                repo_id=db_library.repo_id,
                name=db_library.name,
                owner_email=db_library.owner_email,
            )
        result = self._reuse_bound_dataset(
            source,
            dataset_id=previous_dataset_id,
            dataset_name=previous_dataset_name,
        )
        if result is None:
            result = self.dataset_provisioner.ensure_dataset(source)
        with self.session_factory() as session:
            db_library = self._get_library(session, repo_id)
            dataset_replaced = (
                bool(previous_dataset_id)
                and previous_dataset_id != result.dataset_id
            )
            if dataset_replaced:
                self._clear_file_target_bindings(
                    session,
                    repo_id=repo_id,
                    previous_dataset_id=str(previous_dataset_id),
                    new_dataset_id=result.dataset_id,
                )
            db_library.ragflow_dataset_id = result.dataset_id
            db_library.ragflow_dataset_name = result.dataset_name
            db_library.template_hash = result.template_hash or db_library.template_hash
            self._record_dataset_snapshot(
                session,
                repo_id=repo_id,
                dataset_id=result.dataset_id,
                settings_hash=result.settings_hash,
                settings_payload=result.settings_payload,
            )
            session.commit()
        if previous_dataset_id and previous_dataset_id != result.dataset_id:
            self.log.info(
                "ragflow.dataset_recreated",
                repo_id=repo_id,
                previous_dataset_id=previous_dataset_id,
                dataset_id=result.dataset_id,
            )
        return result.dataset_id

    def _reuse_bound_dataset(
        self,
        source: LibrarySource,
        *,
        dataset_id: str | None,
        dataset_name: str | None,
    ) -> DatasetProvisioningResult | None:
        if not dataset_id:
            return None
        try:
            dataset = self.ragflow_client.get_dataset(dataset_id)
        except ApiError as exc:
            self.log.info(
                "ragflow.dataset_bound_reuse_skipped",
                repo_id=source.repo_id,
                dataset_id=dataset_id,
                status_code=exc.status_code,
            )
            return None
        if (
            self.dataset_provisioner.template_auto_create
            or self.dataset_provisioner.template_required
        ):
            self.dataset_provisioner.ensure_template_dataset()
        resolved = dict(dataset)
        resolved["id"] = str(resolved.get("id") or dataset_id)
        resolved["name"] = str(resolved.get("name") or dataset_name or resolved["id"])
        self.log.info(
            "ragflow.dataset_bound_reused",
            repo_id=source.repo_id,
            dataset_id=resolved["id"],
            dataset_name=resolved["name"],
        )
        return self.dataset_provisioner.result_from_existing_dataset(source, resolved)

    def sync_library_full(self, repo_id: str, *, scope: str = "/") -> SyncSummary:
        sync_id = new_sync_id(repo_id)
        try:
            dataset_id = self.ensure_dataset_for_repo(repo_id)
        except Exception as exc:
            self._mark_library_error(repo_id, exc)
            raise
        bind_contextvars(sync_id=sync_id)
        self._create_dashboard_sync_run(sync_id, repo_id, dataset_id, scope)
        self.log.info(
            "library.sync_started",
            sync_id=sync_id,
            repo_id=repo_id,
            dataset_id=dataset_id,
            scope=scope,
        )
        seen_paths: set[str] = set()
        files_seen = 0
        files_uploaded = 0
        files_skipped = 0
        files_created = 0
        files_updated = 0
        dashboard_skipped = 0
        files_deleted = 0
        errors_count = 0
        warnings_count = 0

        try:
            for path, item in self.iter_files(repo_id, scope):
                normalized_path = normalize_seafile_path(path)
                seen_paths.add(normalized_path)
                files_seen += 1
                try:
                    result = self.sync_file(
                        repo_id,
                        dataset_id,
                        normalized_path,
                        item=item,
                        sync_id=sync_id,
                    )
                except Exception as exc:
                    errors_count += 1
                    self._record_dashboard_change(
                        sync_id=sync_id,
                        action="sync_file",
                        change_type="failed",
                        status="failed",
                        object_name=_basename(normalized_path),
                        source_path=normalized_path,
                        target_path=dataset_id,
                        error_message=str(exc),
                        details={"repo_id": repo_id, "dataset_id": dataset_id},
                    )
                    raise
                if result.uploaded:
                    files_uploaded += 1
                    if result.change_type == "updated":
                        files_updated += 1
                    else:
                        files_created += 1
                if result.skipped:
                    files_skipped += 1
                if result.skipped or result.change_type == "unchanged":
                    dashboard_skipped += 1

            files_deleted = self.delete_missing_files(
                repo_id,
                dataset_id,
                seen_paths,
                scope=scope,
                sync_id=sync_id,
            )
            with self.session_factory() as session:
                db_library = self._get_library(session, repo_id)
                db_library.last_synced_commit_id = db_library.head_commit_id
                db_library.status = "active"
                db_library.last_error = None
                session.commit()
            summary = SyncSummary(
                libraries_synced=1,
                files_seen=files_seen,
                files_uploaded=files_uploaded,
                files_deleted=files_deleted,
                files_skipped=files_skipped,
            )
            self._finish_dashboard_sync_run(
                sync_id=sync_id,
                status="succeeded",
                objects_checked=files_seen,
                objects_created=files_created,
                objects_updated=files_updated,
                objects_deleted=files_deleted,
                objects_skipped=dashboard_skipped,
                errors_count=errors_count,
                warnings_count=warnings_count,
                summary=(
                    f"{files_seen} Dateien geprüft, {files_uploaded} hochgeladen, "
                    f"{files_deleted} gelöscht, {files_skipped} übersprungen"
                ),
                details={"repo_id": repo_id, "dataset_id": dataset_id, "scope": scope},
            )
            self.log.info(
                "library.sync_completed",
                sync_id=sync_id,
                repo_id=repo_id,
                dataset_id=dataset_id,
                scope=scope,
                files_seen=files_seen,
                files_uploaded=files_uploaded,
                files_deleted=files_deleted,
                files_skipped=files_skipped,
            )
            return summary
        except Exception as exc:
            self._mark_library_error(repo_id, exc)
            self._finish_dashboard_sync_run(
                sync_id=sync_id,
                status="failed",
                objects_checked=files_seen,
                objects_created=files_created,
                objects_updated=files_updated,
                objects_deleted=files_deleted,
                objects_skipped=dashboard_skipped,
                errors_count=max(errors_count, 1),
                warnings_count=warnings_count,
                summary=f"Synchronisation fehlgeschlagen: {exc}",
                details={
                    "repo_id": repo_id,
                    "dataset_id": dataset_id,
                    "scope": scope,
                    "error": str(exc),
                },
            )
            raise
        finally:
            unbind_contextvars("sync_id")

    def sync_file(
        self,
        repo_id: str,
        dataset_id: str,
        path: str,
        *,
        item: dict[str, Any] | None = None,
        force: bool = False,
        sync_id: str | None = None,
    ) -> FileSyncResult:
        data = self.sync_client.download_file(repo_id, path)
        classification = classify_file(path, data, self.file_policy)
        source_hash = sha256_bytes(data)
        artifact = None
        if classification.should_ingest:
            artifact = prepare_ingestion_artifact(classification, data)

        with self.session_factory() as session:
            db_file = self._upsert_file_row(
                session,
                repo_id=repo_id,
                path=path,
                item=item,
                classification=classification,
                source_hash=source_hash,
            )
            if not classification.should_ingest or artifact is None:
                db_file.sync_status = "skipped"
                db_file.error_message = classification.reason
                session.commit()
                self.log.info(
                    "file.skipped",
                    sync_id=sync_id,
                    repo_id=repo_id,
                    dataset_id=dataset_id,
                    path=path,
                    reason=classification.reason,
                )
                self._record_dashboard_change(
                    sync_id=sync_id,
                    action="skip_file",
                    change_type="skipped",
                    status="skipped",
                    object_name=_basename(path),
                    source_path=path,
                    target_path=dataset_id,
                    error_message=classification.reason,
                    details={
                        "repo_id": repo_id,
                        "dataset_id": dataset_id,
                        "detected_mime": classification.detected_mime,
                        "ingestion_strategy": classification.ingestion_strategy,
                    },
                )
                return FileSyncResult(
                    uploaded=False,
                    skipped=True,
                    document_id=db_file.ragflow_document_id,
                    change_type="skipped",
                )

            unchanged = (
                not force
                and db_file.source_content_sha256 == artifact.source_content_sha256
                and db_file.ingested_content_sha256 == artifact.ingested_content_sha256
                and bool(db_file.ragflow_document_id)
            )
            old_document_id = db_file.ragflow_document_id
            db_file.sync_status = "pending"
            db_file.error_message = None
            session.commit()

            if unchanged and old_document_id:
                unchanged = self._ragflow_document_exists(
                    dataset_id,
                    old_document_id,
                    artifact.document_name,
                )
                if not unchanged:
                    self.log.info(
                        "ragflow.document_missing_reupload",
                        sync_id=sync_id,
                        repo_id=repo_id,
                        dataset_id=dataset_id,
                        path=path,
                        document_id=old_document_id,
                    )

            if unchanged:
                with self.session_factory() as session:
                    db_file = self._get_file(session, repo_id, normalize_seafile_path(path))
                    db_file.sync_status = "synced"
                    db_file.error_message = None
                    session.commit()
                self.log.debug(
                    "file.unchanged",
                    sync_id=sync_id,
                    repo_id=repo_id,
                    dataset_id=dataset_id,
                    path=path,
                    document_id=old_document_id,
                )
                self._record_dashboard_change(
                    sync_id=sync_id,
                    action="compare_file",
                    change_type="unchanged",
                    status="synced",
                    object_name=_basename(path),
                    source_path=path,
                    target_path=(
                        f"{dataset_id}/{old_document_id}" if old_document_id else dataset_id
                    ),
                    details={
                        "repo_id": repo_id,
                        "dataset_id": dataset_id,
                        "document_id": old_document_id,
                    },
                )
                return FileSyncResult(
                    uploaded=False,
                    skipped=False,
                    document_id=old_document_id,
                    change_type="unchanged",
                )

        stale_document_ids = self._find_stale_document_ids(
            dataset_id,
            document_name=artifact.document_name,
            old_document_id=old_document_id,
        )
        if stale_document_ids:
            self.ragflow_client.delete_documents(dataset_id, stale_document_ids)
            self.log.info(
                "ragflow.stale_documents_deleted",
                sync_id=sync_id,
                repo_id=repo_id,
                dataset_id=dataset_id,
                path=path,
                document_name=artifact.document_name,
                document_count=len(stale_document_ids),
            )
            self._record_dashboard_change(
                sync_id=sync_id,
                action="delete_stale_ragflow_documents",
                change_type="deleted",
                status="succeeded",
                object_name=artifact.document_name,
                source_path=path,
                target_path=dataset_id,
                details={
                    "repo_id": repo_id,
                    "dataset_id": dataset_id,
                    "document_ids": stale_document_ids,
                },
            )

        settings_hash = None
        if self.refresh_dataset_settings:
            settings = self.dataset_settings_service.refresh(dataset_id)
            settings_hash = settings.settings_hash
            with self.session_factory() as session:
                self._record_dataset_snapshot(
                    session,
                    repo_id=repo_id,
                    dataset_id=dataset_id,
                    settings_hash=settings.settings_hash,
                    settings_payload=settings.settings_payload,
                )
                session.commit()

        document = self.ragflow_client.upload_document(
            dataset_id,
            document_name=artifact.document_name,
            content=artifact.content,
            mime_type=artifact.mime_type,
        )
        document_id = str(document.get("id") or document.get("document_id") or "")
        if not document_id:
            msg = f"RAGFlow upload response did not contain a document id for {path}"
            raise RuntimeError(msg)
        metadata = build_ragflow_document_metadata(
            artifact,
            repo_id=repo_id,
            path=path,
            item=item,
        )
        try:
            self.ragflow_client.update_document_metadata(dataset_id, document_id, metadata)
        except ApiError as exc:
            if exc.status_code not in {404, 405}:
                raise
            self.log.warning(
                "ragflow.document_metadata_update_unsupported",
                sync_id=sync_id,
                repo_id=repo_id,
                dataset_id=dataset_id,
                path=path,
                document_id=document_id,
                status_code=exc.status_code,
            )
        self.ragflow_client.parse_documents(dataset_id, [document_id])

        with self.session_factory() as session:
            db_file = self._get_file(session, repo_id, normalize_seafile_path(path))
            db_file.source_content_sha256 = artifact.source_content_sha256
            db_file.ingested_content_sha256 = artifact.ingested_content_sha256
            db_file.ragflow_document_id = document_id
            db_file.ragflow_document_name = artifact.document_name
            db_file.ingested_document_name = artifact.document_name
            db_file.ingested_mime = artifact.mime_type
            db_file.last_uploaded_dataset_settings_hash = settings_hash
            db_file.sync_status = "uploaded"
            db_file.parse_status = "UNSTART"
            db_file.error_message = None
            session.commit()

        self.log.info(
            "file.uploaded",
            sync_id=sync_id,
            repo_id=repo_id,
            dataset_id=dataset_id,
            path=path,
            document_id=document_id,
            document_name=artifact.document_name,
            ingestion_strategy=classification.ingestion_strategy,
            source_size_bytes=len(data),
        )
        change_type = "updated" if old_document_id or stale_document_ids else "created"
        self._record_dashboard_change(
            sync_id=sync_id,
            action="upload_file",
            change_type=change_type,
            status="synced",
            object_name=artifact.document_name,
            source_path=path,
            target_path=f"{dataset_id}/{document_id}",
            previous_name=None,
            new_name=artifact.document_name,
            details={
                "repo_id": repo_id,
                "dataset_id": dataset_id,
                "document_id": document_id,
                "ingestion_strategy": classification.ingestion_strategy,
                "source_size_bytes": len(data),
                "mime_type": artifact.mime_type,
                "stale_document_ids": stale_document_ids,
            },
        )
        return FileSyncResult(
            uploaded=True,
            skipped=False,
            document_id=document_id,
            change_type=change_type,
        )

    def delete_file(
        self,
        repo_id: str,
        dataset_id: str,
        path: str,
        *,
        sync_id: str | None = None,
    ) -> bool:
        normalized_path = normalize_seafile_path(path)
        with self.session_factory() as session:
            db_file = session.scalar(
                select(File).where(
                    File.repo_id == repo_id,
                    File.normalized_path == normalized_path,
                )
            )
            if db_file is None:
                self.log.info(
                    "file.delete_skipped_missing_state",
                    sync_id=sync_id,
                    repo_id=repo_id,
                    dataset_id=dataset_id,
                    path=normalized_path,
                )
                self._record_dashboard_change(
                    sync_id=sync_id,
                    action="delete_file",
                    change_type="deleted",
                    status="skipped",
                    object_name=_basename(normalized_path),
                    source_path=normalized_path,
                    target_path=dataset_id,
                    details={
                        "repo_id": repo_id,
                        "dataset_id": dataset_id,
                        "reason": "file_not_known_in_state",
                    },
                )
                return False
            document_id = db_file.ragflow_document_id
            document_name = db_file.ragflow_document_name or db_file.ingested_document_name
        if document_id and self.delete_ragflow_docs_on_seafile_delete:
            self.ragflow_client.delete_documents(dataset_id, [document_id])
            self.log.info(
                "file.ragflow_document_deleted",
                sync_id=sync_id,
                repo_id=repo_id,
                dataset_id=dataset_id,
                path=normalized_path,
                document_id=document_id,
            )
        with self.session_factory() as session:
            db_file = self._get_file(session, repo_id, normalized_path)
            session.delete(db_file)
            session.commit()
        self._record_dashboard_change(
            sync_id=sync_id,
            action="delete_file",
            change_type="deleted",
            status="succeeded",
            object_name=document_name or _basename(normalized_path),
            source_path=normalized_path,
            target_path=f"{dataset_id}/{document_id}" if document_id else dataset_id,
            details={"repo_id": repo_id, "dataset_id": dataset_id, "document_id": document_id},
        )
        return bool(document_id)

    def delete_missing_files(
        self,
        repo_id: str,
        dataset_id: str,
        seen_paths: set[str],
        *,
        scope: str = "/",
        sync_id: str | None = None,
    ) -> int:
        normalized_scope = normalize_seafile_path(scope)
        deleted = 0
        with self.session_factory() as session:
            rows = session.scalars(select(File).where(File.repo_id == repo_id)).all()
            missing = [
                row
                for row in rows
                if row.normalized_path not in seen_paths
                and (
                    normalized_scope == "/"
                    or row.normalized_path == normalized_scope
                    or row.normalized_path.startswith(normalized_scope.rstrip("/") + "/")
                )
            ]

        for row in missing:
            if row.ragflow_document_id and self.delete_ragflow_docs_on_seafile_delete:
                try:
                    self.ragflow_client.delete_documents(dataset_id, [row.ragflow_document_id])
                except ApiError:
                    raise
                self.log.info(
                    "file.missing_ragflow_document_deleted",
                    sync_id=sync_id,
                    repo_id=repo_id,
                    dataset_id=dataset_id,
                    path=row.normalized_path,
                    document_id=row.ragflow_document_id,
                )
            with self.session_factory() as session:
                db_file = session.get(File, row.id)
                if db_file:
                    session.delete(db_file)
                    session.commit()
            self._record_dashboard_change(
                sync_id=sync_id,
                action="delete_missing_file",
                change_type="deleted",
                status="succeeded",
                object_name=(
                    row.ragflow_document_name
                    or row.ingested_document_name
                    or _basename(row.normalized_path)
                ),
                source_path=row.normalized_path,
                target_path=(
                    f"{dataset_id}/{row.ragflow_document_id}"
                    if row.ragflow_document_id
                    else dataset_id
                ),
                details={
                    "repo_id": repo_id,
                    "dataset_id": dataset_id,
                    "document_id": row.ragflow_document_id,
                },
            )
            deleted += 1
        return deleted

    def check_parse_status(self, repo_id: str, dataset_id: str) -> int:
        documents = self.ragflow_client.list_documents(dataset_id)
        by_id = {str(document.get("id")): document for document in documents if document.get("id")}
        updated = 0
        with self.session_factory() as session:
            rows = session.scalars(select(File).where(File.repo_id == repo_id)).all()
            for row in rows:
                if not row.ragflow_document_id:
                    continue
                document = by_id.get(row.ragflow_document_id)
                if not document:
                    continue
                row.parse_status = str(document.get("run") or "")
                if document.get("run") == "FAIL":
                    row.error_message = str(document.get("progress_msg") or "")[:4000]
                    self._record_dashboard_change(
                        sync_id=None,
                        action="check_parse_status",
                        change_type="failed",
                        status="failed",
                        object_name=row.ragflow_document_name or row.ingested_document_name,
                        source_path=row.normalized_path,
                        target_path=f"{dataset_id}/{row.ragflow_document_id}",
                        error_message=row.error_message,
                        details={"repo_id": repo_id, "dataset_id": dataset_id},
                    )
                updated += 1
            session.commit()
        return updated

    def iter_files(self, repo_id: str, path: str = "/") -> Iterable[tuple[str, dict[str, Any]]]:
        for item in self.sync_client.list_dir(repo_id, path):
            name = str(item.get("name") or "")
            if not name:
                continue
            child_path = _join_seafile_path(path, name)
            if _is_directory(item):
                yield from self.iter_files(repo_id, child_path)
            else:
                yield child_path, item

    def _upsert_library(self, session: Session, library: DiscoveredLibrary) -> Library:
        db_library = session.get(Library, library.repo_id)
        if db_library is None:
            db_library = Library(
                repo_id=library.repo_id,
                name=library.name,
                name_slug=slugify(library.name),
            )
            session.add(db_library)
        db_library.name = library.name
        db_library.name_slug = slugify(library.name)
        db_library.owner_email = library.owner_email
        db_library.encrypted = library.encrypted
        db_library.virtual = library.virtual
        db_library.seafile_mtime = library.seafile_mtime
        db_library.head_commit_id = library.head_commit_id
        return db_library

    def _cleanup_missing_libraries(self, current_repo_ids: set[str]) -> None:
        with self.session_factory() as session:
            missing = session.scalars(
                select(Library)
                .where(Library.repo_id.not_in(current_repo_ids))
                .where(Library.status != "deleted")
            ).all()
            items = [
                {
                    "repo_id": row.repo_id,
                    "name": row.name,
                    "dataset_id": row.ragflow_dataset_id,
                }
                for row in missing
            ]

        for item in items:
            repo_id = str(item["repo_id"])
            dataset_id = str(item["dataset_id"] or "")
            try:
                self.log.info(
                    "library.deleted_detected",
                    repo_id=repo_id,
                    name=item["name"],
                    dataset_id=dataset_id or None,
                )
                if dataset_id and self.delete_dataset_when_library_deleted:
                    self.ragflow_client.delete_datasets([dataset_id])
                    self.log.info(
                        "ragflow.dataset_deleted_for_missing_library",
                        repo_id=repo_id,
                        dataset_id=dataset_id,
                    )
                    self._record_dashboard_change(
                        sync_id=None,
                        action="delete_ragflow_dataset_for_missing_library",
                        change_type="deleted",
                        status="succeeded",
                        object_name=str(item["name"]),
                        source_path=f"seafile:{repo_id}",
                        target_path=f"ragflow:{dataset_id}",
                        details={"repo_id": repo_id, "dataset_id": dataset_id},
                    )
                with self.session_factory() as session:
                    db_library = session.get(Library, repo_id)
                    if db_library:
                        db_library.status = "deleted"
                        db_library.last_error = None
                        for row in session.scalars(select(File).where(File.repo_id == repo_id)):
                            session.delete(row)
                        session.commit()
            except Exception as exc:
                with self.session_factory() as session:
                    db_library = session.get(Library, repo_id)
                    if db_library:
                        db_library.status = "delete_failed"
                        db_library.last_error = str(exc)[:4000]
                        session.commit()
                self.log.warning(
                    "library.delete_cleanup_failed",
                    repo_id=repo_id,
                    dataset_id=dataset_id or None,
                    error=str(exc),
                )

    def _upsert_file_row(
        self,
        session: Session,
        *,
        repo_id: str,
        path: str,
        item: dict[str, Any] | None,
        classification: Any,
        source_hash: str,
    ) -> File:
        normalized_path = normalize_seafile_path(path)
        db_file = session.scalar(
            select(File).where(
                File.repo_id == repo_id,
                File.normalized_path == normalized_path,
            )
        )
        if db_file is None:
            db_file = File(repo_id=repo_id, path=path, normalized_path=normalized_path)
            session.add(db_file)
        db_file.path = path
        db_file.source_extension = classification.source_extension
        db_file.detected_mime = classification.detected_mime
        db_file.detected_encoding = classification.detected_encoding
        db_file.is_text = classification.is_text
        db_file.ingestion_strategy = classification.ingestion_strategy
        db_file.source_content_sha256 = source_hash
        if item:
            db_file.seafile_obj_id = str(item.get("id") or item.get("obj_id") or "") or None
            db_file.size = _int_or_none(item.get("size"))
            db_file.seafile_mtime = _datetime_from_timestamp(item.get("mtime"))  # type: ignore[assignment]
        return db_file

    def _record_dataset_snapshot(
        self,
        session: Session,
        *,
        repo_id: str,
        dataset_id: str,
        settings_hash: str,
        settings_payload: dict[str, Any],
    ) -> None:
        session.add(
            DatasetSettingsSnapshot(
                repo_id=repo_id,
                ragflow_dataset_id=dataset_id,
                settings_hash=settings_hash,
                settings_payload=settings_payload,
            )
        )

    def _clear_file_target_bindings(
        self,
        session: Session,
        *,
        repo_id: str,
        previous_dataset_id: str,
        new_dataset_id: str,
    ) -> None:
        for row in session.scalars(select(File).where(File.repo_id == repo_id)):
            row.ragflow_document_id = None
            row.ragflow_document_name = None
            row.ingested_document_name = None
            row.ingested_mime = None
            row.parse_status = None
            row.sync_status = "pending"
            row.error_message = None
        self._record_dashboard_change(
            sync_id=None,
            action="reset_file_bindings_after_dataset_recreate",
            change_type="updated",
            status="synced",
            object_name=repo_id,
            source_path=f"ragflow:{previous_dataset_id}",
            target_path=f"ragflow:{new_dataset_id}",
            details={
                "repo_id": repo_id,
                "previous_dataset_id": previous_dataset_id,
                "dataset_id": new_dataset_id,
            },
        )

    def _mark_library_error(self, repo_id: str, exc: Exception) -> None:
        with self.session_factory() as session:
            db_library = session.get(Library, repo_id)
            if db_library is None:
                return
            db_library.status = "error"
            db_library.last_error = str(exc)[:4000]
            session.commit()

    def _create_dashboard_sync_run(
        self,
        sync_id: str,
        repo_id: str,
        dataset_id: str,
        scope: str,
    ) -> None:
        if self.dashboard_store is None:
            return
        try:
            self.dashboard_store.create_sync_run(
                sync_id=sync_id,
                source=f"seafile:{repo_id}:{scope}",
                target=f"ragflow:{dataset_id}",
                summary=f"Synchronisation für Repository {repo_id}",
                details={"repo_id": repo_id, "dataset_id": dataset_id, "scope": scope},
            )
        except Exception as exc:
            self.log.warning("dashboard.sync_run_create_failed", error=str(exc), sync_id=sync_id)

    def _finish_dashboard_sync_run(
        self,
        *,
        sync_id: str,
        status: str,
        objects_checked: int,
        objects_created: int,
        objects_updated: int,
        objects_deleted: int,
        objects_skipped: int,
        errors_count: int,
        warnings_count: int,
        summary: str,
        details: Mapping[str, Any],
    ) -> None:
        if self.dashboard_store is None:
            return
        try:
            self.dashboard_store.finish_sync_run(
                sync_id=sync_id,
                status=status,
                objects_checked=objects_checked,
                objects_created=objects_created,
                objects_updated=objects_updated,
                objects_deleted=objects_deleted,
                objects_skipped=objects_skipped,
                errors_count=errors_count,
                warnings_count=warnings_count,
                summary=summary,
                details=details,
            )
        except Exception as exc:
            self.log.warning("dashboard.sync_run_finish_failed", error=str(exc), sync_id=sync_id)

    def _record_dashboard_change(self, **kwargs: Any) -> None:
        if self.dashboard_store is None:
            return
        try:
            self.dashboard_store.record_change(**kwargs)
        except Exception as exc:
            self.log.warning(
                "dashboard.change_record_failed",
                error=str(exc),
                sync_id=kwargs.get("sync_id"),
            )

    def _get_library(self, session: Session, repo_id: str) -> Library:
        db_library = session.get(Library, repo_id)
        if db_library is None:
            msg = f"unknown library in state db: {repo_id}"
            raise KeyError(msg)
        return db_library

    def _get_file(self, session: Session, repo_id: str, path: str) -> File:
        normalized_path = normalize_seafile_path(path)
        db_file = session.scalar(
            select(File).where(
                File.repo_id == repo_id,
                File.normalized_path == normalized_path,
            )
        )
        if db_file is None:
            msg = f"unknown file in state db: {repo_id}:{normalized_path}"
            raise KeyError(msg)
        return db_file

    def _find_stale_document_ids(
        self,
        dataset_id: str,
        *,
        document_name: str,
        old_document_id: str | None,
    ) -> list[str]:
        stale_ids: list[str] = []
        if old_document_id:
            stale_ids.append(old_document_id)

        documents = self.ragflow_client.list_documents(
            dataset_id,
            keywords=_document_search_keyword(document_name),
            page_size=1024,
        )
        for document in documents:
            document_id = _document_id(document)
            if not document_id or document_id in stale_ids:
                continue
            existing_name = _document_name(document)
            if _matches_document_name_or_ragflow_duplicate(existing_name, document_name):
                stale_ids.append(document_id)
        return stale_ids

    def _ragflow_document_exists(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
    ) -> bool:
        documents = self.ragflow_client.list_documents(
            dataset_id,
            keywords=_document_search_keyword(document_name),
            page_size=1024,
        )
        return any(_document_id(document) == document_id for document in documents)


def _join_seafile_path(parent: str, name: str) -> str:
    if parent == "/":
        return f"/{name}"
    return f"{parent.rstrip('/')}/{name}"


def _basename(path: str) -> str:
    stripped = path.rstrip("/")
    if not stripped or stripped == "/":
        return "/"
    return stripped.rsplit("/", 1)[-1]


def _is_directory(item: dict[str, Any]) -> bool:
    value = str(item.get("type") or "").lower()
    return value in {"dir", "directory"} or bool(item.get("is_dir"))


def _document_id(document: dict[str, Any]) -> str | None:
    value = document.get("id") or document.get("document_id")
    return str(value) if value else None


def _document_name(document: dict[str, Any]) -> str:
    value = document.get("name") or document.get("document_name") or document.get("filename")
    return str(value or "")


def _matches_document_name_or_ragflow_duplicate(existing_name: str, target_name: str) -> bool:
    if existing_name == target_name:
        return True

    existing_stem, existing_suffix = _split_document_name(existing_name)
    target_stem, target_suffix = _split_document_name(target_name)
    if existing_suffix != target_suffix:
        return False
    return re.fullmatch(rf"{re.escape(target_stem)} ?\([1-9][0-9]*\)", existing_stem) is not None


def _document_search_keyword(document_name: str) -> str:
    stem, _suffix = _split_document_name(document_name)
    return stem or document_name


def _split_document_name(name: str) -> tuple[str, str]:
    if "." not in name.lstrip("."):
        return name, ""
    stem, dot, suffix = name.rpartition(".")
    return stem, dot + suffix


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_from_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OSError):
        return None
