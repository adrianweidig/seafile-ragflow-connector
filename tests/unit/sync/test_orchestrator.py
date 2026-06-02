from __future__ import annotations

import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from seafile_ragflow_connector.clients.http import ApiError
    from seafile_ragflow_connector.domain.file_classification import FilePolicy
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.file import File
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.sync.orchestrator import SyncOrchestrator
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
        self.deleted_ids.append(document_ids)

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
        self.uploaded_name = document_name
        return {"id": "new-doc"}

    def update_document_metadata(
        self,
        dataset_id: str,
        document_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.metadata_updates.append((dataset_id, document_id, metadata))
        return {"ok": True}

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.parsed_ids.append(document_ids)


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine("sqlite:///:memory:")
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class OrchestratorUploadTests(unittest.TestCase):
    def test_upload_deletes_existing_ragflow_documents_with_same_name(self) -> None:
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

        result = orchestrator.sync_file("repo", "dataset", "/docs/report.pdf")

        self.assertTrue(result.uploaded)
        self.assertEqual(ragflow_client.deleted_ids, [["stale-exact", "stale-copy"]])
        self.assertEqual(ragflow_client.uploaded_name, "report.pdf")
        self.assertEqual(ragflow_client.metadata_updates[0][0:2], ("dataset", "new-doc"))
        self.assertEqual(ragflow_client.metadata_updates[0][2]["repo_id"], "repo")
        self.assertEqual(ragflow_client.metadata_updates[0][2]["source_path"], "/docs/report.pdf")
        self.assertEqual(ragflow_client.metadata_updates[0][2]["document_name"], "report.pdf")
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])
        self.assertEqual(ragflow_client.last_keywords, "report")
        self.assertEqual(ragflow_client.last_page_size, 1024)

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
        self.assertEqual(ragflow_client.deleted_ids, [["old-doc"]])
        self.assertEqual(ragflow_client.metadata_updates[0][2]["source_sha256"], content_hash)
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])

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
            self.assertEqual(library.status, "active")
            self.assertIsNone(library.last_error)

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

        self.assertEqual(ragflow_client.deleted_dataset_ids, [["dataset"]])
        with session_factory() as session:
            library = session.get(Library, "repo")
            self.assertEqual(library.status, "deleted")
            self.assertEqual(session.query(File).count(), 0)

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
