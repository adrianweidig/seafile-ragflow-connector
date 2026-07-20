from __future__ import annotations

import unittest
from contextlib import suppress
from datetime import UTC, datetime, timedelta

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from seafile_ragflow_connector.clients.http import ApiError
    from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
    from seafile_ragflow_connector.domain.file_classification import FilePolicy
    from seafile_ragflow_connector.jobs.context import activate_job_pause
    from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
    from seafile_ragflow_connector.jobs.worker import WorkerRunner
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.file import File
    from seafile_ragflow_connector.persistence.models.job import SyncJob
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.persistence.models.sync_state import (
        CleanupOutbox,
        FileDocumentVersion,
        SyncRun,
    )
    from seafile_ragflow_connector.persistence.sync_state import RepoLeaseBusyError
    from seafile_ragflow_connector.sync.orchestrator import (
        FileSyncResult,
        ParseDeadError,
        ParsePendingError,
        SyncCancelledError,
        SyncOrchestrator,
        _is_ragflow_duplicate_document_name_error,
    )
    from seafile_ragflow_connector.utils.hashing import sha256_bytes
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
    create_engine = None  # type: ignore[assignment]


class _FakeSeafileSyncClient:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.items = [{"name": "report.pdf", "type": "file"}]

    def download_file(self, repo_id: str, path: str) -> bytes:
        return self.content

    def list_dir(self, repo_id: str, path: str):
        return self.items if path == "/" else []


class _FailingSeafileSyncClient(_FakeSeafileSyncClient):
    def list_dir(self, repo_id: str, path: str):
        raise RuntimeError("HTTP 403")


class _SnapshotSeafileSyncClient(_FakeSeafileSyncClient):
    def __init__(self) -> None:
        super().__init__(b"%PDF-1.4\ncontent")
        self.snapshots = {
            "c1": {
                "/": [{"name": "a.pdf", "type": "file", "id": "obj-a", "size": 10}]
            },
            "c2": {
                "/": [
                    {"name": "a.pdf", "type": "file", "id": "obj-a", "size": 10},
                    {"name": "b.pdf", "type": "file", "id": "obj-b", "size": 11},
                ]
            },
        }
        self.revision_downloads: list[tuple[str, str]] = []

    def list_dir_at_commit(self, repo_id: str, commit_id: str, path: str = "/"):
        return list(self.snapshots[commit_id].get(path, []))

    def download_file_revision(self, repo_id: str, path: str, commit_id: str) -> bytes:
        self.revision_downloads.append((commit_id, path))
        return f"%PDF-1.4\n{commit_id}:{path}".encode()


class _CancellingSeafileSyncClient(_FakeSeafileSyncClient):
    def __init__(self) -> None:
        super().__init__(b"%PDF-1.4\ncontent")
        self.items = [
            {"name": "a.pdf", "type": "file"},
            {"name": "b.pdf", "type": "file"},
        ]
        self.cancel: object | None = None

    def download_file(self, repo_id: str, path: str) -> bytes:
        if callable(self.cancel):
            self.cancel()
            self.cancel = None
        return super().download_file(repo_id, path)


class _FakeSeafileAdminClient:
    def __init__(self, libraries: list[dict[str, object]] | None = None) -> None:
        self.libraries = libraries or []
        self.iter_calls = 0

    def iter_libraries(self):
        self.iter_calls += 1
        return iter(self.libraries)


class _FakeRAGFlowClient:
    def __init__(self) -> None:
        self.documents = [
            {"id": "stale-exact", "name": "report.pdf"},
            {"id": "stale-copy", "name": "report (1).pdf"},
            {"id": "unrelated", "name": "other.pdf"},
        ]
        self.deleted_ids: list[list[str]] = []
        self.deleted_dataset_ids: list[list[str]] = []
        self.created_datasets: list[dict[str, object]] = []
        self.updated_datasets: list[tuple[str, dict[str, object]]] = []
        self.metadata_updates: list[tuple[str, str, dict[str, object]]] = []
        self.parsed_ids: list[list[str]] = []
        self.operations: list[str] = []
        self.parse_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.upload_document_id = "new-doc"
        self.dataset_id = "dataset"
        self.generated_dataset_exists = True
        self.generated_dataset_name = "Dataset"
        self.generated_dataset_permission = "me"
        self.template_exists = True
        self.datasets_by_id: dict[str, dict[str, object]] = {}

    def list_documents(
        self,
        dataset_id: str,
        *,
        keywords: str | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, str]]:
        self.last_keywords = keywords
        self.last_page_size = page_size
        return self.documents

    def iter_documents(
        self,
        dataset_id: str,
        *,
        run: str | None = None,
        keywords: str | None = None,
        page_size: int = 100,
    ):
        _ = run
        return iter(
            self.list_documents(
                dataset_id,
                keywords=keywords,
                page_size=page_size,
            )
        )

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None):
        if name == "connector_template":
            if self.template_exists:
                return [{"id": "template", "name": "connector_template"}]
            return []
        if self.generated_dataset_exists:
            self.generated_dataset_name = name or self.generated_dataset_name
            return [
                {
                    "id": self.dataset_id,
                    "name": self.generated_dataset_name,
                    "permission": self.generated_dataset_permission,
                }
            ]
        return []

    def get_dataset(self, dataset_id: str) -> dict[str, object]:
        if dataset_id in self.datasets_by_id:
            return self.datasets_by_id[dataset_id]
        raise ApiError("dataset not found", status_code=404)

    def create_dataset(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_datasets.append(payload)
        if payload.get("name") == "connector_template":
            self.template_exists = True
            return {"id": "template-created", **payload}
        self.generated_dataset_exists = True
        self.generated_dataset_name = str(payload.get("name") or self.generated_dataset_name)
        self.generated_dataset_permission = str(
            payload.get("permission") or self.generated_dataset_permission
        )
        return {"id": self.dataset_id, **payload}

    def update_dataset(
        self,
        dataset_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.updated_datasets.append((dataset_id, payload))
        if dataset_id == "template":
            return {"id": dataset_id, "name": "connector_template", **payload}
        self.generated_dataset_permission = str(
            payload.get("permission") or self.generated_dataset_permission
        )
        return {
            "id": dataset_id,
            "name": self.generated_dataset_name,
            "permission": self.generated_dataset_permission,
            **payload,
        }

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.operations.append("delete")
        self.deleted_ids.append(document_ids)
        if self.delete_error is not None:
            raise self.delete_error
        self.documents = [
            document
            for document in self.documents
            if str(document.get("id") or document.get("document_id")) not in document_ids
        ]

    def delete_datasets(self, dataset_ids: list[str]) -> None:
        self.deleted_dataset_ids.append(dataset_ids)

    def upload_document(
        self,
        dataset_id: str,
        *,
        document_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, str]:
        self.operations.append("upload")
        self.uploaded_name = document_name
        self.documents.append(
            {"id": self.upload_document_id, "name": document_name, "run": "UNSTART"}
        )
        return {"id": self.upload_document_id}

    def update_document_metadata(
        self,
        dataset_id: str,
        document_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.operations.append("metadata")
        self.metadata_updates.append((dataset_id, document_id, metadata))
        return {"ok": True}

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.operations.append("parse")
        self.parsed_ids.append(document_ids)
        if self.parse_error is not None:
            raise self.parse_error


class _RenamingRAGFlowClient(_FakeRAGFlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.renamed_documents: list[tuple[str, str, str]] = []

    def rename_document(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
    ) -> dict[str, str]:
        self.operations.append("rename")
        self.renamed_documents.append((dataset_id, document_id, document_name))
        for document in self.documents:
            if document.get("id") == document_id:
                document["name"] = document_name
        return {"id": document_id, "name": document_name}


class _DuplicateNameRenamingRAGFlowClient(_RenamingRAGFlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.rename_attempts: list[tuple[str, str, str]] = []
        self.rename_error_status = 200
        self.rename_error_code: int | str = 102
        self.rename_error_message = "Duplicated document name in the same dataset."

    def rename_document(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
    ) -> dict[str, str]:
        self.rename_attempts.append((dataset_id, document_id, document_name))
        if any(
            document.get("id") != document_id and document.get("name") == document_name
            for document in self.documents
        ):
            self.operations.append("rename")
            raise ApiError(
                "API returned an error code",
                status_code=self.rename_error_status,
                payload={
                    "code": self.rename_error_code,
                    "message": self.rename_error_message,
                },
            )
        return super().rename_document(dataset_id, document_id, document_name)


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine("sqlite:///:memory:")
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _replacement_cleanup_fixture(
    test_case: unittest.TestCase,
    *,
    payload: dict[str, object] | None = None,
):
    session_factory = _session_factory(test_case)
    with session_factory() as session:
        session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
        db_file = File(
            repo_id="repo",
            path="/docs/report.pdf",
            normalized_path="/docs/report.pdf",
            source_content_sha256="new-source",
            ingested_content_sha256="new-ingested",
            ragflow_document_id="new-doc",
            ragflow_document_name="report.pdf",
            sync_status="synced",
            parse_status="DONE",
        )
        session.add(db_file)
        session.flush()
        old_version = FileDocumentVersion(
            file_id=db_file.id,
            repo_id="repo",
            normalized_path=db_file.normalized_path,
            dataset_id="dataset",
            document_id="old-doc",
            document_name="report.pdf",
            state="superseded",
            parse_status="DONE",
        )
        current_version = FileDocumentVersion(
            file_id=db_file.id,
            repo_id="repo",
            normalized_path=db_file.normalized_path,
            dataset_id="dataset",
            document_id="new-doc",
            document_name="report.pdf",
            source_content_sha256="new-source",
            ingested_content_sha256="new-ingested",
            state="current",
            parse_status="DONE",
        )
        session.add_all([old_version, current_version])
        session.flush()
        session.add(
            CleanupOutbox(
                repo_id="repo",
                file_id=db_file.id,
                document_version_id=old_version.id,
                target_type="ragflow_document",
                target_id="old-doc",
                dataset_id="dataset",
                action="delete",
                payload=dict(payload or {}),
                status="pending",
            )
        )
        session.commit()
        return session_factory, int(old_version.id)


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class OrchestratorUploadTests(unittest.TestCase):
    def test_automatic_discovery_stops_before_seafile_when_deactivated(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                )
            )
            session.commit()
        admin_client = _FakeSeafileAdminClient([])
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=admin_client,  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_workflow(
            updated_by="test",
            automation_enabled=False,
        )

        self.assertEqual(orchestrator.discover_job_specs(), [])
        self.assertEqual(admin_client.iter_calls, 0)
        with session_factory() as session:
            library = session.get(Library, "repo")
            assert library is not None
            self.assertEqual(library.status, "active")

    def test_automatic_discovery_stops_before_seafile_when_queue_is_paused(self) -> None:
        session_factory = _session_factory(self)
        admin_client = _FakeSeafileAdminClient([{"id": "repo", "name": "Demo"}])
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=admin_client,  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_workflow(
            updated_by="test",
            queue_paused=True,
        )

        self.assertEqual(orchestrator.discover_job_specs(), [])
        self.assertEqual(admin_client.iter_calls, 0)

    def test_running_automatic_discovery_stops_before_next_library_when_paused(
        self,
    ) -> None:
        session_factory = _session_factory(self)
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(
                [
                    {"id": "repo-1", "name": "First"},
                    {"id": "repo-2", "name": "Second"},
                ]
            ),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        workflow = orchestrator.admin_control_store.workflow
        checks = 0

        def pause_after_first_library():
            nonlocal checks
            checks += 1
            if checks == 2:
                orchestrator.admin_control_store.update_workflow(
                    updated_by="test",
                    queue_paused=True,
                )
            return workflow()

        orchestrator.admin_control_store.workflow = pause_after_first_library  # type: ignore[method-assign]

        with self.assertRaisesRegex(SyncCancelledError, "library discovery"):
            orchestrator.discover_libraries(trigger="automatic")

        with session_factory() as session:
            self.assertIsNotNone(session.get(Library, "repo-1"))
            self.assertIsNone(session.get(Library, "repo-2"))
            self.assertEqual(session.query(SyncJob).count(), 0)

    def test_discovery_filters_controls_but_full_visibility_keeps_all_sources(self) -> None:
        session_factory = _session_factory(self)
        admin_client = _FakeSeafileAdminClient(
            [
                {"id": "active", "name": "Active"},
                {"id": "paused", "name": "Paused"},
                {"id": "disabled", "name": "Disabled"},
                {"id": "encrypted", "name": "Encrypted", "encrypted": True},
            ]
        )
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=admin_client,  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_library(
            "paused",
            updated_by="test",
            paused=True,
        )
        orchestrator.admin_control_store.update_library(
            "disabled",
            updated_by="test",
            enabled=False,
        )

        discovered = orchestrator.discover_libraries()
        full_visibility = orchestrator.discover_libraries(full_visibility=True)
        specs = orchestrator.discover_job_specs()

        self.assertEqual([library.repo_id for library in discovered], ["active"])
        self.assertEqual(
            {library.repo_id for library in full_visibility},
            {"active", "paused", "disabled", "encrypted"},
        )
        self.assertEqual([spec.repo_id for spec in specs], ["active"])
        self.assertNotIn("trigger", specs[0].payload)
        self.assertEqual(
            specs[0].dedup_key(),
            JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="active").dedup_key(),
        )
        with session_factory() as session:
            self.assertEqual(session.get(Library, "paused").status, "active")
            self.assertEqual(session.get(Library, "disabled").status, "active")
            self.assertEqual(session.get(Library, "encrypted").status, "skipped:encrypted")

    def test_controlled_library_rejects_direct_mutating_work_before_run_creation(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_library(
            "repo",
            updated_by="test",
            paused=True,
        )

        for action in (
            lambda: orchestrator.sync_library_full("repo"),
            lambda: orchestrator.sync_library_delta("repo"),
            lambda: orchestrator.reconcile_library("repo", execute=True),
            lambda: orchestrator.ensure_dataset_for_repo("repo"),
        ):
            with self.assertRaisesRegex(ValueError, "paused"):
                action()

        with session_factory() as session:
            self.assertEqual(session.query(SyncRun).count(), 0)
        self.assertEqual(ragflow_client.operations, [])
        self.assertEqual(ragflow_client.created_datasets, [])

    def test_deactivated_automation_does_not_block_manual_full_sync(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset",
                    ragflow_dataset_name="Demo",
                )
            )
            session.commit()
        sync_client = _FakeSeafileSyncClient(b"content")
        sync_client.items = []
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.datasets_by_id["dataset"] = {"id": "dataset", "name": "Demo"}
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_workflow(
            updated_by="test",
            automation_enabled=False,
        )

        summary = orchestrator.sync_library_full("repo")

        self.assertEqual(summary.libraries_synced, 1)
        with session_factory() as session:
            run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertEqual(run.status, "succeeded")
            self.assertEqual(run.progress["phase"], "completed")

    def test_full_sync_persists_monotonic_per_file_progress(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset",
                    ragflow_dataset_name="Demo",
                )
            )
            session.commit()
        sync_client = _FakeSeafileSyncClient(b"content")
        sync_client.items = [
            {"name": "a.pdf", "type": "file"},
            {"name": "b.pdf", "type": "file"},
        ]
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.datasets_by_id["dataset"] = {"id": "dataset", "name": "Demo"}
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.sync_file = lambda *_args, **_kwargs: FileSyncResult(  # type: ignore[method-assign]
            uploaded=False,
            skipped=True,
            document_id=None,
            change_type="unchanged",
        )
        snapshots: list[dict[str, object]] = []
        update_run = orchestrator.sync_state_store.update_run

        def recording_update(run_id: str, **kwargs: object) -> bool:
            progress = kwargs.get("progress")
            if isinstance(progress, dict):
                snapshots.append(dict(progress))
            return update_run(run_id, **kwargs)  # type: ignore[arg-type]

        orchestrator.sync_state_store.update_run = recording_update  # type: ignore[method-assign]

        orchestrator.sync_library_full("repo")

        syncing = [item for item in snapshots if item.get("phase") == "syncing"]
        self.assertEqual(
            [item["files_processed"] for item in syncing],
            [0, 1, 2],
        )
        self.assertEqual([item["files_total"] for item in syncing], [2, 2, 2])
        self.assertEqual([item["percent"] for item in syncing], [0.0, 50.0, 100.0])
        with session_factory() as session:
            run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertEqual(run.status, "succeeded")
            self.assertEqual(run.progress["phase"], "completed")
            self.assertEqual(run.progress["files_processed"], 2)
            self.assertEqual(run.progress["files_total"], 2)
            self.assertEqual(run.progress["percent"], 100.0)

    def test_full_sync_failure_preserves_progress_and_marks_failed_phase(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset",
                    ragflow_dataset_name="Demo",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.datasets_by_id["dataset"] = {"id": "dataset", "name": "Demo"}
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FailingSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            orchestrator.sync_library_full("repo")

        with session_factory() as session:
            run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.progress["phase"], "failed")
            self.assertEqual(run.progress["failed_phase"], "preparing")
            self.assertEqual(run.progress["completed"], 0)
            self.assertEqual(run.progress["total"], 0)
            self.assertEqual(run.progress["percent"], 0.0)

    def test_reconcile_plan_requires_fresh_repository_lease(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset",
                )
            )
            session.commit()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        held = orchestrator.repo_lease_store.acquire("repo", "other-worker")
        try:
            with self.assertRaises(RepoLeaseBusyError):
                orchestrator.plan_library_reconcile("repo")
        finally:
            orchestrator.repo_lease_store.release(held)

    def test_worker_cancel_propagates_into_sync_run_and_stops_before_next_file(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        sync_client = _CancellingSeafileSyncClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,  # type: ignore[arg-type]
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        job_id = orchestrator.job_store.enqueue(
            JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo")
        )
        sync_client.cancel = lambda: orchestrator.job_store.request_cancel(job_id)
        worker = WorkerRunner(
            orchestrator.job_store,
            handlers={
                JobType.SYNC_LIBRARY_FULL: lambda _spec: orchestrator.sync_library_full(
                    "repo"
                )
            },
            worker_id="worker",
        )

        self.assertTrue(worker.run_once())

        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertIsNotNone(job)
            assert job is not None
            self.assertEqual(job.status, JobStatus.CANCELLED.value)
            self.assertEqual(run.status, "cancelled")
            self.assertEqual(session.query(FileDocumentVersion).count(), 0)

    def test_healthy_parse_polling_does_not_consume_failure_retry_budget(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.sync_file("repo", "dataset", "/a.pdf")

        for _index in range(10):
            with self.assertRaises(ParsePendingError):
                orchestrator.check_parse_status(
                    "repo",
                    "dataset",
                    raise_if_pending=True,
                )
        with session_factory() as session:
            version = session.query(FileDocumentVersion).one()
            self.assertEqual(version.state, "parsing")
            self.assertEqual(version.retry_count, 0)
            self.assertEqual(version.poll_count, 10)

    def test_real_parse_failures_dead_letter_after_fifth_retry(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.sync_file("repo", "dataset", "/a.pdf")
        for document in ragflow_client.documents:
            if document.get("id") == "new-doc":
                document["run"] = "FAIL"
                document["progress_msg"] = "parser failed"

        for _index in range(4):
            with self.assertRaises(ParsePendingError):
                orchestrator.check_parse_status(
                    "repo",
                    "dataset",
                    raise_if_pending=True,
                )
        with self.assertRaises(ParseDeadError):
            orchestrator.check_parse_status(
                "repo",
                "dataset",
                raise_if_pending=True,
            )

        with session_factory() as session:
            version = session.query(FileDocumentVersion).one()
            db_file = session.query(File).one()
            self.assertEqual(version.state, "dead")
            self.assertEqual(version.retry_count, 5)
            self.assertEqual(db_file.sync_status, "parse_failed")

    def test_dead_parse_version_can_be_reuploaded_and_polled_to_completion(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.sync_file("repo", "dataset", "/a.pdf")
        for document in ragflow_client.documents:
            if document.get("id") == "new-doc":
                document["run"] = "FAIL"
        for _index in range(5):
            with suppress(ParsePendingError, ParseDeadError):
                orchestrator.check_parse_status(
                    "repo",
                    "dataset",
                    raise_if_pending=True,
                )

        ragflow_client.upload_document_id = "repair-doc"
        repaired = orchestrator.sync_file("repo", "dataset", "/a.pdf")
        self.assertEqual(repaired.document_id, "repair-doc")
        with self.assertRaises(ParsePendingError):
            orchestrator.check_parse_status(
                "repo",
                "dataset",
                raise_if_pending=True,
            )
        for document in ragflow_client.documents:
            if document.get("id") == "repair-doc":
                document["run"] = "DONE"

        orchestrator.check_parse_status("repo", "dataset", raise_if_pending=True)

        with session_factory() as session:
            versions = session.query(FileDocumentVersion).order_by(
                FileDocumentVersion.id
            ).all()
            self.assertEqual([version.state for version in versions], ["superseded", "current"])
            self.assertEqual(session.query(File).one().ragflow_document_id, "repair-doc")

    def test_delta_uses_commit_snapshots_and_downloads_only_changed_objects(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    head_commit_id="c1",
                )
            )
            session.commit()
        sync_client = _SnapshotSeafileSyncClient()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,  # type: ignore[arg-type]
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        first = orchestrator.sync_library_full("repo")
        self.assertEqual(first.files_uploaded, 1)
        self.assertEqual(sync_client.revision_downloads, [("c1", "/a.pdf")])
        ragflow_client.documents = [{"id": "new-doc", "name": "a.pdf", "run": "DONE"}]
        orchestrator.check_parse_status("repo", "dataset")
        with session_factory() as session:
            library = session.get(Library, "repo")
            assert library is not None
            library.head_commit_id = "c2"
            session.commit()
        ragflow_client.upload_document_id = "new-doc-b"
        sync_client.revision_downloads.clear()

        second = orchestrator.sync_library_delta("repo")

        self.assertEqual(second.files_uploaded, 1)
        self.assertEqual(sync_client.revision_downloads, [("c2", "/b.pdf")])
        cursor = orchestrator.sync_state_store.get_cursor("repo")
        self.assertIsNotNone(cursor)
        assert cursor is not None
        self.assertEqual(cursor.commit_id, "c2")
        with session_factory() as session:
            run = session.query(SyncRun).filter_by(mode="delta").one()
            self.assertEqual(run.progress["phase"], "parsing")
            self.assertEqual(run.progress["changes"], 1)
            self.assertEqual(run.progress["processed"], 1)
            self.assertEqual(run.progress["completed"], 1)
            self.assertEqual(run.progress["total"], 1)
            self.assertEqual(run.progress["percent"], 100.0)

    def test_full_sync_rename_keeps_old_document_until_new_parse_is_current(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset",
                    ragflow_dataset_name="Demo",
                )
            )
            session.add(
                File(
                    repo_id="repo",
                    path="/old.pdf",
                    normalized_path="/old.pdf",
                    seafile_obj_id="same-object",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="old.pdf",
                    sync_status="synced",
                    parse_status="DONE",
                )
            )
            session.commit()
        sync_client = _FakeSeafileSyncClient(b"%PDF-1.4\ncontent")
        sync_client.items = [
            {"name": "renamed.pdf", "type": "file", "id": "same-object"}
        ]
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.datasets_by_id["dataset"] = {"id": "dataset", "name": "Demo"}
        dashboard_store = DashboardEventStore(session_factory, DashboardLimits())
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
            dashboard_store=dashboard_store,
        )
        observed_intermediate_statuses: list[str] = []
        complete_async_work = orchestrator._complete_or_wait_for_async_work

        def observe_before_async_completion(
            run_id: str,
            repo_id: str,
            progress: dict[str, object],
        ) -> str:
            dashboard_run = dashboard_store.get_sync_run(run_id)
            assert dashboard_run is not None
            observed_intermediate_statuses.append(str(dashboard_run["status"]))
            return complete_async_work(run_id, repo_id, progress)

        orchestrator._complete_or_wait_for_async_work = (  # type: ignore[method-assign]
            observe_before_async_completion
        )

        orchestrator.sync_library_full("repo")

        self.assertEqual(observed_intermediate_statuses, ["running"])
        with session_factory() as session:
            self.assertEqual(
                {row.normalized_path for row in session.query(File).all()},
                {"/old.pdf", "/renamed.pdf"},
            )
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "pending")
            self.assertEqual(cleanup.payload["wait_for_document_id"], "new-doc")
            sync_run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertEqual(sync_run.progress["phase"], "parsing")
            self.assertEqual(sync_run.progress["files_processed"], 1)
            self.assertEqual(sync_run.progress["files_total"], 1)
        self.assertEqual(ragflow_client.deleted_ids, [])
        run = dashboard_store.list_sync_runs(
            status=None,
            limit=10,
            offset=0,
        )["items"][0]
        self.assertEqual(run["status"], "running")
        self.assertIsNone(run["ended_at"])

        for document in ragflow_client.documents:
            if document.get("id") == "new-doc":
                document["run"] = "DONE"
        orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            renamed = session.query(File).one()
            self.assertEqual(renamed.normalized_path, "/renamed.pdf")
            self.assertEqual(renamed.ragflow_document_id, "new-doc")
            self.assertEqual(session.query(CleanupOutbox).one().status, "completed")
            sync_run = session.query(SyncRun).filter_by(mode="full").one()
            self.assertEqual(sync_run.status, "succeeded")
            self.assertEqual(sync_run.progress["phase"], "completed")
            self.assertEqual(sync_run.progress["files_processed"], 1)
            self.assertEqual(sync_run.progress["files_total"], 1)
        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        completed_run = dashboard_store.get_sync_run(str(run["sync_id"]))
        self.assertIsNotNone(completed_run)
        assert completed_run is not None
        self.assertEqual(completed_run["status"], "succeeded")
        self.assertIsNotNone(completed_run["ended_at"])

    def test_unchanged_delta_drains_due_cleanup_outbox(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    head_commit_id="c1",
                    ragflow_dataset_id="dataset",
                )
            )
            session.add(
                File(
                    repo_id="repo",
                    path="/old.pdf",
                    normalized_path="/old.pdf",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="old.pdf",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.delete_error = ApiError("temporarily unavailable", status_code=503)
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_SnapshotSeafileSyncClient(),  # type: ignore[arg-type]
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        snapshot = orchestrator.sync_state_store.replace_snapshot(
            repo_id="repo",
            commit_id="c1",
            scope="/",
            entries=[],
        )
        self.assertTrue(
            orchestrator.sync_state_store.advance_cursor(
                repo_id="repo",
                scope="/",
                expected_commit_id=None,
                target_commit_id="c1",
                snapshot_id=snapshot.snapshot_id,
            )
        )
        self.assertFalse(orchestrator.delete_file("repo", "dataset", "/old.pdf"))
        with session_factory() as session:
            outbox = session.query(CleanupOutbox).one()
            self.assertEqual(outbox.status, "retrying")
            outbox.run_after = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        ragflow_client.delete_error = None

        summary = orchestrator.sync_library_delta("repo")

        self.assertEqual(summary.files_uploaded, 0)
        with session_factory() as session:
            self.assertEqual(session.query(File).count(), 0)
            self.assertEqual(session.query(CleanupOutbox).one().status, "completed")

    def test_initial_upload_preserves_unowned_same_name_documents(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _RenamingRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        self.assertEqual(ragflow_client.deleted_ids, [])
        self.assertEqual(
            ragflow_client.operations,
            ["upload", "metadata", "rename", "parse"],
        )
        self.assertTrue(ragflow_client.uploaded_name.startswith("report.__connector_"))
        self.assertTrue(ragflow_client.uploaded_name.endswith(".pdf"))
        self.assertEqual(
            ragflow_client.renamed_documents,
            [("dataset", "new-doc", "report.pdf")],
        )
        self.assertEqual(ragflow_client.metadata_updates[0][0:2], ("dataset", "new-doc"))
        self.assertEqual(ragflow_client.metadata_updates[0][2]["repo_id"], "repo")
        self.assertEqual(ragflow_client.metadata_updates[0][2]["source_path"], "/docs/report.pdf")
        self.assertEqual(ragflow_client.metadata_updates[0][2]["document_name"], "report.pdf")
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])

    def test_update_waits_for_new_parse_then_retries_duplicate_name_rename(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256="old-source",
                    ingested_content_sha256="old-ingested",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                    parse_status="DONE",
                )
            )
            session.commit()

        ragflow_client = _DuplicateNameRenamingRAGFlowClient()
        ragflow_client.rename_error_message = (
            "  Duplicated document name in the same dataset.\n"
        )
        ragflow_client.documents = [{"id": "old-doc", "name": "report.pdf", "run": "DONE"}]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\nnew content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        self.assertEqual(
            ragflow_client.operations,
            ["upload", "metadata", "rename", "parse"],
        )
        self.assertEqual(ragflow_client.deleted_ids, [])
        replacement = next(
            document
            for document in ragflow_client.documents
            if document.get("id") == "new-doc"
        )
        self.assertEqual(replacement["name"], ragflow_client.uploaded_name)
        self.assertTrue(str(replacement["name"]).startswith("report.__connector_"))
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])
        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(db_file.sync_status, "parsing")
            self.assertEqual([version.state for version in versions], ["current", "parsing"])

        orchestrator.check_parse_status("repo", "dataset")

        self.assertEqual(ragflow_client.deleted_ids, [])
        with session_factory() as session:
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual([version.state for version in versions], ["current", "parsing"])

        for document in ragflow_client.documents:
            if document.get("id") == "new-doc":
                document["run"] = "DONE"
        orchestrator.check_parse_status("repo", "dataset")

        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        self.assertEqual(
            ragflow_client.rename_attempts,
            [
                ("dataset", "new-doc", "report.pdf"),
                ("dataset", "new-doc", "report.pdf"),
            ],
        )
        self.assertEqual(
            next(
                document["name"]
                for document in ragflow_client.documents
                if document.get("id") == "new-doc"
            ),
            "report.pdf",
        )
        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "new-doc")
            self.assertEqual(db_file.sync_status, "synced")
            self.assertEqual([version.state for version in versions], ["superseded", "current"])

    def test_update_does_not_suppress_unrelated_ragflow_rename_error(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256="old-source",
                    ingested_content_sha256="old-ingested",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                    parse_status="DONE",
                )
            )
            session.commit()

        ragflow_client = _DuplicateNameRenamingRAGFlowClient()
        ragflow_client.rename_error_message = "A different rename failure."
        ragflow_client.documents = [{"id": "old-doc", "name": "report.pdf", "run": "DONE"}]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\nnew content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with self.assertRaises(ApiError):
            orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(ragflow_client.operations, ["upload", "metadata", "rename"])
        self.assertEqual(ragflow_client.parsed_ids, [])
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")

    def test_duplicate_name_error_requires_exact_status_code_and_message(self) -> None:
        exact_payload = {
            "code": 102,
            "message": "Duplicated document name in the same dataset.",
        }
        self.assertTrue(
            _is_ragflow_duplicate_document_name_error(
                ApiError("duplicate", status_code=200, payload=exact_payload)
            )
        )

        variants = (
            ApiError("duplicate", status_code=201, payload=exact_payload),
            ApiError(
                "duplicate",
                status_code=200,
                payload={**exact_payload, "code": "102"},
            ),
            ApiError(
                "duplicate",
                status_code=200,
                payload={**exact_payload, "message": exact_payload["message"].lower()},
            ),
            ApiError(
                "duplicate",
                status_code=200,
                payload={"code": 102, "msg": exact_payload["message"]},
            ),
        )
        for error in variants:
            with self.subTest(status=error.status_code, payload=error.payload):
                self.assertFalse(_is_ragflow_duplicate_document_name_error(error))

    def test_initial_upload_does_not_defer_exact_duplicate_name_error(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()

        ragflow_client = _DuplicateNameRenamingRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with self.assertRaises(ApiError):
            orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(ragflow_client.operations, ["upload", "metadata", "rename"])
        self.assertEqual(ragflow_client.parsed_ids, [])

    def test_only_latest_of_two_pending_updates_can_be_promoted(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256="old-source",
                    ingested_content_sha256="old-ingested",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                    parse_status="DONE",
                )
            )
            session.commit()

        sync_client = _FakeSeafileSyncClient(b"%PDF-1.4\nversion two")
        ragflow_client = _DuplicateNameRenamingRAGFlowClient()
        ragflow_client.documents = [{"id": "old-doc", "name": "report.pdf", "run": "DONE"}]
        ragflow_client.upload_document_id = "version-two"
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")
        sync_client.content = b"%PDF-1.4\nversion three"
        ragflow_client.upload_document_id = "version-three"
        orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")
        for document in ragflow_client.documents:
            if document.get("id") == "version-two":
                document["run"] = "DONE"
            elif document.get("id") == "version-three":
                document["run"] = "RUNNING"
        ragflow_client.documents = list(reversed(ragflow_client.documents))

        orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(
                [version.state for version in versions],
                ["current", "superseded", "parsing"],
            )
        self.assertIn(["version-two"], ragflow_client.deleted_ids)
        self.assertNotIn(["version-three"], ragflow_client.deleted_ids)

        for document in ragflow_client.documents:
            if document.get("id") == "version-three":
                document["run"] = "DONE"
        orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "version-three")
            self.assertEqual(
                [version.state for version in versions],
                ["superseded", "superseded", "current"],
            )
        self.assertIn(["old-doc"], ragflow_client.deleted_ids)
        self.assertNotIn(["version-three"], ragflow_client.deleted_ids)

    def test_done_update_is_not_promoted_over_newer_pending_upload(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            db_file = File(
                repo_id="repo",
                path="/docs/report.pdf",
                normalized_path="/docs/report.pdf",
                source_content_sha256="old-source",
                ingested_content_sha256="old-ingested",
                ragflow_document_id="old-doc",
                ragflow_document_name="report.pdf",
                sync_status="parsing",
                parse_status="RUNNING",
            )
            session.add(db_file)
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="old-doc",
                        document_name="report.pdf",
                        state="current",
                        parse_status="DONE",
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="version-two",
                        document_name="report.pdf",
                        state="parsing",
                        parse_status="RUNNING",
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_name="report.pdf",
                        state="pending_upload",
                    ),
                ]
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "version-two", "name": "report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(
                [version.state for version in versions],
                ["current", "superseded", "pending_upload"],
            )
        self.assertIn(["version-two"], ragflow_client.deleted_ids)
        self.assertEqual(orchestrator._async_work_counts("repo")["pending_parse"], 0)

    def test_delete_file_cleans_current_and_pending_ragflow_documents(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            db_file = File(
                repo_id="repo",
                path="/docs/report.pdf",
                normalized_path="/docs/report.pdf",
                ragflow_document_id="current-doc",
                ragflow_document_name="report.pdf",
                sync_status="parsing",
                parse_status="DONE",
            )
            session.add(db_file)
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="current-doc",
                        document_name="report.pdf",
                        state="current",
                        parse_status="DONE",
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="pending-doc",
                        document_name="report.pdf",
                        state="parsing",
                        parse_status="RUNNING",
                    ),
                ]
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            {"id": "current-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "pending-doc", "name": "managed-report.pdf", "run": "RUNNING"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        deleted = orchestrator.delete_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(deleted)
        self.assertEqual(
            ragflow_client.deleted_ids,
            [["current-doc"], ["pending-doc"]],
        )
        with session_factory() as session:
            self.assertEqual(session.query(File).count(), 0)
            cleanup = session.query(CleanupOutbox).order_by(CleanupOutbox.id).all()
            self.assertEqual([row.status for row in cleanup], ["completed", "completed"])

    def test_stale_pending_version_older_than_current_is_not_resumed(self) -> None:
        session_factory = _session_factory(self)
        reverted_content = b"%PDF-1.4\nreverted content"
        reverted_hash = sha256_bytes(reverted_content)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            db_file = File(
                repo_id="repo",
                path="/docs/report.pdf",
                normalized_path="/docs/report.pdf",
                source_content_sha256="current-source",
                ingested_content_sha256="current-ingested",
                ragflow_document_id="current-doc",
                ragflow_document_name="report.pdf",
                sync_status="synced",
                parse_status="DONE",
            )
            session.add(db_file)
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_name="report.pdf",
                        source_content_sha256=reverted_hash,
                        ingested_content_sha256=reverted_hash,
                        state="pending_upload",
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="current-doc",
                        document_name="report.pdf",
                        source_content_sha256="current-source",
                        ingested_content_sha256="current-ingested",
                        state="current",
                        parse_status="DONE",
                    ),
                ]
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            {"id": "current-doc", "name": "report.pdf", "run": "DONE"}
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(reverted_content),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        with session_factory() as session:
            versions = session.query(FileDocumentVersion).order_by(
                FileDocumentVersion.id
            ).all()
            matching = [
                version
                for version in versions
                if version.source_content_sha256 == reverted_hash
            ]
            self.assertEqual(len(matching), 2)
            self.assertEqual(matching[0].state, "pending_upload")
            self.assertEqual(matching[1].state, "parsing")
            self.assertGreater(matching[1].id, versions[1].id)

    def test_bound_retryable_fallback_survives_newer_pending_upload(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            db_file = File(
                repo_id="repo",
                path="/docs/report.pdf",
                normalized_path="/docs/report.pdf",
                ragflow_document_id="fallback-doc",
                ragflow_document_name="report.pdf",
                sync_status="parse_failed",
                parse_status="FAIL",
            )
            session.add(db_file)
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="fallback-doc",
                        document_name="report.pdf",
                        state="retryable_failed",
                        parse_status="FAIL",
                        retry_count=1,
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_name="report.pdf",
                        state="pending_upload",
                    ),
                ]
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            {"id": "fallback-doc", "name": "report.pdf", "run": "DONE"}
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.check_parse_status("repo", "dataset")

        self.assertEqual(ragflow_client.deleted_ids, [])
        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(
                FileDocumentVersion.id
            ).all()
            self.assertEqual(db_file.ragflow_document_id, "fallback-doc")
            self.assertEqual([version.state for version in versions], ["current", "pending_upload"])

    def test_reused_active_cleanup_clears_stale_file_delete_payload(self) -> None:
        session_factory, old_version_id = _replacement_cleanup_fixture(
            self,
            payload={"delete_file_row": True, "clear_binding": True},
        )
        ragflow_client = _RenamingRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "managed-report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator._enqueue_cleanup(
            repo_id="repo",
            target_type="ragflow_document",
            target_id="old-doc",
            dataset_id="dataset",
            document_version_id=old_version_id,
        )
        orchestrator.process_cleanup_outbox(repo_id="repo")

        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.payload, {})
            self.assertIsNone(cleanup.file_id)
            self.assertEqual(cleanup.status, "completed")
            self.assertEqual(session.query(File).count(), 1)
            self.assertEqual(session.query(File).one().ragflow_document_id, "new-doc")

    def test_reused_dead_cleanup_keeps_manual_retry_gate(self) -> None:
        session_factory, old_version_id = _replacement_cleanup_fixture(
            self,
            payload={"delete_file_row": True},
        )
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            cleanup.status = "dead"
            cleanup.attempts = 5
            cleanup.error_message = "permanent failure"
            session.commit()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_RenamingRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator._enqueue_cleanup(
            repo_id="repo",
            target_type="ragflow_document",
            target_id="old-doc",
            dataset_id="dataset",
            document_version_id=old_version_id,
        )

        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "dead")
            self.assertEqual(cleanup.attempts, 5)
            self.assertEqual(cleanup.payload, {})
            self.assertIsNone(cleanup.file_id)
            self.assertEqual(cleanup.error_message, "permanent failure")

    def test_cleanup_preserves_old_document_when_replacement_is_missing(self) -> None:
        session_factory, _old_version_id = _replacement_cleanup_fixture(self)
        ragflow_client = _RenamingRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"}
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [])
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "retrying")
            self.assertIn("missing before cleanup", cleanup.error_message or "")
            self.assertEqual(session.query(File).one().ragflow_document_id, "new-doc")

    def test_cleanup_accepts_unsupported_rename_when_replacement_still_exists(self) -> None:
        class _UnsupportedRenameRAGFlowClient(_RenamingRAGFlowClient):
            def rename_document(
                self,
                dataset_id: str,
                document_id: str,
                document_name: str,
            ) -> dict[str, str]:
                raise ApiError("rename endpoint not found", status_code=404)

        session_factory, _old_version_id = _replacement_cleanup_fixture(self)
        ragflow_client = _UnsupportedRenameRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "managed-report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "completed")
            self.assertEqual(session.query(File).one().ragflow_document_id, "new-doc")

    def test_cleanup_generic_rename_400_retries_instead_of_completing(self) -> None:
        class _BadRequestRenameRAGFlowClient(_RenamingRAGFlowClient):
            def rename_document(
                self,
                dataset_id: str,
                document_id: str,
                document_name: str,
            ) -> dict[str, str]:
                self.operations.append("rename")
                raise ApiError(
                    "generic rename rejection",
                    status_code=400,
                    payload={"code": 100, "message": "Invalid rename request."},
                )

        session_factory, _old_version_id = _replacement_cleanup_fixture(self)
        ragflow_client = _BadRequestRenameRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "managed-report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        self.assertEqual(ragflow_client.operations, ["delete", "rename"])
        self.assertTrue(
            any(document.get("id") == "new-doc" for document in ragflow_client.documents)
        )
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "retrying")
            self.assertEqual(cleanup.attempts, 1)
            self.assertIn("generic rename rejection", cleanup.error_message or "")
            self.assertEqual(session.query(File).one().ragflow_document_id, "new-doc")

    def test_cleanup_does_not_defer_duplicate_name_collision(self) -> None:
        session_factory, _old_version_id = _replacement_cleanup_fixture(self)
        ragflow_client = _DuplicateNameRenamingRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "old-version.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "report.__connector_new.pdf", "run": "DONE"},
            {"id": "unowned-doc", "name": "report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        self.assertEqual(ragflow_client.operations, ["delete", "rename"])
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "retrying")
            self.assertIn("API returned an error code", cleanup.error_message or "")
            self.assertEqual(session.query(File).one().ragflow_document_id, "new-doc")

    def test_cleanup_rename_404_does_not_complete_outbox(self) -> None:
        class _MissingOnRenameRAGFlowClient(_RenamingRAGFlowClient):
            def rename_document(
                self,
                dataset_id: str,
                document_id: str,
                document_name: str,
            ) -> dict[str, str]:
                self.documents = [
                    document
                    for document in self.documents
                    if document.get("id") != document_id
                ]
                raise ApiError("document not found", status_code=404)

        session_factory, _old_version_id = _replacement_cleanup_fixture(self)
        ragflow_client = _MissingOnRenameRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "managed-report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        with session_factory() as session:
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "retrying")
            self.assertIn("missing after cleanup", cleanup.error_message or "")

    def test_promotion_and_cleanup_enqueue_commit_atomically(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            db_file = File(
                repo_id="repo",
                path="/docs/report.pdf",
                normalized_path="/docs/report.pdf",
                source_content_sha256="old-source",
                ingested_content_sha256="old-ingested",
                ragflow_document_id="old-doc",
                ragflow_document_name="report.pdf",
                sync_status="parsing",
                parse_status="RUNNING",
            )
            session.add(db_file)
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="old-doc",
                        document_name="report.pdf",
                        state="current",
                        parse_status="DONE",
                    ),
                    FileDocumentVersion(
                        file_id=db_file.id,
                        repo_id="repo",
                        normalized_path=db_file.normalized_path,
                        dataset_id="dataset",
                        document_id="new-doc",
                        document_name="report.pdf",
                        source_content_sha256="new-source",
                        ingested_content_sha256="new-ingested",
                        state="parsing",
                        parse_status="RUNNING",
                    ),
                ]
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            {"id": "old-doc", "name": "report.pdf", "run": "DONE"},
            {"id": "new-doc", "name": "report.pdf", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        def interrupt_before_commit(message: str) -> None:
            if message == "parse-status update interrupted before commit":
                raise SyncCancelledError(message)

        orchestrator._raise_if_job_interrupted = (  # type: ignore[method-assign]
            interrupt_before_commit
        )

        with self.assertRaisesRegex(
            SyncCancelledError, "parse-status update interrupted before commit"
        ):
            orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(
                [version.state for version in versions],
                ["current", "parsing"],
            )
            self.assertEqual(session.query(CleanupOutbox).count(), 0)

        def interrupt_after_commit(message: str) -> None:
            if message == "document cleanup interrupted":
                raise SyncCancelledError(message)

        orchestrator._raise_if_job_interrupted = (  # type: ignore[method-assign]
            interrupt_after_commit
        )

        with self.assertRaisesRegex(SyncCancelledError, "document cleanup interrupted"):
            orchestrator.check_parse_status("repo", "dataset")

        with session_factory() as session:
            db_file = session.query(File).one()
            versions = session.query(FileDocumentVersion).order_by(FileDocumentVersion.id).all()
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(db_file.ragflow_document_id, "new-doc")
            self.assertEqual(
                [version.state for version in versions],
                ["superseded", "current"],
            )
            self.assertEqual(cleanup.target_id, "old-doc")
            self.assertEqual(cleanup.status, "pending")

    def test_sync_file_checkpoints_cover_each_remote_pipeline_boundary(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=_RenamingRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        checkpoints: list[str] = []
        orchestrator._raise_if_job_interrupted = checkpoints.append  # type: ignore[method-assign]

        orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(
            checkpoints,
            [
                "file sync interrupted before download",
                "file sync interrupted after download",
                "file sync interrupted after conversion",
                "file sync interrupted before dataset settings",
                "file sync interrupted after dataset settings",
                "file sync interrupted before upload recovery",
                "file sync interrupted before upload",
                "file sync interrupted after upload",
                "file sync interrupted before metadata",
                "file sync interrupted after metadata",
                "file sync interrupted before rename",
                "file sync interrupted after rename",
                "file sync interrupted before parse",
                "file sync interrupted after parse",
                "file sync interrupted before parse-status scheduling",
            ],
        )

    def test_sync_file_pause_after_metadata_prevents_rename_and_parse(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        ragflow_client = _RenamingRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with (
            activate_job_pause(lambda: "metadata" in ragflow_client.operations),
            self.assertRaisesRegex(SyncCancelledError, "after metadata"),
        ):
            orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(ragflow_client.operations, ["upload", "metadata"])
        self.assertEqual(ragflow_client.renamed_documents, [])
        self.assertEqual(ragflow_client.parsed_ids, [])

    def test_sync_file_pause_after_download_prevents_conversion_and_upload(self) -> None:
        class _TrackingSyncClient(_FakeSeafileSyncClient):
            def __init__(self) -> None:
                super().__init__(b"%PDF-1.4\ncontent")
                self.downloaded = False

            def download_file(self, repo_id: str, path: str) -> bytes:
                self.downloaded = True
                return super().download_file(repo_id, path)

        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        sync_client = _TrackingSyncClient()
        ragflow_client = _RenamingRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=sync_client,
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with (
            activate_job_pause(lambda: sync_client.downloaded),
            self.assertRaisesRegex(SyncCancelledError, "after download"),
        ):
            orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(ragflow_client.operations, [])
        with session_factory() as session:
            self.assertEqual(session.query(File).count(), 0)

    def test_missing_ragflow_document_is_reuploaded_even_when_file_hash_matches(self) -> None:
        session_factory = _session_factory(self)
        content = b"%PDF-1.4\ncontent"
        content_hash = sha256_bytes(content)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256=content_hash,
                    ingested_content_sha256=content_hash,
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = []
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(content),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        self.assertEqual(ragflow_client.deleted_ids, [])
        self.assertEqual(
            ragflow_client.operations,
            ["upload", "metadata", "parse"],
        )
        self.assertEqual(ragflow_client.metadata_updates[0][2]["source_sha256"], content_hash)
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            pending = session.query(FileDocumentVersion).filter_by(state="parsing").one()
            self.assertEqual(pending.document_id, "new-doc")

        ragflow_client.documents = [{"id": "new-doc", "name": "report.pdf", "run": "DONE"}]
        self.assertEqual(orchestrator.check_parse_status("repo", "dataset"), 1)
        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])

    def test_parse_failure_preserves_old_binding_and_does_not_delete(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256="old-source",
                    ingested_content_sha256="old-ingested",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.parse_error = ApiError(
            "parse rejected",
            status_code=200,
            payload={"code": 102},
        )
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\nnew content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with self.assertRaises(ApiError):
            orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertEqual(ragflow_client.operations, ["upload", "metadata", "parse"])
        self.assertEqual(ragflow_client.deleted_ids, [])
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(db_file.sync_status, "pending")

    def test_delete_failure_keeps_new_binding_and_does_not_repeat_upload(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    source_content_sha256="old-source",
                    ingested_content_sha256="old-ingested",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.delete_error = ApiError("delete unavailable", status_code=503)
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\nnew content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        self.assertEqual(
            ragflow_client.operations,
            ["upload", "metadata", "parse"],
        )
        self.assertEqual(ragflow_client.deleted_ids, [])
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.ragflow_document_id, "old-doc")
            self.assertEqual(db_file.sync_status, "parsing")

        ragflow_client.documents = [{"id": "new-doc", "name": "report.pdf", "run": "DONE"}]
        self.assertEqual(orchestrator.check_parse_status("repo", "dataset"), 1)
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.ragflow_document_id, "new-doc")
            self.assertEqual(db_file.sync_status, "synced")
            cleanup = session.query(CleanupOutbox).one()
            self.assertEqual(cleanup.status, "retrying")

        second = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")
        self.assertFalse(second.uploaded)
        self.assertEqual(
            ragflow_client.operations,
            ["upload", "metadata", "parse", "delete"],
        )

    def test_check_parse_status_accepts_document_id_and_clears_completed_error(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    ragflow_document_id="target-doc",
                    parse_status="FAIL",
                    error_message="old parse failure",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [
            *({"id": f"other-{index}", "run": "DONE"} for index in range(100)),
            {"document_id": "target-doc", "run": "DONE"},
        ]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        self.assertEqual(orchestrator.check_parse_status("repo", "dataset"), 1)
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertEqual(db_file.parse_status, "DONE")
            self.assertIsNone(db_file.error_message)

    def test_check_parse_status_does_not_erase_state_when_run_is_missing(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    ragflow_document_id="target-doc",
                    parse_status="RUNNING",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.documents = [{"id": "target-doc"}]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        self.assertEqual(orchestrator.check_parse_status("repo", "dataset"), 0)
        with session_factory() as session:
            self.assertEqual(session.query(File).one().parse_status, "RUNNING")

    def test_dataset_recreation_clears_document_bindings_for_reupload(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-old",
                    ragflow_dataset_name="seafile__demo__repo",
                )
            )
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/report.pdf",
                    normalized_path="/docs/report.pdf",
                    ragflow_document_id="old-doc",
                    ragflow_document_name="report.pdf",
                    sync_status="synced",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.dataset_id = "dataset-new"
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        dataset_id = orchestrator.ensure_dataset_for_repo("repo")

        self.assertEqual(dataset_id, "dataset-new")
        with session_factory() as session:
            db_file = session.query(File).one()
            self.assertIsNone(db_file.ragflow_document_id)
            self.assertEqual(db_file.sync_status, "pending")

    def test_existing_bound_legacy_dataset_is_reused_before_new_name_creation(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="error",
                    last_error="previous failure",
                    ragflow_dataset_id="dataset-old",
                    ragflow_dataset_name="seafile__demo__repo",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.generated_dataset_exists = False
        ragflow_client.datasets_by_id["dataset-old"] = {
            "id": "dataset-old",
            "name": "seafile__demo__repo",
        }
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        dataset_id = orchestrator.ensure_dataset_for_repo("repo")

        self.assertEqual(dataset_id, "dataset-old")
        self.assertEqual(ragflow_client.created_datasets, [])
        with session_factory() as session:
            library = session.get(Library, "repo")
            self.assertIsNotNone(library)
            assert library is not None
            self.assertEqual(library.ragflow_dataset_name, "seafile__demo__repo")
            self.assertEqual(library.status, "error")
            self.assertEqual(library.last_error, "previous failure")

    def test_sync_library_failure_marks_library_error_after_dataset_reuse(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-old",
                    ragflow_dataset_name="seafile__demo__repo",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.datasets_by_id["dataset-old"] = {
            "id": "dataset-old",
            "name": "seafile__demo__repo",
        }
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FailingSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            orchestrator.sync_library_full("repo")

        with session_factory() as session:
            library = session.get(Library, "repo")
            self.assertIsNotNone(library)
            assert library is not None
            self.assertEqual(library.status, "error")
            self.assertEqual(library.last_error, "HTTP 403")

    def test_missing_template_dataset_is_created_with_rag_defaults(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.template_exists = False
        ragflow_client.generated_dataset_exists = False
        ragflow_client.dataset_id = "dataset-created"
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        dataset_id = orchestrator.ensure_dataset_for_repo("repo")

        self.assertEqual(dataset_id, "dataset-created")
        template_payload = ragflow_client.created_datasets[0]
        generated_payload = ragflow_client.created_datasets[1]
        self.assertEqual(template_payload["name"], "connector_template")
        self.assertEqual(template_payload["permission"], "me")
        self.assertEqual(template_payload["chunk_method"], "naive")
        parser_config = template_payload["parser_config"]
        self.assertEqual(parser_config["layout_recognize"], "DeepDOC")
        self.assertEqual(parser_config["auto_questions"], 0)
        self.assertEqual(parser_config["auto_keywords"], 0)
        self.assertEqual(parser_config["pages"], [[1, 1000000]])
        self.assertTrue(str(generated_payload["name"]).startswith("RAG_demo_"))
        self.assertEqual(generated_payload["permission"], "me")

    def test_generated_dataset_can_use_team_permission_while_template_stays_private(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.template_exists = False
        ragflow_client.generated_dataset_exists = False
        ragflow_client.dataset_id = "dataset-created"
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            generated_dataset_permission="team",
            refresh_dataset_settings=False,
        )

        dataset_id = orchestrator.ensure_dataset_for_repo("repo")

        self.assertEqual(dataset_id, "dataset-created")
        template_payload, generated_payload = ragflow_client.created_datasets
        self.assertEqual(template_payload["permission"], "me")
        self.assertEqual(generated_payload["permission"], "team")

    def test_existing_generated_dataset_still_ensures_template_dataset(self) -> None:
        class _ExistingTeamDatasetRAGFlowClient(_FakeRAGFlowClient):
            def list_datasets(
                self,
                *,
                name: str | None = None,
                parse_status: str | None = None,
            ):
                datasets = super().list_datasets(name=name, parse_status=parse_status)
                if name != "connector_template":
                    for dataset in datasets:
                        dataset["permission"] = "team"
                return datasets

        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _ExistingTeamDatasetRAGFlowClient()
        ragflow_client.template_exists = False
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            generated_dataset_permission="team",
            refresh_dataset_settings=False,
        )

        dataset_id = orchestrator.ensure_dataset_for_repo("repo")

        self.assertEqual(dataset_id, "dataset")
        self.assertEqual(ragflow_client.created_datasets[0]["name"], "connector_template")
        self.assertEqual(ragflow_client.created_datasets[0]["permission"], "me")
        self.assertEqual(ragflow_client.updated_datasets, [])

    def test_controlled_missing_libraries_keep_target_state_and_supersede_cleanup(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            for repo_id in ("paused", "disabled"):
                session.add(
                    Library(
                        repo_id=repo_id,
                        name=repo_id.title(),
                        name_slug=repo_id,
                        status="awaiting_confirmation",
                        deletion_state="awaiting_confirmation",
                        ragflow_dataset_id=f"dataset-{repo_id}",
                        missing_since=datetime.now(UTC) - timedelta(hours=25),
                        missing_observations=3,
                    )
                )
                session.add(
                    File(
                        repo_id=repo_id,
                        path="/keep.pdf",
                        normalized_path="/keep.pdf",
                    )
                )
                session.add(
                    CleanupOutbox(
                        repo_id=repo_id,
                        target_type="ragflow_dataset",
                        target_id=f"dataset-{repo_id}",
                        dataset_id=f"dataset-{repo_id}",
                        action="delete",
                        status="pending",
                    )
                )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient([]),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.admin_control_store.update_library(
            "paused",
            updated_by="test",
            paused=True,
        )
        orchestrator.admin_control_store.update_library(
            "disabled",
            updated_by="test",
            enabled=False,
        )

        self.assertEqual(orchestrator.discover_libraries(), [])

        for repo_id in ("paused", "disabled"):
            self.assertFalse(orchestrator.confirm_missing_library_deletion(repo_id))
        self.assertEqual(ragflow_client.deleted_dataset_ids, [])
        with session_factory() as session:
            libraries = session.query(Library).order_by(Library.repo_id).all()
            self.assertEqual({library.status for library in libraries}, {"active"})
            self.assertEqual(
                {library.deletion_state for library in libraries},
                {"active"},
            )
            self.assertTrue(all(library.missing_since is None for library in libraries))
            self.assertTrue(all(library.missing_observations == 0 for library in libraries))
            self.assertEqual(session.query(File).count(), 2)
            self.assertEqual(
                {row.status for row in session.query(CleanupOutbox).all()},
                {"superseded"},
            )

    def test_deleted_seafile_library_deletes_ragflow_dataset_without_touching_seafile(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset",
                )
            )
            session.add(File(repo_id="repo", path="/a.pdf", normalized_path="/a.pdf"))
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient([]),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        self.assertEqual(orchestrator.discover_libraries(), [])
        with session_factory() as session:
            library = session.get(Library, "repo")
            assert library is not None
            self.assertEqual(library.missing_observations, 1)
            self.assertEqual(library.status, "missing")
            library.missing_since = datetime.now(UTC) - timedelta(hours=25)
            session.commit()

        for _index in range(2):
            with session_factory() as session:
                library = session.get(Library, "repo")
                assert library is not None
                library.last_missing_observation_at = datetime.now(UTC) - timedelta(
                    hours=2
                )
                session.commit()
            self.assertEqual(orchestrator.discover_libraries(), [])

        self.assertEqual(ragflow_client.deleted_dataset_ids, [["dataset"]])
        with session_factory() as session:
            library = session.get(Library, "repo")
            self.assertEqual(library.status, "deleted")
            self.assertEqual(session.query(File).count(), 0)

    def test_mass_missing_guard_requires_confirmation_before_dataset_cleanup(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id=f"repo-{index}",
                        name=f"Repo {index}",
                        name_slug=f"repo-{index}",
                        status="active",
                        ragflow_dataset_id=f"dataset-{index}",
                    )
                    for index in range(5)
                ]
            )
            session.commit()
        visible = [
            {"id": "repo-3", "name": "Repo 3"},
            {"id": "repo-4", "name": "Repo 4"},
        ]
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(visible),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.discover_libraries()
        with session_factory() as session:
            for library in session.query(Library).filter(
                Library.repo_id.in_(["repo-0", "repo-1", "repo-2"])
            ):
                library.missing_since = datetime.now(UTC) - timedelta(hours=25)
            session.commit()
        for _index in range(2):
            with session_factory() as session:
                for library in session.query(Library).filter(
                    Library.repo_id.in_(["repo-0", "repo-1", "repo-2"])
                ):
                    library.last_missing_observation_at = datetime.now(UTC) - timedelta(
                        hours=2
                    )
                session.commit()
            orchestrator.discover_libraries()

        self.assertEqual(ragflow_client.deleted_dataset_ids, [])
        with session_factory() as session:
            guarded = session.query(Library).filter(
                Library.repo_id.in_(["repo-0", "repo-1", "repo-2"])
            )
            self.assertEqual(
                {library.deletion_state for library in guarded},
                {"awaiting_confirmation"},
            )
        self.assertTrue(orchestrator.confirm_missing_library_deletion("repo-0"))
        self.assertEqual(ragflow_client.deleted_dataset_ids, [["dataset-0"]])

    def test_discovery_keeps_confirmed_and_dead_dataset_cleanup_states_sticky(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="confirmed",
                        name="Confirmed",
                        name_slug="confirmed",
                        status="confirmed_for_deletion",
                        deletion_state="confirmed",
                        ragflow_dataset_id="dataset-confirmed",
                    ),
                    Library(
                        repo_id="failed",
                        name="Failed",
                        name_slug="failed",
                        status="delete_failed",
                        deletion_state="delete_failed",
                        ragflow_dataset_id="dataset-failed",
                    ),
                ]
            )
            session.add_all(
                [
                    CleanupOutbox(
                        repo_id="confirmed",
                        target_type="ragflow_dataset",
                        target_id="dataset-confirmed",
                        dataset_id="dataset-confirmed",
                        action="delete",
                        status="retrying",
                        run_after=datetime.now(UTC) + timedelta(hours=1),
                    ),
                    CleanupOutbox(
                        repo_id="failed",
                        target_type="ragflow_dataset",
                        target_id="dataset-failed",
                        dataset_id="dataset-failed",
                        action="delete",
                        status="dead",
                        attempts=5,
                    ),
                ]
            )
            session.commit()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient([]),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        orchestrator.discover_libraries()

        with session_factory() as session:
            confirmed = session.get(Library, "confirmed")
            failed = session.get(Library, "failed")
            assert confirmed is not None and failed is not None
            self.assertEqual(confirmed.deletion_state, "confirmed")
            self.assertEqual(confirmed.status, "confirmed_for_deletion")
            self.assertEqual(failed.deletion_state, "delete_failed")
            self.assertEqual(failed.status, "delete_failed")

    def test_reappearance_during_remote_dataset_delete_prevents_state_purge(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo",
                    name="Demo",
                    name_slug="demo",
                    status="confirmed_for_deletion",
                    deletion_state="confirmed",
                    ragflow_dataset_id="dataset",
                )
            )
            session.add(File(repo_id="repo", path="/a.pdf", normalized_path="/a.pdf"))
            session.add(
                CleanupOutbox(
                    repo_id="repo",
                    target_type="ragflow_dataset",
                    target_id="dataset",
                    dataset_id="dataset",
                    action="delete",
                    status="pending",
                )
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()

        def reappear_while_deleting(dataset_ids: list[str]) -> None:
            ragflow_client.deleted_dataset_ids.append(dataset_ids)
            with session_factory() as session:
                library = session.get(Library, "repo")
                cleanup = session.query(CleanupOutbox).one()
                assert library is not None
                cleanup.status = "superseded"
                cleanup.completed_at = datetime.now(UTC)
                library.status = "active"
                library.deletion_state = "active"
                library.last_seen_at = datetime.now(UTC)
                session.commit()

        ragflow_client.delete_datasets = reappear_while_deleting  # type: ignore[method-assign]
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        self.assertEqual(orchestrator.process_cleanup_outbox(repo_id="repo"), 0)

        with session_factory() as session:
            library = session.get(Library, "repo")
            cleanup = session.query(CleanupOutbox).one()
            assert library is not None
            self.assertEqual(library.status, "active")
            self.assertEqual(library.deletion_state, "active")
            self.assertEqual(cleanup.status, "superseded")
            self.assertEqual(session.query(File).count(), 1)
            cleanup_id = int(cleanup.id)
        reactivated_id = orchestrator._enqueue_cleanup(
            repo_id="repo",
            target_type="ragflow_dataset",
            target_id="dataset",
            dataset_id="dataset",
        )
        self.assertEqual(reactivated_id, cleanup_id)
        with session_factory() as session:
            cleanup = session.get(CleanupOutbox, cleanup_id)
            assert cleanup is not None
            self.assertEqual(cleanup.status, "pending")

    def test_cleanup_completion_finalizes_subscribed_workflow_without_status_get(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.commit()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )
        orchestrator.sync_state_store.create_run(
            run_id="workflow",
            repo_id=None,
            mode="workflow",
            status="running",
        )
        job_id = orchestrator.job_store.enqueue(
            JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="repo")
        )
        orchestrator.job_store.subscribe_workflow(
            "workflow",
            job_id,
            is_root=True,
            owns_job=True,
        )
        with session_factory() as session:
            job = session.get(SyncJob, job_id)
            assert job is not None
            job.status = JobStatus.SUCCEEDED.value
            cleanup = CleanupOutbox(
                repo_id="repo",
                target_type="ragflow_document",
                target_id="old-doc",
                dataset_id="dataset",
                action="delete",
                status="pending",
            )
            session.add(cleanup)
            session.commit()
            cleanup_id = int(cleanup.id)
        orchestrator.job_store.subscribe_cleanup_from_job(job_id, cleanup_id)
        self.assertEqual(
            orchestrator.job_store.refresh_workflow_parent("workflow"),
            "retrying",
        )

        orchestrator.process_cleanup_outbox(repo_id="repo")

        workflow = orchestrator.sync_state_store.get_run("workflow")
        self.assertIsNotNone(workflow)
        assert workflow is not None
        self.assertEqual(workflow.status, "succeeded")

    def test_cleanup_outbox_stops_before_next_remote_delete_when_paused(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
            session.add_all(
                [
                    CleanupOutbox(
                        repo_id="repo",
                        target_type="ragflow_document",
                        target_id=f"doc-{index}",
                        dataset_id="dataset",
                        action="delete",
                        status="pending",
                    )
                    for index in range(2)
                ]
            )
            session.commit()
        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"content"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        with (
            activate_job_pause(lambda: bool(ragflow_client.deleted_ids)),
            self.assertRaisesRegex(SyncCancelledError, "cleanup outbox"),
        ):
            orchestrator.process_cleanup_outbox(repo_id="repo")

        self.assertEqual(ragflow_client.deleted_ids, [["doc-0"]])
        with session_factory() as session:
            statuses = [
                row.status
                for row in session.query(CleanupOutbox).order_by(CleanupOutbox.id)
            ]
            self.assertEqual(statuses, ["completed", "pending"])

    def test_delete_unknown_file_is_skipped_without_ragflow_delete(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        deleted = orchestrator.delete_file("repo", "dataset", "/missing.pdf")

        self.assertFalse(deleted)
        self.assertEqual(ragflow_client.deleted_ids, [])

    def test_recursive_missing_delete_is_scoped_to_directory(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo",
                    path="/docs/a.pdf",
                    normalized_path="/docs/a.pdf",
                    ragflow_document_id="doc-a",
                )
            )
            session.add(
                File(
                    repo_id="repo",
                    path="/other/b.pdf",
                    normalized_path="/other/b.pdf",
                    ragflow_document_id="doc-b",
                )
            )
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=_FakeSeafileSyncClient(b"%PDF-1.4\ncontent"),
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            refresh_dataset_settings=False,
        )

        deleted_count = orchestrator.delete_missing_files(
            "repo",
            "dataset",
            set(),
            scope="/docs",
        )

        self.assertEqual(deleted_count, 1)
        self.assertEqual(ragflow_client.deleted_ids, [["doc-a"]])
        with session_factory() as session:
            remaining = session.query(File).one()
            self.assertEqual(remaining.normalized_path, "/other/b.pdf")


if __name__ == "__main__":
    unittest.main()
