from __future__ import annotations

import unittest

from seafile_ragflow_connector.openwebui.sources import (
    annotate_answer_citations,
    extract_answer,
    normalize_sources,
    render_sources_markdown,
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

    def test_signed_preview_tokens_roundtrip_and_keep_chat_links_durable(self) -> None:
        token = sign_preview_payload({"document_id": "doc-1"}, "proxy-secret", now=100)

        self.assertEqual(
            verify_preview_token(token, "proxy-secret", now=101)["document_id"],
            "doc-1",
        )
        self.assertEqual(
            verify_preview_token(token, "proxy-secret", now=2000)["document_id"],
            "doc-1",
        )

    def test_legacy_expired_preview_tokens_still_open_saved_chat_sources(self) -> None:
        token = sign_preview_payload(
            {"document_id": "doc-1", "exp": 101},
            "proxy-secret",
            now=100,
        )

        self.assertEqual(
            verify_preview_token(token, "proxy-secret", now=2000)["document_id"],
            "doc-1",
        )

    def test_normalize_sources_builds_safe_preview_url(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_keyword": "report.pdf",
                        "content": "Treffertext",
                        "positions": [[3, 10, 20, 30, 40]],
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
        self.assertEqual(sources[0]["source_metadata"]["citation_marker"], "[ID:0]")
        self.assertEqual(sources[0]["source_metadata"]["page"], 3)
        self.assertIn("Quelle 1, Seite 3, Chunk chunk-1", sources[0]["citation_label"])

        token = sources[0]["preview_url"].rsplit("token=", 1)[1]
        preview = verify_preview_token(token, "proxy-secret", now=100)
        self.assertEqual(preview["page"], 3)
        self.assertEqual(preview["position"], [[3, 10, 20, 30, 40]])
        self.assertLess(len(token), 420)

    def test_normalize_sources_adds_original_file_url_without_path_leak(self) -> None:
        settings = self._settings()
        settings.seafile_file_url_template = (
            "https://seafile.example/lib/{repo_id_quoted}/file{path_quoted}{page_fragment}"
        )

        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "content": "PDF-Treffertext",
                        "positions": [[4, 10, 20, 30, 40]],
                    }
                ]
            },
            settings=settings,
            dataset_id="dataset-1",
            dataset_name="Demo",
            files_by_document_id={
                "doc-1": {
                    "repo_id": "repo-1",
                    "path": "/folder/report final.pdf",
                    "ragflow_document_name": "report final.pdf",
                }
            },
        )

        self.assertEqual(
            sources[0]["original_url"],
            "https://seafile.example/lib/repo-1/file/folder/report%20final.pdf#page=4",
        )
        self.assertEqual(sources[0]["source_metadata"]["path"], "/folder/report final.pdf")
        self.assertEqual(sources[0]["source_metadata"]["repo_id"], "repo-1")

        token = sources[0]["preview_url"].rsplit("token=", 1)[1]
        preview = verify_preview_token(token, "proxy-secret", now=100)
        self.assertEqual(preview["source_path"], "/folder/report final.pdf")
        self.assertEqual(preview["original_url"], sources[0]["original_url"])

    def test_preview_token_keeps_long_snippets_compact(self) -> None:
        long_text = "Preview-Auszug " * 80

        sources = normalize_sources(
            {"chunks": [{"id": "chunk-1", "document_id": "doc-1", "content": long_text}]},
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        token = sources[0]["preview_url"].rsplit("token=", 1)[1]
        preview = verify_preview_token(token, "proxy-secret", now=100)

        self.assertEqual(sources[0]["snippet"], long_text.strip())
        self.assertLessEqual(len(preview["snippet"]), 123)
        self.assertTrue(preview["snippet"].endswith("..."))
        self.assertLess(len(token), 650)

    def test_annotate_answer_citations_links_ragflow_inline_ids_to_sources(self) -> None:
        sources = normalize_sources(
            {
                "reference": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "report.pdf",
                        "content": "Treffertext",
                        "positions": [[3, 10, 20, 30, 40]],
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        answer = annotate_answer_citations(
            "Siehe Studienplan [ID:0] und unbekannt [ID:9].",
            sources,
        )

        self.assertIn("[Quelle 1, Seite 3, Chunk chunk-1](https://connector.example", answer)
        self.assertNotIn("[ID:0]", answer)
        self.assertIn("[ID:9]", answer)

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
        self.assertEqual(sources[0]["source_metadata"]["path"], "/internal/folder/report.pdf")
        self.assertEqual(sources[0]["source_metadata"]["repo_id"], "repo-1")

    def test_normalize_sources_sanitizes_html_fragments_and_entities(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "html_fragmente.md",
                        "content": (
                            "<table><tr><td>Alpha</td><td>&Uuml;ber</td></tr></table>"
                            "<script>hidden()</script>"
                        ),
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertEqual(sources[0]["snippet"], "Alpha | Über")
        self.assertEqual(sources[0]["document"], ["Alpha | Über"])
        self.assertNotIn("<td>", sources[0]["text"])

    def test_render_sources_markdown_groups_documents_and_hides_debug_ids(self) -> None:
        settings = self._settings()
        settings.seafile_file_url_template = (
            "https://seafile.example/lib/{repo_id_quoted}/file{path_quoted}{page_fragment}"
        )
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-a",
                        "document_id": "doc-1",
                        "content": "Treffer eins mit # Überschrift und Alpha | Beta",
                        "positions": [[2, 1, 1, 1, 1]],
                        "similarity": 0.68,
                    },
                    {
                        "id": "chunk-b",
                        "document_id": "doc-1",
                        "content": "Zweiter Treffer im gleichen Dokument",
                        "positions": [[3, 1, 1, 1, 1]],
                        "similarity": 0.61,
                    },
                ]
            },
            settings=settings,
            dataset_id="dataset-1",
            dataset_name="Demo",
            files_by_document_id={
                "doc-1": {
                    "repo_id": "repo-1",
                    "path": "/aehnlicher_inhalt_b.txt",
                    "ragflow_document_name": "aehnlicher_inhalt_b.txt",
                }
            },
        )

        markdown = render_sources_markdown(sources)

        self.assertIn("### 1. aehnlicher\\_inhalt\\_b.txt", markdown)
        self.assertIn("Relevanz mittel (68%)", markdown)
        self.assertIn("2 Treffer", markdown)
        self.assertIn("Preview öffnen", markdown)
        self.assertIn("Original öffnen", markdown)
        self.assertIn("\\# Überschrift", markdown)
        self.assertIn("Alpha \\| Beta", markdown)
        self.assertNotIn("chunk-a", markdown)

    def test_normalize_sources_removes_text_projection_wrappers(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "html_fragmente.md",
                        "content": (
                            "Source path: /html_fragmente.md\n"
                            "Source path hash: abc\n"
                            "----- BEGIN SOURCE CONTENT -----\n"
                            "# HTML-Fragmente\nAlpha und <td>Beta</td>\n"
                            "----- END SOURCE CONTENT -----"
                        ),
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertEqual(sources[0]["snippet"], "# HTML-Fragmente\nAlpha und Beta")
        self.assertNotIn("Source path", sources[0]["snippet"])

    def test_normalize_sources_prefers_original_seafile_name_over_projection_name(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "hash__html_fragmente.md.txt",
                        "content": "Treffertext",
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
            files_by_document_id={
                "doc-1": {
                    "path": "/html_fragmente.md",
                    "ragflow_document_name": "hash__html_fragmente.md.txt",
                }
            },
        )

        self.assertEqual(sources[0]["name"], "html_fragmente.md")

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
