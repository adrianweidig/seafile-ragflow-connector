from __future__ import annotations

import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

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
        self.parsed_ids: list[list[str]] = []
        self.dataset_id = "dataset"

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
            return [{"id": "template", "name": "connector_template"}]
        return [{"id": self.dataset_id, "name": name or "Dataset"}]

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

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.parsed_ids.append(document_ids)


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class OrchestratorUploadTests(unittest.TestCase):
    def test_upload_deletes_existing_ragflow_documents_with_same_name(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])
        self.assertEqual(ragflow_client.last_keywords, "report")
        self.assertEqual(ragflow_client.last_page_size, 1024)

    def test_missing_ragflow_document_is_reuploaded_even_when_file_hash_matches(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        self.assertEqual(ragflow_client.parsed_ids, [["new-doc"]])

    def test_dataset_recreation_clears_document_bindings_for_reupload(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
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

    def test_deleted_seafile_library_deletes_ragflow_dataset_without_touching_seafile(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
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


if __name__ == "__main__":
    unittest.main()
