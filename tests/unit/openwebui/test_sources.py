from __future__ import annotations

import unittest

from seafile_ragflow_connector.openwebui.sources import (
    extract_answer,
    normalize_sources,
    sign_preview_payload,
    verify_preview_token,
)

try:
    from seafile_ragflow_connector.config.settings import Settings
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "pydantic_settings"}:
        raise
    Settings = None  # type: ignore[assignment]


@unittest.skipIf(Settings is None, "pydantic is not installed in this Python environment")
class OpenWebUISourceTests(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(
            seafile_base_url="http://seafile.local",
            seafile_admin_token="admin-token",
            seafile_sync_user_token="sync-token",
            ragflow_base_url="http://ragflow.local",
            ragflow_api_key="ragflow-token",
            database_url="postgresql+psycopg://custom/db",
            openwebui_integration_enabled=True,
            openwebui_sync_mode="dry-run",
            openwebui_proxy_shared_secret="proxy-secret",
            openwebui_proxy_public_base_url="https://connector.example",
            openwebui_source_preview_mode="connector_viewer",
        )

    def test_signed_preview_tokens_roundtrip_and_expire(self) -> None:
        token = sign_preview_payload({"document_id": "doc-1"}, "proxy-secret", now=100)

        self.assertEqual(
            verify_preview_token(token, "proxy-secret", now=101)["document_id"],
            "doc-1",
        )

        with self.assertRaises(ValueError):
            verify_preview_token(token, "proxy-secret", now=2000)

    def test_normalize_sources_builds_safe_preview_url(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_keyword": "report.pdf",
                        "content": "Treffertext",
                        "similarity": 0.9,
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertEqual(len(sources), 1)
        self.assertIn("connector.example/api/openwebui/sources/preview", sources[0]["preview_url"])
        self.assertEqual(sources[0]["metadata"][0]["dataset_id"], "dataset-1")
        self.assertEqual(sources[0]["source_metadata"]["dataset_id"], "dataset-1")
        self.assertEqual(sources[0]["document"], ["Treffertext"])
        self.assertEqual(sources[0]["name"], "report.pdf")

    def test_normalize_sources_extracts_ragflow_reference_mapping_without_path_leak(self) -> None:
        sources = normalize_sources(
            {
                "choices": [
                    {
                        "message": {
                            "reference": {
                                "chunks": {
                                    "20": {
                                        "id": "chunk-1",
                                        "document_id": "doc-1",
                                        "content": "Treffertext",
                                    }
                                }
                            }
                        }
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
            files_by_document_id={
                "doc-1": {
                    "repo_id": "repo-1",
                    "path": "/internal/folder/report.pdf",
                    "ragflow_document_name": "",
                }
            },
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["name"], "report.pdf")
        self.assertNotIn("source_path", sources[0]["metadata"][0])
        self.assertNotIn("source_path", sources[0]["source_metadata"])

    def test_extract_answer_unwraps_native_ragflow_data_payload(self) -> None:
        answer = extract_answer(
            {
                "code": 0,
                "data": {
                    "answer": "Antwort aus RAGFlow",
                    "reference": {"chunks": []},
                },
                "message": "success",
            }
        )

        self.assertEqual(answer, "Antwort aus RAGFlow")


if __name__ == "__main__":
    unittest.main()
