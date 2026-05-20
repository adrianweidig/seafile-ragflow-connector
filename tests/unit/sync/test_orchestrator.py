from __future__ import annotations

import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from seafile_ragflow_connector.domain.file_classification import FilePolicy
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.sync.orchestrator import SyncOrchestrator
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
    create_engine = None  # type: ignore[assignment]


class _FakeSeafileSyncClient:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def download_file(self, repo_id: str, path: str) -> bytes:
        return self.content


class _FakeRAGFlowClient:
    def __init__(self) -> None:
        self.documents = [
            {"id": "stale-exact", "name": "report.pdf"},
            {"id": "stale-copy", "name": "report (1).pdf"},
            {"id": "unrelated", "name": "other.pdf"},
        ]
        self.deleted_ids: list[list[str]] = []
        self.parsed_ids: list[list[str]] = []

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

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.deleted_ids.append(document_ids)

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
            admin_client=object(),  # type: ignore[arg-type]
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


if __name__ == "__main__":
    unittest.main()
