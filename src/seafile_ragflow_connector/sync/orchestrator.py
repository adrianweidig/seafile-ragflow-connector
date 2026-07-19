from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import delete, func, select
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
from seafile_ragflow_connector.jobs.context import (
    JobDeferredError,
    current_job_id,
    current_job_run_id,
    job_cancellation_requested,
)
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import (
    CleanupOutbox,
    FileDocumentVersion,
    SourceSnapshot,
    SourceSnapshotEntry,
    SyncCursor,
    SyncRun,
)
from seafile_ragflow_connector.persistence.models.template import DatasetSettingsSnapshot
from seafile_ragflow_connector.persistence.sync_state import (
    RepoLeaseHandle,
    RepoMutationLeaseStore,
    SyncStateStore,
    activate_repo_lease,
    current_repo_lease,
)
from seafile_ragflow_connector.sync.dataset_provisioning import (
    DatasetProvisioner,
    DatasetProvisioningResult,
    LibrarySource,
)
from seafile_ragflow_connector.sync.dataset_settings import DatasetSettingsService
from seafile_ragflow_connector.sync.delta_sync import (
    SnapshotEntry,
    capture_commit_snapshot,
    diff_snapshots,
    snapshot_entries_from_records,
)
from seafile_ragflow_connector.sync.discovery import (
    DiscoveredLibrary,
    normalize_library,
    should_skip_library,
)
from seafile_ragflow_connector.sync.reconcile import ReconcilePlan, Reconciler
from seafile_ragflow_connector.utils.paths import normalize_seafile_path

MISSING_OBSERVATION_MIN_INTERVAL = timedelta(hours=1)


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


class ParsePendingError(JobDeferredError):
    """Healthy RAGFlow parsing is still in progress and needs another poll."""


class ParseDeadError(ValueError):
    """At least one managed RAGFlow document exhausted real parse retries."""


class SyncCancelledError(RuntimeError):
    pass


class ReconcilePlanStaleError(RuntimeError):
    pass


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
        admin_control_store: AdminControlStore | None = None,
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
        self.admin_control_store = admin_control_store or AdminControlStore(session_factory)
        self.dataset_provisioner = DatasetProvisioner(
            ragflow_client,
            template_dataset_name=template_dataset_name,
            template_auto_create=template_auto_create,
            template_required=template_required,
        )
        self.dataset_settings_service = DatasetSettingsService(ragflow_client)
        self.job_store = JobStore(session_factory)
        self.repo_lease_store = RepoMutationLeaseStore(session_factory)
        self.sync_state_store = SyncStateStore(session_factory)
        self.reconciler = Reconciler(session_factory, ragflow_client)
        self.log = structlog.get_logger(__name__)

    def discover_libraries(
        self,
        *,
        full_visibility: bool = False,
        trigger: str = "manual",
    ) -> list[DiscoveredLibrary]:
        visible: list[tuple[DiscoveredLibrary, str | None, bool]] = []
        current_repo_ids: set[str] = set()
        libraries = iter(self.admin_client.iter_libraries())
        while True:
            self._raise_if_automatic_cycle_interrupted(
                trigger,
                "automatic library discovery interrupted",
            )
            try:
                raw = next(libraries)
            except StopIteration:
                break
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
                dataset_id = db_library.ragflow_dataset_id
                session.commit()
            self.job_store.refresh_workflow_parents_for_repo_cleanup(library.repo_id)
            visible.append((library, dataset_id, skipped))
            if skipped:
                self.log.info("library.skipped", repo_id=library.repo_id, reason=reason)
                continue
        self._raise_if_automatic_cycle_interrupted(
            trigger,
            "automatic library discovery interrupted before missing-library cleanup",
        )
        self._cleanup_missing_libraries(current_repo_ids, trigger=trigger)
        controls = self.admin_control_store.libraries(
            [library.repo_id for library, _dataset_id, _skipped in visible]
        )
        discovered: list[DiscoveredLibrary] = []
        for library, dataset_id, skipped in visible:
            self._raise_if_automatic_cycle_interrupted(
                trigger,
                "automatic library discovery interrupted before job scheduling",
            )
            if skipped:
                if full_visibility:
                    discovered.append(library)
                continue
            control = controls[library.repo_id]
            if control.runnable:
                self._ensure_parse_status_job(
                    library.repo_id,
                    dataset_id,
                    trigger=trigger,
                )
                discovered.append(library)
                continue
            self.log.info(
                "library.controlled",
                repo_id=library.repo_id,
                state=control.state,
            )
            if full_visibility:
                discovered.append(library)
        return discovered

    def discover_job_specs(self) -> list[JobSpec]:
        try:
            workflow = self.admin_control_store.workflow()
        except Exception as exc:
            self.log.warning(
                "automation.enabled_check_failed",
                error_class=type(exc).__name__,
            )
            return []
        if not workflow.automation_enabled or workflow.queue_paused:
            return []
        return [
            JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id=library.repo_id)
            for library in self.discover_libraries(trigger="automatic")
        ]

    def sync_once(self) -> SyncSummary:
        libraries = self.discover_libraries()
        summary = SyncSummary(libraries_seen=len(libraries))
        for library in libraries:
            try:
                library_summary = self.sync_library_delta(library.repo_id)
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
        self.assert_library_runnable(repo_id)
        active_lease = current_repo_lease(repo_id)
        if active_lease is None:
            with self._mutation_scope(
                repo_id,
                owner_id=f"dataset:{new_sync_id(repo_id)}",
            ):
                return self.ensure_dataset_for_repo(repo_id)
        self.repo_lease_store.assert_owned(active_lease)
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
            if exc.status_code != 404:
                raise
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
        self.assert_library_runnable(repo_id)
        normalized_scope = normalize_seafile_path(scope)
        sync_id = new_sync_id(repo_id)
        with self._mutation_scope(repo_id, owner_id=f"sync:{sync_id}") as lease:
            self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
            with self.session_factory() as session:
                library = self._get_library(session, repo_id)
                target_commit_id = library.head_commit_id
            cursor = self.sync_state_store.get_cursor(repo_id, normalized_scope)
            baseline_commit_id = cursor.commit_id if cursor else None
            run_id = self.sync_state_store.create_run(
                run_id=sync_id,
                repo_id=repo_id,
                mode="full",
                scope=normalized_scope,
                parent_run_id=self._current_parent_run_id(),
                job_id=current_job_id(),
                baseline_commit_id=baseline_commit_id,
                target_commit_id=target_commit_id,
                fence_token=lease.fence_token,
                progress=self._file_sync_progress(
                    files_total=0,
                    files_processed=0,
                    phase="preparing",
                ),
            )
            snapshot_id: int | None = None
            snapshot_entries: list[SnapshotEntry] | None = None
            if target_commit_id:
                captured = self._try_capture_snapshot(
                    repo_id,
                    target_commit_id,
                    normalized_scope,
                )
                if captured is not None:
                    snapshot_id, snapshot_entries = captured
            try:
                summary = self._sync_library_full_owned(
                    repo_id,
                    scope=normalized_scope,
                    sync_id=sync_id,
                    lease=lease,
                    source_commit_id=(target_commit_id if snapshot_entries is not None else None),
                    snapshot_entries=snapshot_entries,
                )
                if target_commit_id and snapshot_id is not None:
                    advanced = self.sync_state_store.advance_cursor(
                        repo_id=repo_id,
                        scope=normalized_scope,
                        expected_commit_id=baseline_commit_id,
                        target_commit_id=target_commit_id,
                        snapshot_id=snapshot_id,
                    )
                    if not advanced:
                        raise RuntimeError("sync cursor changed while full sync was running")
                    if normalized_scope == "/":
                        with self.session_factory() as session:
                            library = self._get_library(session, repo_id)
                            library.last_synced_commit_id = target_commit_id
                            session.commit()
                self._complete_or_wait_for_async_work(
                    run_id,
                    repo_id,
                    {
                        "files_seen": summary.files_seen,
                        "files_uploaded": summary.files_uploaded,
                        "files_deleted": summary.files_deleted,
                        "files_skipped": summary.files_skipped,
                        "snapshot_pinned": snapshot_entries is not None,
                    },
                )
                return summary
            except Exception as exc:
                cancelled = isinstance(exc, SyncCancelledError)
                self.sync_state_store.update_run(
                    run_id,
                    status="cancelled" if cancelled else "failed",
                    progress=self._terminal_run_progress(
                        run_id,
                        terminal_phase="cancelled" if cancelled else "failed",
                    ),
                    error_message=None if cancelled else str(exc)[:4000],
                    finished=True,
                )
                raise

    def _sync_library_full_owned(
        self,
        repo_id: str,
        *,
        scope: str,
        sync_id: str,
        lease: RepoLeaseHandle,
        source_commit_id: str | None,
        snapshot_entries: list[SnapshotEntry] | None,
    ) -> SyncSummary:
        self.repo_lease_store.assert_owned(lease)
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
            source_files_iter: Iterable[tuple[str, dict[str, Any]]]
            if snapshot_entries is None:
                source_files_iter = self.iter_files(repo_id, scope)
            else:
                source_files_iter = (
                    (entry.path, self._snapshot_item(entry))
                    for entry in snapshot_entries
                    if not entry.is_directory
                )
            source_files = list(source_files_iter)
            files_total = len(source_files)
            self.sync_state_store.update_run(
                sync_id,
                progress=self._file_sync_progress(
                    files_total=files_total,
                    files_processed=0,
                ),
            )
            source_paths = {
                normalize_seafile_path(path) for path, _item in source_files
            }
            source_object_counts = Counter(
                object_id
                for _path, item in source_files
                if (object_id := _seafile_object_id(item))
            )
            with self.session_factory() as session:
                existing_files = list(
                    session.scalars(select(File).where(File.repo_id == repo_id)).all()
                )
                existing_object_counts = Counter(
                    row.seafile_obj_id for row in existing_files if row.seafile_obj_id
                )
                unique_existing_paths = {
                    str(row.seafile_obj_id): row.normalized_path
                    for row in existing_files
                    if row.seafile_obj_id
                    and existing_object_counts[str(row.seafile_obj_id)] == 1
                }
            rename_candidates: dict[str, str] = {}
            for path, item in source_files:
                normalized_path = normalize_seafile_path(path)
                object_id = _seafile_object_id(item)
                previous_path = unique_existing_paths.get(object_id or "")
                if (
                    object_id
                    and source_object_counts[object_id] == 1
                    and previous_path
                    and previous_path != normalized_path
                    and previous_path not in source_paths
                ):
                    rename_candidates[normalized_path] = previous_path
            for path, item in source_files:
                if not self.repo_lease_store.heartbeat(lease, lease_seconds=900):
                    self.repo_lease_store.assert_owned(lease)
                if self._cancellation_requested(sync_id):
                    raise SyncCancelledError("sync run cancellation requested")
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
                        source_commit_id=source_commit_id,
                        lease=lease,
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
                previous_path = rename_candidates.get(normalized_path)
                if previous_path and result.document_id:
                    cleanup_queued = self._queue_file_cleanup(
                        repo_id,
                        dataset_id,
                        previous_path,
                        wait_for_document_id=result.document_id,
                        fence_token=lease.fence_token,
                        delete_file_row=True,
                        run_id=self._correlation_run_id(sync_id),
                    )
                    if cleanup_queued:
                        # Keep delete_missing_files from deleting the old document before
                        # the replacement reached the current parse state.
                        seen_paths.add(previous_path)
                self.sync_state_store.update_run(
                    sync_id,
                    progress=self._file_sync_progress(
                        files_total=files_total,
                        files_processed=files_seen,
                    ),
                )

            self.sync_state_store.update_run(
                sync_id,
                progress=self._file_sync_progress(
                    files_total=files_total,
                    files_processed=files_seen,
                    phase="cleanup",
                ),
            )
            files_deleted = self.delete_missing_files(
                repo_id,
                dataset_id,
                seen_paths,
                scope=scope,
                sync_id=sync_id,
                lease=lease,
            )
            with self.session_factory() as session:
                db_library = self._get_library(session, repo_id)
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
                status="running",
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
                terminal=False,
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
            cancelled = isinstance(exc, SyncCancelledError)
            if not cancelled:
                self._mark_library_error(repo_id, exc)
            self._finish_dashboard_sync_run(
                sync_id=sync_id,
                status="cancelled" if cancelled else "failed",
                objects_checked=files_seen,
                objects_created=files_created,
                objects_updated=files_updated,
                objects_deleted=files_deleted,
                objects_skipped=dashboard_skipped,
                errors_count=errors_count if cancelled else max(errors_count, 1),
                warnings_count=warnings_count,
                summary=(
                    "Synchronisation abgebrochen"
                    if cancelled
                    else f"Synchronisation fehlgeschlagen: {exc}"
                ),
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

    def sync_library_delta(self, repo_id: str, *, scope: str = "/") -> SyncSummary:
        self.assert_library_runnable(repo_id)
        normalized_scope = normalize_seafile_path(scope)
        with self._mutation_scope(
            repo_id,
            owner_id=f"delta:{new_sync_id(repo_id)}",
        ) as lease:
            self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
            with self.session_factory() as session:
                library = self._get_library(session, repo_id)
                target_commit_id = library.head_commit_id
            cursor = self.sync_state_store.get_cursor(repo_id, normalized_scope)
            if not target_commit_id or cursor is None:
                self.log.info(
                    "library.delta_full_fallback",
                    repo_id=repo_id,
                    reason="missing_target_or_baseline",
                )
                return self.sync_library_full(repo_id, scope=normalized_scope)
            if cursor.commit_id == target_commit_id:
                run_id = self.sync_state_store.create_run(
                    repo_id=repo_id,
                    mode="delta",
                    scope=normalized_scope,
                    parent_run_id=self._current_parent_run_id(),
                    job_id=current_job_id(),
                    baseline_commit_id=cursor.commit_id,
                    target_commit_id=target_commit_id,
                    fence_token=lease.fence_token,
                    progress=self._delta_sync_progress(
                        changes_total=0,
                        changes_processed=0,
                        phase="syncing",
                    ),
                )
                summary = SyncSummary(libraries_synced=1)
                self._ensure_parse_status_job(
                    repo_id,
                    self._library_dataset_id(repo_id),
                    run_id=self._correlation_run_id(run_id),
                )
                self._complete_or_wait_for_async_work(
                    run_id,
                    repo_id,
                    {"changes": 0, "reason": "head_unchanged"},
                )
                return summary

            captured = self._try_capture_snapshot(
                repo_id,
                target_commit_id,
                normalized_scope,
            )
            if captured is None:
                self.log.info(
                    "library.delta_full_fallback",
                    repo_id=repo_id,
                    reason="commit_snapshot_unavailable",
                )
                return self.sync_library_full(repo_id, scope=normalized_scope)
            target_snapshot_id, target_entries = captured
            baseline_snapshot = self.sync_state_store.get_snapshot(cursor.snapshot_id)
            baseline_records = self.sync_state_store.snapshot_entries(cursor.snapshot_id)
            if baseline_snapshot is None or not baseline_snapshot.complete:
                self.log.info(
                    "library.delta_full_fallback",
                    repo_id=repo_id,
                    reason="baseline_snapshot_missing",
                )
                return self.sync_library_full(repo_id, scope=normalized_scope)
            baseline_entries = snapshot_entries_from_records(baseline_records)
            changes = diff_snapshots(baseline_entries, target_entries)
            run_id = self.sync_state_store.create_run(
                repo_id=repo_id,
                mode="delta",
                scope=normalized_scope,
                parent_run_id=self._current_parent_run_id(),
                job_id=current_job_id(),
                baseline_commit_id=cursor.commit_id,
                target_commit_id=target_commit_id,
                fence_token=lease.fence_token,
                progress=self._delta_sync_progress(
                    changes_total=len(changes),
                    changes_processed=0,
                ),
            )
            files_uploaded = 0
            files_deleted = 0
            files_skipped = 0
            try:
                dataset_id = self.ensure_dataset_for_repo(repo_id)
                for index, change in enumerate(changes, start=1):
                    if not self.repo_lease_store.heartbeat(lease, lease_seconds=900):
                        self.repo_lease_store.assert_owned(lease)
                    if self._cancellation_requested(run_id):
                        raise SyncCancelledError("sync run cancellation requested")
                    if change.operation == "removed":
                        if self.delete_file(
                            repo_id,
                            dataset_id,
                            change.path,
                            sync_id=run_id,
                            lease=lease,
                        ):
                            files_deleted += 1
                    elif change.entry is not None:
                        result = self.sync_file(
                            repo_id,
                            dataset_id,
                            change.path,
                            item=self._snapshot_item(change.entry),
                            sync_id=run_id,
                            source_commit_id=target_commit_id,
                            lease=lease,
                        )
                        files_uploaded += int(result.uploaded)
                        files_skipped += int(result.skipped)
                        if change.operation == "renamed" and change.old_path:
                            self._queue_file_cleanup(
                                repo_id,
                                dataset_id,
                                change.old_path,
                                fence_token=lease.fence_token,
                                wait_for_document_id=result.document_id,
                                delete_file_row=True,
                                run_id=self._correlation_run_id(run_id),
                            )
                    self.sync_state_store.update_run(
                        run_id,
                        progress=self._delta_sync_progress(
                            changes_total=len(changes),
                            changes_processed=index,
                        ),
                    )
                self.repo_lease_store.assert_owned(lease)
                if not self.sync_state_store.advance_cursor(
                    repo_id=repo_id,
                    scope=normalized_scope,
                    expected_commit_id=cursor.commit_id,
                    target_commit_id=target_commit_id,
                    snapshot_id=target_snapshot_id,
                ):
                    raise RuntimeError("sync cursor changed while delta sync was running")
                if normalized_scope == "/":
                    with self.session_factory() as session:
                        library = self._get_library(session, repo_id)
                        library.last_synced_commit_id = target_commit_id
                        library.status = "active"
                        library.last_error = None
                        session.commit()
                summary = SyncSummary(
                    libraries_synced=1,
                    files_seen=len([entry for entry in target_entries if not entry.is_directory]),
                    files_uploaded=files_uploaded,
                    files_deleted=files_deleted,
                    files_skipped=files_skipped,
                )
                self._complete_or_wait_for_async_work(
                    run_id,
                    repo_id,
                    {
                        "changes": len(changes),
                        "processed": len(changes),
                        "files_uploaded": files_uploaded,
                        "files_deleted": files_deleted,
                        "files_skipped": files_skipped,
                    },
                )
                return summary
            except Exception as exc:
                cancelled = isinstance(exc, SyncCancelledError)
                if not cancelled:
                    self._mark_library_error(repo_id, exc)
                self.sync_state_store.update_run(
                    run_id,
                    status="cancelled" if cancelled else "failed",
                    progress=self._terminal_run_progress(
                        run_id,
                        terminal_phase="cancelled" if cancelled else "failed",
                    ),
                    error_message=None if cancelled else str(exc)[:4000],
                    finished=True,
                )
                raise

    def plan_library_reconcile(self, repo_id: str, *, scope: str = "/") -> ReconcilePlan:
        active = current_repo_lease(repo_id)
        if active is None:
            with self._mutation_scope(
                repo_id,
                owner_id=f"reconcile-plan:{new_sync_id(repo_id)}",
            ):
                return self.plan_library_reconcile(repo_id, scope=scope)
        self.repo_lease_store.assert_owned(active)
        normalized_scope = normalize_seafile_path(scope)
        with self.session_factory() as session:
            library = self._get_library(session, repo_id)
            dataset_id = library.ragflow_dataset_id
            target_commit_id = library.head_commit_id
        if not dataset_id:
            return ReconcilePlan(
                repo_id=repo_id,
                scope=normalized_scope,
                commit_id=target_commit_id,
                warnings=["library has no RAGFlow dataset binding"],
            )
        source_entries: list[SnapshotEntry] | None = None
        snapshot_id: int | None = None
        plan_commit_id = target_commit_id
        if target_commit_id:
            captured = self._try_capture_snapshot(
                repo_id,
                target_commit_id,
                normalized_scope,
            )
            if captured is not None:
                snapshot_id, source_entries = captured
        if source_entries is None:
            cursor = self.sync_state_store.get_cursor(repo_id, normalized_scope)
            if cursor is not None:
                snapshot_id = cursor.snapshot_id
                plan_commit_id = cursor.commit_id
                source_entries = snapshot_entries_from_records(
                    self.sync_state_store.snapshot_entries(cursor.snapshot_id)
                )
        plan = self.reconciler.plan_library_reconcile(
            repo_id,
            dataset_id,
            source_entries=source_entries,
            scope=normalized_scope,
            commit_id=plan_commit_id,
            snapshot_id=snapshot_id,
        )
        if source_entries is None:
            return ReconcilePlan(
                repo_id=plan.repo_id,
                dataset_id=plan.dataset_id,
                scope=plan.scope,
                commit_id=plan.commit_id,
                snapshot_id=plan.snapshot_id,
                jobs=plan.jobs,
                categories=plan.categories,
                warnings=[*plan.warnings, "no complete Seafile snapshot is available"],
            )
        return plan

    def reconcile_library(
        self,
        repo_id: str,
        *,
        scope: str = "/",
        execute: bool = False,
    ) -> ReconcilePlan:
        if execute:
            self.assert_library_runnable(repo_id)
        with self._mutation_scope(
            repo_id,
            owner_id=f"reconcile:{new_sync_id(repo_id)}",
        ) as lease:
            plan = self.plan_library_reconcile(repo_id, scope=scope)
            if not execute or not plan.jobs:
                return plan
            self._assert_reconcile_plan_current(plan)
            with self.session_factory() as session:
                library = self._get_library(session, repo_id)
                dataset_id = library.ragflow_dataset_id
            if not dataset_id:
                return ReconcilePlan(
                    repo_id=plan.repo_id,
                    dataset_id=plan.dataset_id,
                    scope=plan.scope,
                    commit_id=plan.commit_id,
                    snapshot_id=plan.snapshot_id,
                    jobs=plan.jobs,
                    categories=plan.categories,
                    warnings=[*plan.warnings, "reconcile execution skipped without dataset"],
                )
            for job in plan.jobs:
                self.repo_lease_store.assert_owned(lease)
                self._assert_reconcile_plan_current(plan)
                if job_cancellation_requested():
                    raise SyncCancelledError("reconcile cancellation requested")
                if job.job_type == JobType.DELETE_FILE and job.file_path:
                    self.delete_file(
                        repo_id,
                        dataset_id,
                        job.file_path,
                        lease=lease,
                    )
                elif job.job_type == JobType.UPLOAD_FILE and job.file_path:
                    self.sync_file(
                        repo_id,
                        dataset_id,
                        job.file_path,
                        force=bool(job.payload.get("force")),
                        source_commit_id=plan.commit_id,
                        lease=lease,
                    )
                elif job.job_type == JobType.CHECK_PARSE_STATUS:
                    self.check_parse_status(repo_id, dataset_id)
            self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
        return plan

    def _assert_reconcile_plan_current(self, plan: ReconcilePlan) -> None:
        if not plan.repo_id or not plan.commit_id or plan.snapshot_id is None:
            raise ReconcilePlanStaleError(
                "reconcile execution requires a pinned complete source snapshot"
            )
        snapshot = self.sync_state_store.get_snapshot(plan.snapshot_id)
        if (
            snapshot is None
            or not snapshot.complete
            or snapshot.commit_id != plan.commit_id
            or snapshot.repo_id != plan.repo_id
            or snapshot.scope != plan.scope
        ):
            raise ReconcilePlanStaleError("reconcile source snapshot is no longer valid")
        with self.session_factory() as session:
            library = self._get_library(session, plan.repo_id)
            current_head = library.head_commit_id
        if current_head != plan.commit_id:
            raise ReconcilePlanStaleError(
                "Seafile head changed after reconcile planning; create a fresh plan"
            )

    def sync_file(
        self,
        repo_id: str,
        dataset_id: str,
        path: str,
        *,
        item: dict[str, Any] | None = None,
        force: bool = False,
        sync_id: str | None = None,
        source_commit_id: str | None = None,
        lease: RepoLeaseHandle | None = None,
    ) -> FileSyncResult:
        if lease is None:
            self.assert_library_runnable(repo_id)
            with self._mutation_scope(
                repo_id,
                owner_id=f"file:{new_sync_id(repo_id)}",
            ) as acquired:
                return self.sync_file(
                    repo_id,
                    dataset_id,
                    path,
                    item=item,
                    force=force,
                    sync_id=sync_id,
                    source_commit_id=source_commit_id,
                    lease=acquired,
                )
        self.repo_lease_store.assert_owned(lease)
        self._raise_if_job_interrupted("file sync interrupted before download")
        if source_commit_id and hasattr(self.sync_client, "download_file_revision"):
            data = self.sync_client.download_file_revision(repo_id, path, source_commit_id)
        else:
            data = self.sync_client.download_file(repo_id, path)
        self._raise_if_job_interrupted("file sync interrupted after download")
        classification = classify_file(path, data, self.file_policy)
        artifact = None
        if classification.should_ingest:
            artifact = prepare_ingestion_artifact(classification, data)
        self._raise_if_job_interrupted("file sync interrupted after conversion")

        pending_version_id: int | None = None
        resume_document_id: str | None = None
        upload_operation_id: str | None = None
        old_version_id: int | None = None
        with self.session_factory() as session:
            db_file = self._upsert_file_row(
                session,
                repo_id=repo_id,
                path=path,
                item=item,
                classification=classification,
            )
            if source_commit_id:
                db_file.last_seen_commit_id = source_commit_id
            if not classification.should_ingest or artifact is None:
                retired_document_id = db_file.ragflow_document_id
                db_file.sync_status = "skipped"
                db_file.error_message = classification.reason
                session.commit()
                if retired_document_id:
                    self._queue_file_cleanup(
                        repo_id,
                        dataset_id,
                        path,
                        fence_token=lease.fence_token if lease else None,
                        run_id=self._correlation_run_id(sync_id),
                    )
                    self._raise_if_job_interrupted(
                        "file sync interrupted before cleanup processing"
                    )
                    self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
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
            old_version_id = self._ensure_current_document_version(
                session,
                db_file,
                dataset_id,
            )
            if unchanged and old_version_id is not None:
                old_version = session.get(FileDocumentVersion, old_version_id)
                unchanged = bool(
                    old_version is not None
                    and old_version.state == "current"
                    and old_version.parse_status != "FAIL"
                )
            pending_version_stmt = (
                select(FileDocumentVersion)
                .where(FileDocumentVersion.file_id == db_file.id)
                .where(FileDocumentVersion.dataset_id == dataset_id)
                .where(
                    FileDocumentVersion.state.in_(
                        ["pending_upload", "uploaded", "parsing", "retryable_failed"]
                    )
                )
                .where(
                    FileDocumentVersion.source_content_sha256
                    == artifact.source_content_sha256
                )
                .where(
                    FileDocumentVersion.ingested_content_sha256
                    == artifact.ingested_content_sha256
                )
                .order_by(FileDocumentVersion.id.desc())
            )
            if old_version_id is not None:
                pending_version_stmt = pending_version_stmt.where(
                    FileDocumentVersion.id > old_version_id
                )
            pending_version = session.scalar(pending_version_stmt)
            if pending_version is not None:
                pending_version_id = int(pending_version.id)
                resume_document_id = pending_version.document_id
                if not pending_version.upload_operation_id:
                    pending_version.upload_operation_id = uuid4().hex
                upload_operation_id = pending_version.upload_operation_id
                if pending_version.state == "parsing" and resume_document_id:
                    db_file.sync_status = "parsing"
                    session.commit()
                    self._raise_if_job_interrupted(
                        "file sync interrupted before parse-status scheduling"
                    )
                    self._ensure_parse_status_job(
                        repo_id,
                        dataset_id,
                        run_id=self._correlation_run_id(sync_id),
                    )
                    return FileSyncResult(
                        uploaded=False,
                        skipped=False,
                        document_id=resume_document_id,
                        change_type="pending",
                    )
            db_file.sync_status = "pending"
            db_file.error_message = None
            session.commit()

            if unchanged and old_document_id:
                self._raise_if_job_interrupted(
                    "file sync interrupted before document verification"
                )
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

        settings_hash = None
        self._raise_if_job_interrupted("file sync interrupted before dataset settings")
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
        self._raise_if_job_interrupted("file sync interrupted after dataset settings")

        if pending_version_id is None:
            with self.session_factory() as session:
                db_file = self._get_file(session, repo_id, normalize_seafile_path(path))
                version = FileDocumentVersion(
                    file_id=db_file.id,
                    repo_id=repo_id,
                    normalized_path=db_file.normalized_path,
                    dataset_id=dataset_id,
                    document_name=artifact.document_name,
                    source_content_sha256=artifact.source_content_sha256,
                    ingested_content_sha256=artifact.ingested_content_sha256,
                    ingested_mime=artifact.mime_type,
                    state="pending_upload",
                    previous_version_id=old_version_id,
                    upload_operation_id=uuid4().hex,
                )
                session.add(version)
                session.commit()
                pending_version_id = int(version.id)
                upload_operation_id = version.upload_operation_id

        if not upload_operation_id:
            with self.session_factory() as session:
                stored_version = session.get(FileDocumentVersion, pending_version_id)
                if stored_version is None:
                    raise RuntimeError("pending document version disappeared before upload")
                stored_version.upload_operation_id = (
                    stored_version.upload_operation_id or uuid4().hex
                )
                upload_operation_id = stored_version.upload_operation_id
                session.commit()

        assert upload_operation_id is not None
        managed_document_name = _managed_upload_document_name(
            artifact.document_name,
            upload_operation_id,
        )
        metadata = build_ragflow_document_metadata(
            artifact,
            repo_id=repo_id,
            path=path,
            item=item,
        )
        metadata.update(
            {
                "connector_managed": "true",
                "connector_upload_operation_id": upload_operation_id,
            }
        )

        uploaded_now = False
        if resume_document_id is None:
            if lease is not None:
                self.repo_lease_store.assert_owned(lease)
            self._raise_if_job_interrupted("file sync interrupted before upload recovery")
            recovered = self._recover_managed_upload(
                dataset_id,
                managed_document_name=managed_document_name,
                upload_operation_id=upload_operation_id,
            )
            if recovered is None:
                self._raise_if_job_interrupted("file sync interrupted before upload")
                document = self.ragflow_client.upload_document(
                    dataset_id,
                    document_name=managed_document_name,
                    content=artifact.content,
                    mime_type=artifact.mime_type,
                )
                uploaded_now = True
            else:
                document = recovered
            self._raise_if_job_interrupted("file sync interrupted after upload")
            document_id = str(document.get("id") or document.get("document_id") or "")
            if not document_id:
                msg = f"RAGFlow upload response did not contain a document id for {path}"
                raise RuntimeError(msg)
            self._raise_if_job_interrupted("file sync interrupted before metadata")
            self._update_managed_document_metadata(
                dataset_id,
                document_id,
                metadata,
                sync_id=sync_id,
                repo_id=repo_id,
                path=path,
            )
            self._raise_if_job_interrupted("file sync interrupted after metadata")
            with self.session_factory() as session:
                stored_version = session.get(FileDocumentVersion, pending_version_id)
                if stored_version is None:
                    raise RuntimeError("pending document version disappeared after upload")
                stored_version.document_id = document_id
                stored_version.state = "uploaded"
                stored_version.error_message = None
                session.commit()
        else:
            document_id = resume_document_id
            self._raise_if_job_interrupted("file sync interrupted before metadata")
            self._update_managed_document_metadata(
                dataset_id,
                document_id,
                metadata,
                sync_id=sync_id,
                repo_id=repo_id,
                path=path,
            )
            self._raise_if_job_interrupted("file sync interrupted after metadata")
        self._raise_if_job_interrupted("file sync interrupted before rename")
        self._restore_friendly_document_name(
            dataset_id,
            document_id,
            artifact.document_name,
            sync_id=sync_id,
            repo_id=repo_id,
            path=path,
        )
        self._raise_if_job_interrupted("file sync interrupted after rename")
        if lease is not None:
            self.repo_lease_store.assert_owned(lease)
        self._raise_if_job_interrupted("file sync interrupted before parse")
        self.ragflow_client.parse_documents(dataset_id, [document_id])
        self._raise_if_job_interrupted("file sync interrupted after parse")

        with self.session_factory() as session:
            db_file = self._get_file(session, repo_id, normalize_seafile_path(path))
            db_file.last_uploaded_dataset_settings_hash = settings_hash
            db_file.sync_status = "parsing"
            db_file.parse_status = "UNSTART"
            db_file.error_message = None
            stored_version = session.get(FileDocumentVersion, pending_version_id)
            if stored_version is None:
                raise RuntimeError("pending document version disappeared before parse tracking")
            stored_version.state = "parsing"
            stored_version.parse_status = "UNSTART"
            stored_version.error_message = None
            session.commit()
        self._raise_if_job_interrupted(
            "file sync interrupted before parse-status scheduling"
        )
        self._ensure_parse_status_job(
            repo_id,
            dataset_id,
            run_id=self._correlation_run_id(sync_id),
        )

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
        change_type = "updated" if old_document_id else "created"
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
                "previous_document_id": old_document_id,
                "document_state": "parsing",
            },
        )
        return FileSyncResult(
            uploaded=uploaded_now,
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
        lease: RepoLeaseHandle | None = None,
    ) -> bool:
        if lease is None:
            self.assert_library_runnable(repo_id)
            with self._mutation_scope(
                repo_id,
                owner_id=f"delete:{new_sync_id(repo_id)}",
            ) as acquired:
                return self.delete_file(
                    repo_id,
                    dataset_id,
                    path,
                    sync_id=sync_id,
                    lease=acquired,
                )
        self.repo_lease_store.assert_owned(lease)
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
            self._queue_file_cleanup(
                repo_id,
                dataset_id,
                normalized_path,
                fence_token=lease.fence_token if lease else None,
                delete_file_row=True,
                run_id=self._correlation_run_id(sync_id),
            )
            completed = self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
            if completed <= 0:
                return False
        else:
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
        lease: RepoLeaseHandle | None = None,
    ) -> int:
        if lease is None:
            self.assert_library_runnable(repo_id)
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
            self._raise_if_job_interrupted("missing-file cleanup interrupted")
            removed = self.delete_file(
                repo_id,
                dataset_id,
                row.normalized_path,
                sync_id=sync_id,
                lease=lease,
            )
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
            deleted += int(removed or not row.ragflow_document_id)
        return deleted

    def check_parse_status(
        self,
        repo_id: str,
        dataset_id: str,
        *,
        raise_if_pending: bool = False,
    ) -> int:
        self.assert_library_runnable(repo_id)
        with self._mutation_scope(
            repo_id,
            owner_id=f"parse:{new_sync_id(repo_id)}",
        ) as lease:
            documents = self.ragflow_client.iter_documents(dataset_id)
            by_id = {
                document_id: document
                for document in documents
                if (document_id := _document_id(document))
            }
            updated = 0
            retry_ids: list[str] = []
            cleanup_outbox_ids: set[int] = set()
            cleanup_run_id = self._correlation_run_id()
            self.repo_lease_store.assert_owned(lease)
            with self.session_factory() as session:
                for db_file in session.scalars(
                    select(File)
                    .where(File.repo_id == repo_id)
                    .where(File.ragflow_document_id.is_not(None))
                ):
                    self._ensure_current_document_version(session, db_file, dataset_id)
                session.flush()
                versions = session.scalars(
                    select(FileDocumentVersion)
                    .where(FileDocumentVersion.repo_id == repo_id)
                    .where(FileDocumentVersion.dataset_id == dataset_id)
                    .where(
                        FileDocumentVersion.state.in_(
                            [
                                "current",
                                "pending_upload",
                                "uploaded",
                                "parsing",
                                "retryable_failed",
                                "dead",
                            ]
                        )
                    )
                ).all()
                latest_version_id_by_file: dict[int, int] = {}
                for version in versions:
                    latest_version_id_by_file[version.file_id] = max(
                        int(version.id),
                        latest_version_id_by_file.get(version.file_id, 0),
                    )
                for version in versions:
                    self._raise_if_job_interrupted("parse-status update interrupted")
                    tracked_file = session.get(File, version.file_id)
                    if tracked_file is None:
                        continue
                    is_latest_version = int(version.id) == latest_version_id_by_file.get(
                        version.file_id
                    )
                    is_bound_document = bool(
                        version.document_id
                        and tracked_file.ragflow_document_id == version.document_id
                    )
                    if (
                        version.state != "current"
                        and not is_latest_version
                        and not is_bound_document
                    ):
                        version.state = "superseded"
                        version.error_message = None
                        if version.document_id is not None:
                            cleanup_outbox_ids.add(
                                self._enqueue_cleanup_in_session(
                                    session,
                                    repo_id=repo_id,
                                    target_type="ragflow_document",
                                    target_id=version.document_id,
                                    dataset_id=version.dataset_id,
                                    document_version_id=int(version.id),
                                    fence_token=lease.fence_token,
                                    run_id=cleanup_run_id,
                                )
                            )
                        updated += 1
                        continue
                    if version.state not in {
                        "current",
                        "uploaded",
                        "parsing",
                        "retryable_failed",
                    }:
                        continue
                    if version.document_id is None:
                        continue
                    document = by_id.get(version.document_id)
                    if document is None:
                        continue
                    parse_status = str(document.get("run") or "").strip().upper()
                    if not parse_status:
                        continue
                    version.poll_count += 1
                    version.parse_status = parse_status
                    if parse_status == "FAIL":
                        version.retry_count += 1
                        version.error_message = str(document.get("progress_msg") or "")[:4000]
                        if version.retry_count < 5:
                            version.state = "retryable_failed"
                            retry_ids.append(version.document_id)
                        else:
                            version.state = "dead"
                        tracked_file.sync_status = "parse_failed"
                        tracked_file.parse_status = "FAIL"
                        tracked_file.retry_count = version.retry_count
                        tracked_file.error_message = version.error_message
                    elif parse_status == "DONE":
                        version.retry_count = 0
                        version.error_message = None
                        if version.state != "current" and is_latest_version:
                            previous_versions = session.scalars(
                                select(FileDocumentVersion)
                                .where(FileDocumentVersion.file_id == version.file_id)
                                .where(FileDocumentVersion.id != version.id)
                                .where(
                                    FileDocumentVersion.state.in_(
                                        [
                                            "current",
                                            "dead",
                                            "retryable_failed",
                                            "parsing",
                                        ]
                                    )
                                )
                            ).all()
                            for previous in previous_versions:
                                previous.state = "superseded"
                                if previous.document_id:
                                    cleanup_outbox_ids.add(
                                        self._enqueue_cleanup_in_session(
                                            session,
                                            repo_id=repo_id,
                                            target_type="ragflow_document",
                                            target_id=previous.document_id,
                                            dataset_id=previous.dataset_id,
                                            document_version_id=int(previous.id),
                                            fence_token=lease.fence_token,
                                            run_id=cleanup_run_id,
                                        )
                                    )
                            version.state = "current"
                            version.promoted_at = datetime.now(UTC)
                            tracked_file.source_content_sha256 = version.source_content_sha256
                            tracked_file.ingested_content_sha256 = version.ingested_content_sha256
                            tracked_file.ragflow_document_id = version.document_id
                            tracked_file.ragflow_document_name = version.document_name
                            tracked_file.ingested_document_name = version.document_name
                            tracked_file.ingested_mime = version.ingested_mime
                            tracked_file.sync_status = "synced"
                            tracked_file.parse_status = "DONE"
                            tracked_file.retry_count = 0
                            tracked_file.error_message = None
                        elif is_bound_document or (
                            version.state == "current" and is_latest_version
                        ):
                            if is_bound_document:
                                version.state = "current"
                            tracked_file.sync_status = "synced"
                            tracked_file.parse_status = "DONE"
                            tracked_file.retry_count = 0
                            tracked_file.error_message = None
                    else:
                        version.state = "parsing"
                        version.error_message = None
                        tracked_file.sync_status = "parsing"
                        tracked_file.parse_status = parse_status
                        tracked_file.error_message = None
                    updated += 1
                self._raise_if_job_interrupted("parse-status update interrupted before commit")
                session.commit()

            parent_job_id = current_job_id()
            if parent_job_id is not None:
                for outbox_id in cleanup_outbox_ids:
                    self.job_store.subscribe_cleanup_from_job(parent_job_id, outbox_id)

            for document_id in retry_ids:
                self._raise_if_job_interrupted("document reparse interrupted")
                self.repo_lease_store.assert_owned(lease)
                try:
                    self.ragflow_client.parse_documents(dataset_id, [document_id])
                except Exception as exc:
                    self.log.warning(
                        "ragflow.document_parse_retry_failed",
                        repo_id=repo_id,
                        dataset_id=dataset_id,
                        document_id=document_id,
                        error_class=type(exc).__name__,
                    )
                else:
                    with self.session_factory() as session:
                        retry_version = session.scalar(
                            select(FileDocumentVersion).where(
                                FileDocumentVersion.document_id == document_id
                            )
                        )
                        if retry_version is not None:
                            retry_version.state = "parsing"
                            session.commit()
            self._raise_if_job_interrupted("document cleanup interrupted")
            self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
            self._ensure_parse_status_job(
                repo_id,
                dataset_id,
                run_id=self._correlation_run_id(),
            )
            self._refresh_waiting_sync_runs(repo_id)
            if raise_if_pending:
                counts = self._async_work_counts(repo_id)
                pending = counts["pending_parse"]
                dead = counts["dead_parse"]
                if dead:
                    raise ParseDeadError(
                        f"{dead} RAGFlow document(s) exhausted parse retries"
                    )
                if pending:
                    raise ParsePendingError(
                        f"{pending} RAGFlow document(s) are still parsing",
                        delay_seconds=30,
                    )
            return updated

    def assert_library_runnable(self, repo_id: str) -> None:
        control = self.admin_control_store.library(repo_id)
        if not control.runnable:
            raise ValueError(
                f"library {repo_id!r} is {control.state} and cannot be mutated"
            )

    @contextmanager
    def _mutation_scope(
        self,
        repo_id: str,
        *,
        owner_id: str,
    ) -> Iterator[RepoLeaseHandle]:
        active = current_repo_lease(repo_id)
        if active is not None:
            self.repo_lease_store.assert_owned(active)
            yield active
            return
        handle = self.repo_lease_store.acquire(
            repo_id,
            owner_id,
            lease_seconds=900,
        )
        try:
            with activate_repo_lease(handle):
                yield handle
        finally:
            self.repo_lease_store.release(handle)

    def _cancellation_requested(self, run_id: str) -> bool:
        return job_cancellation_requested() or self.sync_state_store.cancel_requested(run_id)

    @staticmethod
    def _raise_if_job_interrupted(message: str) -> None:
        if job_cancellation_requested():
            raise SyncCancelledError(message)

    def _raise_if_automatic_cycle_interrupted(
        self,
        trigger: str,
        message: str,
    ) -> None:
        if trigger != "automatic":
            return
        if current_job_id() is not None:
            self._raise_if_job_interrupted(message)
            return
        try:
            queue_paused = self.admin_control_store.workflow().queue_paused
        except Exception as exc:
            raise SyncCancelledError(
                f"{message}: workflow control could not be verified"
            ) from exc
        if queue_paused:
            raise SyncCancelledError(message)

    def _current_parent_run_id(self) -> str | None:
        run_id = current_job_run_id()
        return run_id if run_id and self.sync_state_store.get_run(run_id) is not None else None

    def _correlation_run_id(self, fallback: str | None = None) -> str | None:
        run_id = current_job_run_id() or fallback
        return run_id if run_id and self.sync_state_store.get_run(run_id) is not None else None

    def _current_execution_trigger(self, *, default: str = "manual") -> str:
        job_id = current_job_id()
        if job_id is None:
            return default
        job = self.job_store.get(job_id)
        if job is None:
            return default
        trigger = str((job.payload or {}).get("trigger") or "").strip().lower()
        return trigger if trigger in {"automatic", "manual"} else "automatic"

    def _library_dataset_id(self, repo_id: str) -> str | None:
        with self.session_factory() as session:
            library = session.get(Library, repo_id)
            return library.ragflow_dataset_id if library is not None else None

    def _async_work_counts(self, repo_id: str) -> dict[str, int]:
        with self.session_factory() as session:
            version_states = session.execute(
                select(
                    FileDocumentVersion.file_id,
                    FileDocumentVersion.id,
                    FileDocumentVersion.state,
                )
                .where(FileDocumentVersion.repo_id == repo_id)
                .order_by(FileDocumentVersion.file_id, FileDocumentVersion.id.desc())
            ).all()
            latest_state_by_file: dict[int, str] = {}
            for file_id, _version_id, state in version_states:
                latest_state_by_file.setdefault(int(file_id), str(state))
            pending_parse = sum(
                state
                in {
                    "pending_upload",
                    "uploaded",
                    "parsing",
                    "retryable_failed",
                }
                for state in latest_state_by_file.values()
            )
            dead_parse = sum(
                state == "dead" for state in latest_state_by_file.values()
            )
            pending_cleanup = int(
                session.scalar(
                    select(func.count(CleanupOutbox.id))
                    .where(CleanupOutbox.repo_id == repo_id)
                    .where(CleanupOutbox.status.in_(["pending", "retrying"]))
                )
                or 0
            )
            dead_cleanup = int(
                session.scalar(
                    select(func.count(CleanupOutbox.id))
                    .where(CleanupOutbox.repo_id == repo_id)
                    .where(CleanupOutbox.status == "dead")
                )
                or 0
            )
        return {
            "pending_parse": pending_parse,
            "dead_parse": dead_parse,
            "pending_cleanup": pending_cleanup,
            "dead_cleanup": dead_cleanup,
        }

    @staticmethod
    def _file_sync_progress(
        *,
        files_total: int,
        files_processed: int,
        phase: str = "syncing",
    ) -> dict[str, int | float | str]:
        total = max(0, files_total)
        processed = min(max(0, files_processed), total)
        percent = 0.0 if total == 0 else round(processed * 100.0 / total, 2)
        return {
            "phase": phase,
            "files_total": total,
            "files_processed": processed,
            "total": total,
            "completed": processed,
            "percent": percent,
        }

    @staticmethod
    def _delta_sync_progress(
        *,
        changes_total: int,
        changes_processed: int,
        phase: str = "syncing",
    ) -> dict[str, int | float | str]:
        total = max(0, changes_total)
        processed = min(max(0, changes_processed), total)
        percent = 0.0 if total == 0 else round(processed * 100.0 / total, 2)
        return {
            "phase": phase,
            "changes": total,
            "processed": processed,
            "total": total,
            "completed": processed,
            "percent": percent,
        }

    def _terminal_run_progress(
        self,
        run_id: str,
        *,
        terminal_phase: str,
    ) -> dict[str, Any]:
        run = self.sync_state_store.get_run(run_id)
        progress = dict(run.progress or {}) if run is not None else {}
        previous_phase = str(progress.get("phase") or "unknown")
        progress["phase"] = terminal_phase
        progress[f"{terminal_phase}_phase"] = previous_phase
        return progress

    def _complete_or_wait_for_async_work(
        self,
        run_id: str,
        repo_id: str,
        progress: Mapping[str, Any],
    ) -> str:
        counts = self._async_work_counts(repo_id)
        run = self.sync_state_store.get_run(run_id)
        existing_progress = dict(run.progress or {}) if run is not None else {}
        if counts["pending_parse"] or counts["dead_parse"]:
            phase = "parsing"
        elif counts["pending_cleanup"] or counts["dead_cleanup"]:
            phase = "cleanup"
        else:
            phase = "completed"
        merged_progress = {
            **existing_progress,
            **dict(progress),
            **counts,
            "sync_phase_complete": True,
            "phase": phase,
        }
        if phase == "completed":
            merged_progress["percent"] = 100.0
        if counts["dead_parse"] or counts["dead_cleanup"]:
            error = (
                "asynchronous sync work failed: "
                f"parse={counts['dead_parse']}, cleanup={counts['dead_cleanup']}"
            )
            self.sync_state_store.update_run(
                run_id,
                status="failed",
                progress=merged_progress,
                error_message=error,
                finished=True,
            )
            self._update_dashboard_async_status(
                run_id,
                status="failed",
                progress=merged_progress,
                terminal=True,
                error_message=error,
            )
            return "failed"
        if counts["pending_parse"] or counts["pending_cleanup"]:
            self.sync_state_store.update_run(
                run_id,
                status="running",
                progress=merged_progress,
            )
            self._update_dashboard_async_status(
                run_id,
                status="running",
                progress=merged_progress,
                terminal=False,
            )
            return "running"
        self.sync_state_store.update_run(
            run_id,
            status="succeeded",
            progress=merged_progress,
            finished=True,
        )
        self._update_dashboard_async_status(
            run_id,
            status="succeeded",
            progress=merged_progress,
            terminal=True,
        )
        return "succeeded"

    def _refresh_waiting_sync_runs(self, repo_id: str) -> None:
        with self.session_factory() as session:
            runs = list(
                session.scalars(
                    select(SyncRun)
                    .where(SyncRun.repo_id == repo_id)
                    .where(SyncRun.status.in_(["running", "retrying"]))
                    .where(SyncRun.mode != "workflow")
                ).all()
            )
            snapshots = [
                (run.id, dict(run.progress or {}))
                for run in runs
                if (run.progress or {}).get("sync_phase_complete")
                or any(
                    key in (run.progress or {})
                    for key in (
                        "pending_parse",
                        "dead_parse",
                        "pending_cleanup",
                        "dead_cleanup",
                    )
                )
            ]
        for run_id, progress in snapshots:
            self._complete_or_wait_for_async_work(run_id, repo_id, progress)

    def _ensure_parse_status_job(
        self,
        repo_id: str,
        dataset_id: str | None,
        *,
        run_id: str | None = None,
        trigger: str | None = None,
    ) -> int | None:
        if not dataset_id:
            return None
        with self.session_factory() as session:
            pending = session.scalar(
                select(func.count(FileDocumentVersion.id))
                .where(FileDocumentVersion.repo_id == repo_id)
                .where(FileDocumentVersion.dataset_id == dataset_id)
                .where(
                    FileDocumentVersion.state.in_(
                        ["uploaded", "parsing", "retryable_failed"]
                    )
                )
            )
        if not pending:
            return None
        payload = {"dataset_id": dataset_id}
        resolved_trigger = trigger or self._current_execution_trigger()
        if resolved_trigger == "manual":
            payload["trigger"] = "manual"
        result = self.job_store.enqueue_with_result(
            JobSpec(
                JobType.CHECK_PARSE_STATUS,
                repo_id=repo_id,
                payload=payload,
                max_attempts=5,
            )
        )
        correlation_run_id = run_id or self._correlation_run_id()
        if correlation_run_id:
            self.job_store.bind_run_if_unbound(result.job_id, correlation_run_id)
        parent_job_id = current_job_id()
        if parent_job_id is not None:
            self.job_store.inherit_workflow_subscriptions(
                parent_job_id,
                result.job_id,
                child_created=not result.deduplicated,
            )
        return result.job_id

    def _try_capture_snapshot(
        self,
        repo_id: str,
        commit_id: str,
        scope: str,
    ) -> tuple[int, list[SnapshotEntry]] | None:
        if not hasattr(self.sync_client, "list_dir_at_commit"):
            return None
        try:
            entries = capture_commit_snapshot(
                self.sync_client,
                repo_id,
                commit_id,
                scope=scope,
            )
        except ApiError as exc:
            if exc.status_code not in {400, 404, 405, 501}:
                raise
            self.log.info(
                "seafile.commit_snapshot_unavailable",
                repo_id=repo_id,
                commit_id=commit_id,
                status_code=exc.status_code,
                fallback="live_full_sync",
            )
            return None
        except TypeError as exc:
            if not _is_incompatible_snapshot_client_error(exc):
                raise
            self.log.info(
                "seafile.commit_snapshot_incompatible",
                repo_id=repo_id,
                commit_id=commit_id,
                error_class=type(exc).__name__,
                fallback="live_full_sync",
            )
            return None
        snapshot = self.sync_state_store.replace_snapshot(
            repo_id=repo_id,
            commit_id=commit_id,
            scope=scope,
            entries=[entry.as_record() for entry in entries],
            complete=True,
        )
        return snapshot.snapshot_id, entries

    @staticmethod
    def _snapshot_item(entry: SnapshotEntry) -> dict[str, Any]:
        item = dict(entry.raw)
        if entry.object_id:
            item.setdefault("id", entry.object_id)
        if entry.size is not None:
            item.setdefault("size", entry.size)
        if entry.mtime is not None:
            item.setdefault("mtime", entry.mtime)
        return item

    def _ensure_current_document_version(
        self,
        session: Session,
        db_file: File,
        dataset_id: str,
    ) -> int | None:
        if not db_file.ragflow_document_id:
            return None
        existing = session.scalar(
            select(FileDocumentVersion)
            .where(FileDocumentVersion.file_id == db_file.id)
            .where(FileDocumentVersion.document_id == db_file.ragflow_document_id)
            .order_by(FileDocumentVersion.id.desc())
        )
        if existing is not None:
            return int(existing.id)
        version = FileDocumentVersion(
            file_id=db_file.id,
            repo_id=db_file.repo_id,
            normalized_path=db_file.normalized_path,
            dataset_id=dataset_id,
            document_id=db_file.ragflow_document_id,
            document_name=(
                db_file.ragflow_document_name
                or db_file.ingested_document_name
                or _basename(db_file.normalized_path)
            ),
            source_content_sha256=db_file.source_content_sha256,
            ingested_content_sha256=db_file.ingested_content_sha256,
            ingested_mime=db_file.ingested_mime,
            state="current",
            parse_status=db_file.parse_status,
            poll_count=0,
            retry_count=db_file.retry_count,
            error_message=db_file.error_message,
            promoted_at=db_file.updated_at,
        )
        session.add(version)
        session.flush()
        return int(version.id)

    def _queue_file_cleanup(
        self,
        repo_id: str,
        dataset_id: str,
        path: str,
        *,
        fence_token: int | None,
        wait_for_document_id: str | None = None,
        delete_file_row: bool = False,
        run_id: str | None = None,
    ) -> bool:
        normalized_path = normalize_seafile_path(path)
        with self.session_factory() as session:
            db_file = session.scalar(
                select(File).where(
                    File.repo_id == repo_id,
                    File.normalized_path == normalized_path,
                )
            )
            if db_file is None or not db_file.ragflow_document_id:
                if db_file is not None and delete_file_row:
                    session.delete(db_file)
                    session.commit()
                return False
            version_id = self._ensure_current_document_version(session, db_file, dataset_id)
            file_id = int(db_file.id)
            document_id = db_file.ragflow_document_id
            session.commit()
        self._enqueue_cleanup(
            repo_id=repo_id,
            target_type="ragflow_document",
            target_id=document_id,
            dataset_id=dataset_id,
            file_id=file_id,
            document_version_id=version_id,
            fence_token=fence_token,
            run_id=run_id,
            payload={
                "wait_for_document_id": wait_for_document_id,
                "delete_file_row": delete_file_row,
                "clear_binding": not delete_file_row,
            },
        )
        return True

    def _enqueue_cleanup(
        self,
        *,
        repo_id: str,
        target_type: str,
        target_id: str,
        dataset_id: str | None,
        file_id: int | None = None,
        document_version_id: int | None = None,
        fence_token: int | None = None,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        with self.session_factory() as session:
            outbox_id = self._enqueue_cleanup_in_session(
                session,
                repo_id=repo_id,
                target_type=target_type,
                target_id=target_id,
                dataset_id=dataset_id,
                file_id=file_id,
                document_version_id=document_version_id,
                fence_token=fence_token,
                run_id=run_id,
                payload=payload,
            )
            session.commit()
        parent_job_id = current_job_id()
        if parent_job_id is not None:
            self.job_store.subscribe_cleanup_from_job(parent_job_id, outbox_id)
        return outbox_id

    @staticmethod
    def _enqueue_cleanup_in_session(
        session: Session,
        *,
        repo_id: str,
        target_type: str,
        target_id: str,
        dataset_id: str | None,
        file_id: int | None = None,
        document_version_id: int | None = None,
        fence_token: int | None = None,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        existing = session.scalar(
            select(CleanupOutbox)
            .where(
                CleanupOutbox.target_type == target_type,
                CleanupOutbox.target_id == target_id,
                CleanupOutbox.action == "delete",
            )
            .with_for_update()
        )
        if existing is not None:
            existing.repo_id = repo_id
            existing.run_id = run_id or existing.run_id
            existing.file_id = file_id
            existing.document_version_id = document_version_id
            existing.dataset_id = dataset_id
            existing.payload = dict(payload or {})
            existing.fence_token = fence_token
            if existing.status in {"completed", "superseded", "cancelled"}:
                existing.status = "pending"
                existing.attempts = 0
                existing.run_after = datetime.now(UTC)
                existing.error_message = None
                existing.completed_at = None
            session.flush()
            return int(existing.id)
        row = CleanupOutbox(
            repo_id=repo_id,
            run_id=run_id,
            file_id=file_id,
            document_version_id=document_version_id,
            target_type=target_type,
            target_id=target_id,
            dataset_id=dataset_id,
            action="delete",
            payload=dict(payload or {}),
            fence_token=fence_token,
        )
        session.add(row)
        session.flush()
        return int(row.id)

    def process_cleanup_outbox(
        self,
        *,
        repo_id: str,
        lease: RepoLeaseHandle | None = None,
        limit: int = 100,
    ) -> int:
        if lease is None:
            self.assert_library_runnable(repo_id)
            active = current_repo_lease(repo_id)
            if active is None:
                with self._mutation_scope(
                    repo_id,
                    owner_id=f"cleanup:{new_sync_id(repo_id)}",
                ) as acquired:
                    return self.process_cleanup_outbox(
                        repo_id=repo_id,
                        lease=acquired,
                        limit=limit,
                    )
            lease = active
        now = datetime.now(UTC)
        with self.session_factory() as session:
            row_ids = list(
                session.scalars(
                    select(CleanupOutbox.id)
                    .where(CleanupOutbox.repo_id == repo_id)
                    .where(CleanupOutbox.status.in_(["pending", "retrying"]))
                    .where(CleanupOutbox.run_after <= now)
                    .order_by(CleanupOutbox.id)
                    .limit(limit)
                ).all()
            )
        completed = 0
        for row_id in row_ids:
            self._raise_if_job_interrupted("cleanup outbox interrupted")
            control = self.admin_control_store.library(repo_id)
            if not control.runnable:
                self.log.info(
                    "cleanup.outbox_controlled",
                    repo_id=repo_id,
                    state=control.state,
                )
                break
            friendly_rename: tuple[str, str, str, str, str | None] | None = None
            with self.session_factory() as session:
                row = session.get(CleanupOutbox, row_id)
                if row is None or row.status not in {"pending", "retrying"}:
                    continue
                wait_for_document_id = str(
                    (row.payload or {}).get("wait_for_document_id") or ""
                )
                if wait_for_document_id:
                    waiting_version = session.scalar(
                        select(FileDocumentVersion)
                        .where(FileDocumentVersion.document_id == wait_for_document_id)
                    )
                    ready = bool(waiting_version and waiting_version.state == "current")
                    if waiting_version is not None and not ready:
                        ready = bool(
                            session.scalar(
                                select(FileDocumentVersion.id)
                                .where(
                                    FileDocumentVersion.file_id == waiting_version.file_id
                                )
                                .where(FileDocumentVersion.state == "current")
                            )
                        )
                    if not ready:
                        continue
                target_type = row.target_type
                target_id = row.target_id
                dataset_id = row.dataset_id
                payload = dict(row.payload or {})
                file_id = row.file_id
                document_version_id = row.document_version_id
                if file_id is None and document_version_id is not None:
                    cleaned_version = session.get(
                        FileDocumentVersion, document_version_id
                    )
                    if cleaned_version is not None:
                        file_id = cleaned_version.file_id
                if target_type == "ragflow_document" and dataset_id and file_id:
                    current_version = session.scalar(
                        select(FileDocumentVersion)
                        .where(FileDocumentVersion.file_id == file_id)
                        .where(FileDocumentVersion.state == "current")
                        .where(FileDocumentVersion.document_id.is_not(None))
                        .where(FileDocumentVersion.document_id != target_id)
                        .order_by(FileDocumentVersion.id.desc())
                    )
                    if current_version is not None and current_version.document_id:
                        current_file = session.get(File, file_id)
                        friendly_rename = (
                            dataset_id,
                            current_version.document_id,
                            current_version.document_name,
                            (
                                current_file.normalized_path
                                if current_file is not None
                                else current_version.normalized_path
                            ),
                            row.run_id,
                        )
            try:
                self.repo_lease_store.assert_owned(lease)
                self._raise_if_job_interrupted("cleanup outbox interrupted")
                control = self.admin_control_store.library(repo_id)
                if not control.runnable:
                    self.log.info(
                        "cleanup.outbox_controlled",
                        repo_id=repo_id,
                        state=control.state,
                    )
                    break
                if target_type == "ragflow_document":
                    if not dataset_id:
                        raise ValueError("document cleanup requires dataset_id")
                    if friendly_rename is not None and not self._ragflow_document_id_exists(
                        dataset_id,
                        friendly_rename[1],
                    ):
                        raise RuntimeError(
                            "replacement RAGFlow document is missing before cleanup"
                        )
                    self.ragflow_client.delete_documents(dataset_id, [target_id])
                    if friendly_rename is not None:
                        (
                            rename_dataset_id,
                            rename_document_id,
                            rename_document_name,
                            rename_path,
                            rename_sync_id,
                        ) = friendly_rename
                        self._raise_if_job_interrupted(
                            "cleanup replacement rename interrupted"
                        )
                        self._restore_friendly_document_name(
                            rename_dataset_id,
                            rename_document_id,
                            rename_document_name,
                            sync_id=rename_sync_id,
                            repo_id=repo_id,
                            path=rename_path,
                        )
                        if not self._ragflow_document_id_exists(
                            rename_dataset_id,
                            rename_document_id,
                        ):
                            raise RuntimeError(
                                "replacement RAGFlow document is missing after cleanup"
                            )
                elif target_type == "ragflow_dataset":
                    self.ragflow_client.delete_datasets([target_id])
                else:
                    raise ValueError(f"unsupported cleanup target type: {target_type}")
            except SyncCancelledError:
                raise
            except Exception as exc:
                with self.session_factory() as session:
                    row = session.scalar(
                        select(CleanupOutbox)
                        .where(CleanupOutbox.id == row_id)
                        .where(CleanupOutbox.status.in_(["pending", "retrying"]))
                        .with_for_update()
                    )
                    if row is not None:
                        row.attempts += 1
                        row.status = "dead" if row.attempts >= 5 else "retrying"
                        delay = min(600, 30 * (2 ** max(0, row.attempts - 1)))
                        row.run_after = datetime.now(UTC) + timedelta(seconds=delay)
                        row.error_message = str(exc)[:4000]
                        if row.target_type == "ragflow_dataset":
                            library = session.get(Library, row.repo_id)
                            if library is not None:
                                library.status = "delete_failed"
                                library.deletion_state = "delete_failed"
                                library.last_error = row.error_message
                        session.commit()
                self.job_store.refresh_workflow_parents_for_cleanup(int(row_id))
                self.log.warning(
                    "cleanup.outbox_failed",
                    repo_id=repo_id,
                    target_type=target_type,
                    target_id=target_id,
                    error_class=type(exc).__name__,
                )
                continue
            with self.session_factory() as session:
                row = session.scalar(
                    select(CleanupOutbox)
                    .where(CleanupOutbox.id == row_id)
                    .where(CleanupOutbox.status.in_(["pending", "retrying"]))
                    .with_for_update()
                )
                if row is None:
                    continue
                row.status = "completed"
                row.completed_at = datetime.now(UTC)
                row.error_message = None
                if document_version_id is not None:
                    version = session.get(FileDocumentVersion, document_version_id)
                    if version is not None and version.state != "superseded":
                        version.state = "superseded"
                if file_id is not None:
                    db_file = session.get(File, file_id)
                    if db_file is not None and payload.get("delete_file_row"):
                        session.delete(db_file)
                    elif (
                        db_file is not None
                        and payload.get("clear_binding")
                        and db_file.ragflow_document_id == target_id
                    ):
                        db_file.ragflow_document_id = None
                        db_file.ragflow_document_name = None
                        db_file.ingested_document_name = None
                        db_file.ingested_mime = None
                        db_file.parse_status = None
                if target_type == "ragflow_dataset":
                    library = session.get(Library, repo_id)
                    if library is not None:
                        self._purge_deleted_library_state(session, library)
                session.commit()
                completed += 1
            self.job_store.refresh_workflow_parents_for_cleanup(int(row_id))
        self._refresh_waiting_sync_runs(repo_id)
        return completed

    def list_cleanup_outbox(
        self,
        *,
        repo_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[CleanupOutbox]:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.session_factory() as session:
            stmt = select(CleanupOutbox).order_by(CleanupOutbox.created_at.desc()).limit(limit)
            if repo_id is not None:
                stmt = stmt.where(CleanupOutbox.repo_id == repo_id)
            if statuses:
                stmt = stmt.where(CleanupOutbox.status.in_(statuses))
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)
            return rows

    def requeue_cleanup_outbox(self, outbox_id: int) -> str | None:
        with self.session_factory() as session:
            row = session.get(CleanupOutbox, outbox_id)
            if row is None or row.status != "dead":
                return None
            repo_id = row.repo_id
            self.assert_library_runnable(repo_id)
            library = session.get(Library, repo_id)
            if (
                row.target_type == "ragflow_dataset"
                and library is not None
                and library.deletion_state == "active"
            ):
                return None
            row.status = "pending"
            row.attempts = 0
            row.run_after = datetime.now(UTC)
            row.error_message = None
            row.completed_at = None
            library = session.get(Library, row.repo_id)
            if library is not None and row.target_type == "ragflow_dataset":
                library.status = "confirmed_for_deletion"
                library.deletion_state = "confirmed"
                library.last_error = None
            session.commit()
        self.job_store.refresh_workflow_parents_for_cleanup(outbox_id)
        return repo_id

    def retry_cleanup_outbox(self, outbox_id: int) -> bool:
        repo_id = self.requeue_cleanup_outbox(outbox_id)
        if repo_id is None:
            return False
        self.process_cleanup_outbox(repo_id=repo_id)
        self._refresh_waiting_sync_runs(repo_id)
        return True

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
        if db_library.deletion_state == "deleted":
            db_library.ragflow_dataset_id = None
            db_library.ragflow_dataset_name = None
        db_library.last_seen_at = datetime.now(UTC)
        for cleanup in session.scalars(
            select(CleanupOutbox)
            .where(CleanupOutbox.repo_id == library.repo_id)
            .where(CleanupOutbox.target_type == "ragflow_dataset")
            .where(CleanupOutbox.status.in_(["pending", "retrying", "dead"]))
        ):
            cleanup.status = "superseded"
            cleanup.completed_at = datetime.now(UTC)
            cleanup.error_message = "source library reappeared before dataset cleanup"
        db_library.missing_since = None
        db_library.last_missing_observation_at = None
        db_library.missing_observations = 0
        db_library.deletion_state = "active"
        db_library.status = "active"
        db_library.last_error = None
        return db_library

    @staticmethod
    def _protect_controlled_library_target(
        session: Session,
        library: Library,
        *,
        now: datetime,
    ) -> None:
        for cleanup in session.scalars(
            select(CleanupOutbox)
            .where(CleanupOutbox.repo_id == library.repo_id)
            .where(CleanupOutbox.target_type == "ragflow_dataset")
            .where(CleanupOutbox.status.in_(["pending", "retrying", "dead"]))
        ):
            cleanup.status = "superseded"
            cleanup.completed_at = now
            cleanup.error_message = "library target protected by admin control"
        library.missing_since = None
        library.last_missing_observation_at = None
        library.missing_observations = 0
        library.deletion_state = "active"
        library.status = "active"
        library.last_error = None

    def _cleanup_missing_libraries(
        self,
        current_repo_ids: set[str],
        *,
        trigger: str = "manual",
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            missing_repo_ids = list(
                session.scalars(
                    select(Library.repo_id)
                    .where(Library.repo_id.not_in(current_repo_ids))
                    .where(Library.status != "deleted")
                ).all()
            )
        controls = self.admin_control_store.libraries(missing_repo_ids)
        with self.session_factory() as session:
            missing = session.scalars(
                select(Library)
                .where(Library.repo_id.not_in(current_repo_ids))
                .where(Library.status != "deleted")
            ).all()
            total_known = session.scalar(
                select(func.count(Library.repo_id)).where(Library.status != "deleted")
            )
            cleanup_statuses: dict[str, str] = {}
            for cleanup_repo_id, cleanup_status in session.execute(
                select(CleanupOutbox.repo_id, CleanupOutbox.status)
                .where(CleanupOutbox.target_type == "ragflow_dataset")
                .where(CleanupOutbox.status.in_(["pending", "retrying", "dead"]))
            ):
                repo_key = str(cleanup_repo_id)
                if cleanup_status == "dead" or repo_key not in cleanup_statuses:
                    cleanup_statuses[repo_key] = str(cleanup_status)
            actionable_missing: list[Library] = []
            for row in missing:
                control = controls.get(row.repo_id)
                if control is None or not control.runnable:
                    self._protect_controlled_library_target(session, row, now=now)
                    self.log.info(
                        "library.missing_cleanup_controlled",
                        repo_id=row.repo_id,
                        state=control.state if control is not None else "unavailable",
                    )
                    continue
                actionable_missing.append(row)
                row.missing_since = row.missing_since or now
                last_observed = row.last_missing_observation_at
                if last_observed is None or _as_utc(last_observed) <= (
                    now - MISSING_OBSERVATION_MIN_INTERVAL
                ):
                    row.missing_observations += 1
                    row.last_missing_observation_at = now
                cleanup_status = cleanup_statuses.get(row.repo_id)
                if cleanup_status:
                    if cleanup_status == "dead":
                        row.deletion_state = "delete_failed"
                        row.status = "delete_failed"
                    else:
                        row.deletion_state = "confirmed"
                        row.status = "confirmed_for_deletion"
                    continue
                if row.deletion_state in {"confirmed", "delete_failed"}:
                    continue
                if row.deletion_state != "awaiting_confirmation":
                    row.deletion_state = "missing"
                    row.status = "missing"
            mass_guard = (
                len(actionable_missing) >= 3
                and bool(total_known)
                and len(actionable_missing) / int(total_known or 1) > 0.20
            )
            eligible = [
                row
                for row in actionable_missing
                if row.missing_observations >= 3
                and row.missing_since is not None
                and _as_utc(row.missing_since) <= now - timedelta(hours=24)
                and row.deletion_state == "missing"
            ]
            if mass_guard:
                for row in eligible:
                    row.deletion_state = "awaiting_confirmation"
                    row.status = "awaiting_confirmation"
            items = [
                {
                    "repo_id": row.repo_id,
                    "name": row.name,
                    "dataset_id": row.ragflow_dataset_id,
                }
                for row in eligible
                if not mass_guard
            ]
            session.commit()

        for item in items:
            self._raise_if_automatic_cycle_interrupted(
                trigger,
                "automatic missing-library cleanup interrupted",
            )
            repo_id = str(item["repo_id"])
            dataset_id = str(item["dataset_id"] or "")
            try:
                control = self.admin_control_store.library(repo_id)
                if not control.runnable:
                    with self.session_factory() as session:
                        db_library = session.get(Library, repo_id)
                        if db_library is not None and db_library.status != "deleted":
                            self._protect_controlled_library_target(
                                session,
                                db_library,
                                now=datetime.now(UTC),
                            )
                            session.commit()
                    continue
                self.log.info(
                    "library.deleted_detected",
                    repo_id=repo_id,
                    name=item["name"],
                    dataset_id=dataset_id or None,
                )
                if dataset_id and self.delete_dataset_when_library_deleted:
                    with self._mutation_scope(
                        repo_id,
                        owner_id=f"library-cleanup:{new_sync_id(repo_id)}",
                    ) as lease:
                        self._enqueue_cleanup(
                            repo_id=repo_id,
                            target_type="ragflow_dataset",
                            target_id=dataset_id,
                            dataset_id=dataset_id,
                            fence_token=lease.fence_token,
                        )
                        self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
                else:
                    with self.session_factory() as session:
                        db_library = session.get(Library, repo_id)
                        if db_library:
                            self._purge_deleted_library_state(session, db_library)
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

    def confirm_missing_library_deletion(self, repo_id: str) -> bool:
        control = self.admin_control_store.library(repo_id)
        if not control.runnable:
            self.log.info(
                "library.delete_confirmation_controlled",
                repo_id=repo_id,
                state=control.state,
            )
            return False
        with self.session_factory() as session:
            library = session.get(Library, repo_id)
            if library is None or library.deletion_state != "awaiting_confirmation":
                return False
            dataset_id = library.ragflow_dataset_id
            library.deletion_state = "confirmed"
            library.status = "confirmed_for_deletion"
            session.commit()
        if dataset_id and self.delete_dataset_when_library_deleted:
            with self._mutation_scope(
                repo_id,
                owner_id=f"library-confirm:{new_sync_id(repo_id)}",
            ) as lease:
                self._enqueue_cleanup(
                    repo_id=repo_id,
                    target_type="ragflow_dataset",
                    target_id=dataset_id,
                    dataset_id=dataset_id,
                    fence_token=lease.fence_token,
                )
                completed = self.process_cleanup_outbox(repo_id=repo_id, lease=lease)
            if completed == 0 and not self.admin_control_store.library(repo_id).runnable:
                with self.session_factory() as session:
                    library = session.get(Library, repo_id)
                    if library is not None and library.status != "deleted":
                        self._protect_controlled_library_target(
                            session,
                            library,
                            now=datetime.now(UTC),
                        )
                        session.commit()
                return False
        else:
            control = self.admin_control_store.library(repo_id)
            if not control.runnable:
                with self.session_factory() as session:
                    library = session.get(Library, repo_id)
                    if library is not None and library.status != "deleted":
                        self._protect_controlled_library_target(
                            session,
                            library,
                            now=datetime.now(UTC),
                        )
                        session.commit()
                return False
            with self.session_factory() as session:
                library = session.get(Library, repo_id)
                if library is not None:
                    self._purge_deleted_library_state(session, library)
                    session.commit()
        return True

    def _purge_deleted_library_state(
        self,
        session: Session,
        library: Library,
    ) -> None:
        repo_id = library.repo_id
        library.status = "deleted"
        library.deletion_state = "deleted"
        library.last_error = None
        library.last_synced_commit_id = None
        for db_file in session.scalars(select(File).where(File.repo_id == repo_id)):
            session.delete(db_file)
        snapshot_ids = list(
            session.scalars(
                select(SourceSnapshot.id).where(SourceSnapshot.repo_id == repo_id)
            ).all()
        )
        session.execute(delete(SyncCursor).where(SyncCursor.repo_id == repo_id))
        if snapshot_ids:
            session.execute(
                delete(SourceSnapshotEntry).where(
                    SourceSnapshotEntry.snapshot_id.in_(snapshot_ids)
                )
            )
            session.execute(delete(SourceSnapshot).where(SourceSnapshot.id.in_(snapshot_ids)))

    def _upsert_file_row(
        self,
        session: Session,
        *,
        repo_id: str,
        path: str,
        item: dict[str, Any] | None,
        classification: Any,
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
        for version in session.scalars(
            select(FileDocumentVersion).where(FileDocumentVersion.repo_id == repo_id)
        ):
            if version.dataset_id == previous_dataset_id and version.state == "current":
                version.state = "superseded"
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
        terminal: bool = True,
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
                terminal=terminal,
            )
        except Exception as exc:
            self.log.warning("dashboard.sync_run_finish_failed", error=str(exc), sync_id=sync_id)

    def _update_dashboard_async_status(
        self,
        sync_id: str,
        *,
        status: str,
        progress: Mapping[str, Any],
        terminal: bool,
        error_message: str | None = None,
    ) -> None:
        if self.dashboard_store is None:
            return
        if status == "running":
            summary = "Synchronisation wartet auf Verarbeitung in RAGFlow"
        elif status == "failed":
            reason = error_message or "asynchrone Verarbeitung"
            summary = f"Synchronisation fehlgeschlagen: {reason}"
        else:
            summary = "Synchronisation vollständig abgeschlossen"
        try:
            self.dashboard_store.update_sync_run_status(
                sync_id=sync_id,
                status=status,
                terminal=terminal,
                summary=summary,
                details={"async_work": dict(progress)},
                errors_count=(1 if status == "failed" else None),
            )
        except Exception as exc:
            self.log.warning(
                "dashboard.sync_run_status_update_failed",
                error=str(exc),
                sync_id=sync_id,
            )

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

    def _ragflow_document_exists(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
    ) -> bool:
        documents = self.ragflow_client.iter_documents(
            dataset_id,
            keywords=_document_search_keyword(document_name),
        )
        return any(_document_id(document) == document_id for document in documents)

    def _ragflow_document_id_exists(self, dataset_id: str, document_id: str) -> bool:
        return any(
            _document_id(document) == document_id
            for document in self.ragflow_client.iter_documents(dataset_id)
        )

    def _recover_managed_upload(
        self,
        dataset_id: str,
        *,
        managed_document_name: str,
        upload_operation_id: str,
    ) -> dict[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for document in self.ragflow_client.iter_documents(
            dataset_id,
            keywords=upload_operation_id,
        ):
            if _remote_document_name(document) != managed_document_name:
                continue
            metadata = document.get("metadata") or document.get("meta_fields") or {}
            if isinstance(metadata, Mapping):
                remote_operation_id = str(
                    metadata.get("connector_upload_operation_id") or ""
                ).strip()
                if remote_operation_id and remote_operation_id != upload_operation_id:
                    continue
            matches.append(dict(document))
        if len(matches) > 1:
            raise RuntimeError(
                "multiple RAGFlow documents match one connector upload operation"
            )
        if matches:
            self.log.info(
                "ragflow.document_upload_recovered",
                dataset_id=dataset_id,
                document_id=_document_id(matches[0]),
                upload_operation_id=upload_operation_id,
            )
            return matches[0]
        return None

    def _update_managed_document_metadata(
        self,
        dataset_id: str,
        document_id: str,
        metadata: dict[str, str],
        *,
        sync_id: str | None,
        repo_id: str,
        path: str,
    ) -> None:
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

    def _restore_friendly_document_name(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
        *,
        sync_id: str | None,
        repo_id: str,
        path: str,
    ) -> None:
        rename_document = getattr(self.ragflow_client, "rename_document", None)
        if not callable(rename_document):
            return
        try:
            rename_document(dataset_id, document_id, document_name)
        except ApiError as exc:
            if exc.status_code not in {400, 404, 405, 501} and not (
                _is_ragflow_duplicate_document_name_error(exc)
            ):
                raise
            self.log.warning(
                "ragflow.document_rename_unsupported",
                sync_id=sync_id,
                repo_id=repo_id,
                dataset_id=dataset_id,
                path=path,
                document_id=document_id,
                status_code=exc.status_code,
            )


def _is_ragflow_duplicate_document_name_error(exc: ApiError) -> bool:
    if exc.status_code != 200 or not isinstance(exc.payload, Mapping):
        return False
    code = exc.payload.get("code")
    message = str(exc.payload.get("message") or exc.payload.get("msg") or "")
    normalized_message = message.strip().casefold().removesuffix(".")
    return (
        code in {102, "102"}
        and normalized_message == "duplicated document name in the same dataset"
    )


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


def _seafile_object_id(item: Mapping[str, Any]) -> str | None:
    value = str(item.get("id") or item.get("obj_id") or "").strip()
    return value or None


def _is_incompatible_snapshot_client_error(exc: TypeError) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "positional argument",
            "unexpected keyword argument",
            "required positional argument",
        )
    )


def _document_id(document: dict[str, Any]) -> str | None:
    value = document.get("id") or document.get("document_id")
    return str(value) if value else None


def _remote_document_name(document: Mapping[str, Any]) -> str:
    return str(
        document.get("name")
        or document.get("document_name")
        or document.get("doc_name")
        or ""
    )


def _managed_upload_document_name(document_name: str, operation_id: str) -> str:
    stem, suffix = _split_document_name(document_name)
    # Keep the marker and extension intact even for unusually long source names.
    bounded_stem = stem[:160] or "document"
    return f"{bounded_stem}.__connector_{operation_id}{suffix}"


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


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
