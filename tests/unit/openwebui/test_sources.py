from __future__ import annotations

import unittest

from seafile_ragflow_connector.openwebui.sources import (
    annotate_answer_citations,
    audit_rank_sources,
    curate_sources_for_answer,
    extract_answer,
    extract_answer_result,
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

    def test_signed_preview_tokens_include_required_claims_and_expire(self) -> None:
        token = sign_preview_payload({"document_id": "doc-1"}, "proxy-secret", now=100)

        payload = verify_preview_token(token, "proxy-secret", now=101)

        self.assertEqual(payload["document_id"], "doc-1")
        self.assertEqual(payload["iat"], 100)
        self.assertEqual(payload["exp"], 1000)
        self.assertEqual(payload["purpose"], "source_preview")
        self.assertEqual(payload["aud"], "openwebui_proxy")
        with self.assertRaisesRegex(ValueError, "expired"):
            verify_preview_token(token, "proxy-secret", now=1000)

    def test_payload_cannot_override_security_claims(self) -> None:
        token = sign_preview_payload(
            {
                "document_id": "doc-1",
                "iat": 0,
                "exp": 999999,
                "purpose": "other",
                "aud": "other",
            },
            "proxy-secret",
            now=100,
            ttl_seconds=10,
        )

        with self.assertRaisesRegex(ValueError, "expired"):
            verify_preview_token(token, "proxy-secret", now=110)

    def test_preview_tokens_are_bound_to_purpose_and_audience(self) -> None:
        token = sign_preview_payload({"document_id": "doc-1"}, "proxy-secret", now=100)

        with self.assertRaisesRegex(ValueError, "purpose"):
            verify_preview_token(
                token,
                "proxy-secret",
                now=101,
                expected_purpose="document_viewer",
            )
        with self.assertRaisesRegex(ValueError, "audience"):
            verify_preview_token(
                token,
                "proxy-secret",
                now=101,
                expected_audience="search_service",
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
        self.assertEqual(sources[0]["source_metadata"]["citation_marker"], "[S1]")
        self.assertEqual(sources[0]["source_metadata"]["provider_citation_marker"], "[ID:0]")
        self.assertEqual(sources[0]["source_metadata"]["page"], 3)
        self.assertEqual(sources[0]["citation_label"], "S1")
        self.assertEqual(sources[0]["source_id"], "S1")
        self.assertEqual(sources[0]["source_metadata"]["locator_quality"], "page")
        self.assertEqual(sources[0]["source_metadata"]["relevance_label"], "hoch")

        token = sources[0]["preview_url"].rsplit("token=", 1)[1]
        preview = verify_preview_token(token, "proxy-secret")
        self.assertEqual(preview["page"], 3)
        self.assertEqual(preview["position"], [[3, 10, 20, 30, 40]])
        self.assertLess(len(token), 500)

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
        preview = verify_preview_token(token, "proxy-secret")
        self.assertEqual(preview["source_path"], "/folder/report final.pdf")
        self.assertEqual(preview["original_url"], sources[0]["original_url"])

    def test_normalize_sources_derives_default_original_file_url(self) -> None:
        settings = self._settings()
        settings.seafile_file_url_template = None

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
            "http://seafile.local/lib/repo-1/file/folder/report%20final.pdf#page=4",
        )

    def test_normalize_sources_keeps_original_url_unavailable_without_repo_or_path(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "content": "Treffer ohne Seafile-Pfad",
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertIsNone(sources[0]["original_url"])

    def test_preview_token_keeps_long_snippets_compact(self) -> None:
        long_text = "Preview-Auszug " * 80

        sources = normalize_sources(
            {"chunks": [{"id": "chunk-1", "document_id": "doc-1", "content": long_text}]},
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        token = sources[0]["preview_url"].rsplit("token=", 1)[1]
        preview = verify_preview_token(token, "proxy-secret")

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

        self.assertIn("[S1](https://connector.example", answer)
        self.assertNotIn("[ID:0]", answer)
        self.assertIn("[ID:9]", answer)

    def test_annotate_answer_citations_maps_provider_marker_variants(self) -> None:
        sources = [
            {
                "source_id": "S1",
                "name": "report.md",
                "preview_url": "https://connector.example/preview",
                "source_metadata": {
                    "provider_citation_id": 0,
                    "citation_id": 0,
                },
            }
        ]

        answer = annotate_answer_citations(
            "Siehe [ID:0], {{source:0}} und ##0$$.",
            sources,
        )

        self.assertEqual(answer.count("[S1](https://connector.example/preview)"), 3)
        self.assertNotIn("[ID:0]", answer)
        self.assertNotIn("{{source:0}}", answer)
        self.assertNotIn("##0$$", answer)

    def test_audit_rank_sources_preserves_existing_source_labels(self) -> None:
        ranked = audit_rank_sources(
            [
                {
                    "source_id": "S1",
                    "rank": 1,
                    "name": "first.md",
                    "text": "Niedrig bewerteter, aber in der Antwort genannter Treffer.",
                    "score": 0.2,
                    "source_metadata": {"rank": 1, "citation_id": 0},
                },
                {
                    "source_id": "S2",
                    "rank": 2,
                    "name": "second.md",
                    "text": "Höher bewerteter Treffer.",
                    "score": 0.95,
                    "source_metadata": {"rank": 2, "citation_id": 1},
                },
            ],
            question="Was steht im ersten Dokument?",
            answer="Der relevante Inhalt steht im ersten Dokument. [S1]",
        )

        self.assertEqual([source["source_id"] for source in ranked], ["S1", "S2"])
        self.assertTrue(ranked[0]["source_metadata"]["used_in_answer"])
        self.assertFalse(ranked[1]["source_metadata"]["used_in_answer"])

    def test_curate_sources_for_answer_hides_uncited_documents(self) -> None:
        sources = [
            {
                "source_id": "S1",
                "name": "mobile-work.pdf",
                "text": "Samstags sind maximal sechs Stunden mobiles Arbeiten möglich.",
                "source_metadata": {"document_id": "doc-mobile", "citation_id": 0},
            },
            {
                "source_id": "S2",
                "name": "mobile-work.pdf",
                "text": "Die Arbeitszeit muss zwischen 06:00 und 19:00 Uhr liegen.",
                "source_metadata": {"document_id": "doc-mobile", "citation_id": 1},
            },
            {
                "source_id": "S3",
                "name": "audit.md",
                "text": "Codex-Audit-Marker ohne Bezug zur Frage.",
                "source_metadata": {"document_id": "doc-audit", "citation_id": 2},
            },
        ]

        curated = curate_sources_for_answer(
            sources,
            answer="Samstags gilt eine Sechs-Stunden-Grenze. [S1]",
        )

        self.assertEqual(
            [source["name"] for source in curated],
            ["mobile-work.pdf", "mobile-work.pdf"],
        )

    def test_exact_marker_source_becomes_s1_and_rewrites_provider_id(self) -> None:
        marker = "ENTERPRISE_CA_RAGFLOW_E2E_20260528T000130Z"
        sources = normalize_sources(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Der Marker steht in der Testdatei [ID:3].",
                            "reference": {
                                "chunks": {
                                    "0": {
                                        "id": "chunk-related-a",
                                        "document_id": "doc-a",
                                        "document_name": "connector-live-check.md",
                                        "content": "Verwandter Live-Check ohne gesuchten Marker.",
                                        "similarity": 0.91,
                                    },
                                    "1": {
                                        "id": "chunk-related-b",
                                        "document_id": "doc-b",
                                        "document_name": "codex_audit_e2e.md",
                                        "content": "Semantisch ähnlicher Audit-Kontext.",
                                        "similarity": 0.88,
                                    },
                                    "3": {
                                        "id": "chunk-exact",
                                        "document_id": "doc-exact",
                                        "document_name": (
                                            "codex_enterprise_ca_e2e_20260528T000130Z.md"
                                        ),
                                        "content": f"Testdatei enthält Marker {marker}.",
                                        "page": 2,
                                        "similarity": 0.71,
                                    },
                                }
                            },
                        }
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
            question=f"Welche Testdatei enthält den Marker `{marker}`?",
            answer="Der Marker steht in der Testdatei [ID:3].",
        )

        self.assertEqual(sources[0]["source_id"], "S1")
        self.assertEqual(sources[0]["name"], "codex_enterprise_ca_e2e_20260528T000130Z.md")
        self.assertEqual(sources[0]["source_metadata"]["provider_citation_id"], 3)
        self.assertEqual(sources[0]["source_metadata"]["source_role"], "primary")
        self.assertEqual(sources[0]["source_metadata"]["match_type"], "exact_string_match")
        self.assertGreaterEqual(sources[0]["source_metadata"]["audit_score"], 0.95)

        answer = annotate_answer_citations(
            "Der Marker steht in der Testdatei [ID:3].",
            sources,
        )

        self.assertIn("[S1](https://connector.example", answer)
        self.assertNotIn("[ID:3]", answer)

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

    def test_normalize_sources_handles_malformed_html_without_regex_fallback(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "document_id": "doc-1",
                        "document_name": "html_fragmente.md",
                        "content": (
                            "<style" * 2000
                            + "<table><tr><td>Alpha</td><td>&Uuml;ber</td></tr></table>"
                            + "<script>hidden()</script>"
                        ),
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertEqual(sources[0]["snippet"], "Alpha | Über")
        self.assertNotIn("hidden", sources[0]["text"])
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

        self.assertIn("**Quellenbasis:** 1 Dokument, 2 Treffer", markdown)
        self.assertIn("### 1. aehnlicher\\_inhalt\\_b.txt", markdown)
        self.assertIn("**Nachweis:** Seite 2", markdown)
        self.assertIn("Relevanz mittel (68%)", markdown)
        self.assertIn("2 Treffer", markdown)
        self.assertIn("Preview öffnen", markdown)
        self.assertIn("Original öffnen", markdown)
        self.assertIn("\\# Überschrift", markdown)
        self.assertIn("Alpha \\| Beta", markdown)
        self.assertNotIn("chunk-a", markdown)

        english = render_sources_markdown(sources, language="en")
        self.assertIn("## Found sources", english)
        self.assertIn("**Source basis:** 1 document, 2 hits", english)
        self.assertIn("**Evidence:**", english)

        spanish = render_sources_markdown(sources, language="es")
        self.assertIn("## Fuentes encontradas", spanish)
        self.assertIn("**Base de fuentes:** 1 documento, 2 resultados", spanish)
        self.assertIn("Abrir vista previa", spanish)

        arabic = render_sources_markdown(sources, language="ar")
        self.assertIn("## المصادر الموجودة", arabic)
        self.assertIn("فتح المعاينة", arabic)

    def test_audit_markdown_shows_evidence_table_without_debug_ids(self) -> None:
        settings = self._settings()
        settings.seafile_file_url_template = (
            "https://seafile.example/lib/{repo_id_quoted}/file{path_quoted}{page_fragment}"
        )
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-pdf",
                        "document_id": "doc-pdf",
                        "document_name": "dienstleister.pdf",
                        "content": "Externe Dienstleister müssen vor Beauftragung geprüft werden.",
                        "positions": [[4, 10, 20, 30, 40]],
                        "similarity": 0.92,
                    },
                    {
                        "id": "chunk-text",
                        "document_id": "doc-text",
                        "document_name": "qm-prozess.md",
                        "content": "Die verantwortliche Stelle muss dokumentiert werden.",
                        "line_start": 88,
                        "line_end": 104,
                        "similarity": 0.73,
                    },
                ]
            },
            settings=settings,
            dataset_id="dataset-1",
            dataset_name="Personalhandbuch",
            files_by_document_id={
                "doc-pdf": {"repo_id": "repo-1", "path": "/Richtlinien/dienstleister.pdf"},
                "doc-text": {"repo_id": "repo-1", "path": "/QM/qm-prozess.md"},
            },
        )

        markdown = render_sources_markdown(
            sources,
            show_scores=False,
            show_debug=False,
            mode="audit",
        )

        self.assertIn("## Nachweise", markdown)
        self.assertIn("**Audit-Status:** retrieval-only", markdown)
        self.assertIn("**Claim-Abdeckung:** 0/1 Aussagen belegt", markdown)
        self.assertIn("### S1 -", markdown)
        self.assertIn("- **Dokument:**", markdown)
        self.assertIn("- **Öffnen:**", markdown)
        self.assertIn("dienstleister.pdf", markdown)
        self.assertIn("Seite 4", markdown)
        self.assertIn("Zeile 88-104", markdown)
        self.assertIn("hoch", markdown)
        self.assertIn("Preview öffnen", markdown)
        self.assertNotIn("chunk-pdf", markdown)
        self.assertNotIn("doc-pdf", markdown)
        self.assertNotIn("dataset-1", markdown)

    def test_audit_markdown_debug_shows_internal_ids_without_secrets(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-debug",
                        "document_id": "doc-debug",
                        "document_name": "debug.pdf",
                        "content": "Debug-Auszug",
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        markdown = render_sources_markdown(
            sources,
            show_scores=True,
            show_debug=True,
            mode="audit",
        )

        self.assertIn("Chunk `chunk-debug`", markdown)
        self.assertIn("Dokument `doc-debug`", markdown)
        self.assertIn("Dataset `dataset-1`", markdown)
        self.assertNotIn("proxy-secret", markdown)

    def test_audit_markdown_does_not_invent_precise_locator(self) -> None:
        sources = normalize_sources(
            {
                "chunks": [
                    {
                        "id": "chunk-only",
                        "document_id": "doc-1",
                        "document_name": "nur-dokument.pdf",
                        "content": "Ein grober Hinweis ohne Seite oder Zeile.",
                    }
                ]
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        markdown = render_sources_markdown(sources, mode="audit")

        self.assertIn("Chunk-Fundstelle", markdown)
        self.assertIn("nicht genauer bestimmbar", markdown)
        self.assertNotIn("Seite 1", markdown)
        self.assertNotIn("Zeile 1", markdown)

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
                    "answer": "RAGFlow liefert eine echte Antwort mit Satzstruktur.",
                    "reference": {"chunks": []},
                },
                "message": "success",
            }
        )

        self.assertEqual(answer, "RAGFlow liefert eine echte Antwort mit Satzstruktur.")

    def test_extract_answer_rejects_generic_message_and_data_content(self) -> None:
        for payload in (
            {"message": "dateiname.md", "sources": [{"content": "Ein Quellenchunk."}]},
            {"data": {"content": "dateiname.md"}, "sources": [{"content": "Ein Quellenchunk."}]},
        ):
            with self.subTest(payload=payload):
                result = extract_answer_result(payload)

                self.assertEqual(result.answer, "")
                self.assertEqual(result.origin, "retrieval_only")

    def test_extract_answer_rejects_backend_error_text(self) -> None:
        for answer in (
            "ERROR: Model(@None) not authorized",
            "**ERROR**: Model(@None) not authorized",
        ):
            with self.subTest(answer=answer):
                result = extract_answer_result(
                    {
                        "data": {"answer": answer},
                        "reference": {
                            "chunks": [
                                {
                                    "document_name": "quelle.md",
                                    "content": "Ein verwertbarer Quellenchunk.",
                                }
                            ]
                        },
                    }
                )

                self.assertEqual(result.answer, "")
                self.assertEqual(result.origin, "retrieval_only")
                self.assertTrue(any("backend error" in warning for warning in result.warnings))

    def test_extract_references_does_not_duplicate_shared_references(self) -> None:
        reference = {
            "chunks": [
                {
                    "id": "chunk-1",
                    "document_id": "doc-1",
                    "document_name": "quelle.md",
                    "content": "Der relevante Satz steht hier.",
                }
            ]
        }

        sources = normalize_sources(
            {
                "choices": [{"message": {"content": "Antwort.", "reference": reference}}],
                "data": {"references": reference},
                "references": reference,
            },
            settings=self._settings(),
            dataset_id="dataset-1",
            dataset_name="Demo",
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source_metadata"]["document_id"], "doc-1")

    def test_source_group_sort_puts_unknown_scores_after_scored_sources(self) -> None:
        markdown = render_sources_markdown(
            [
                {
                    "name": "unknown.md",
                    "text": "Quelle ohne Score.",
                    "source_metadata": {"path": "/unknown.md"},
                },
                {
                    "name": "high.md",
                    "text": "Quelle mit Score.",
                    "score": 0.9,
                    "source_metadata": {"path": "/high.md", "score": 0.9},
                },
            ],
            mode="compact",
        )

        self.assertLess(markdown.index("high.md"), markdown.index("unknown.md"))


if __name__ == "__main__":
    unittest.main()
