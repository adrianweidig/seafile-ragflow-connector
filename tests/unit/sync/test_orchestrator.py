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
        ParseDeadError,
        ParsePendingError,
        SyncOrchestrator,
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

    def iter_libraries(self):
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
            return [{"id": self.dataset_id, "name": name or "Dataset"}]
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
        return {"id": self.dataset_id, **payload}

    def update_dataset(
        self,
        dataset_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.updated_datasets.append((dataset_id, payload))
        return {"id": dataset_id, "name": "connector_template", **payload}

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


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine("sqlite:///:memory:")
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class OrchestratorUploadTests(unittest.TestCase):
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
            self.assertEqual(session.query(FileDocumentVersion).count(), 1)

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
        self.assertEqual(template_payload["chunk_method"], "naive")
        parser_config = template_payload["parser_config"]
        self.assertEqual(parser_config["layout_recognize"], "DeepDOC")
        self.assertEqual(parser_config["auto_questions"], 0)
        self.assertEqual(parser_config["auto_keywords"], 0)
        self.assertEqual(parser_config["pages"], [[1, 1000000]])
        self.assertTrue(str(generated_payload["name"]).startswith("RAG_demo_"))

    def test_existing_generated_dataset_still_ensures_template_dataset(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo", name="Demo", name_slug="demo", status="active"))
            session.commit()

        ragflow_client = _FakeRAGFlowClient()
        ragflow_client.template_exists = False
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

        self.assertEqual(dataset_id, "dataset")
        self.assertEqual(ragflow_client.created_datasets[0]["name"], "connector_template")

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
