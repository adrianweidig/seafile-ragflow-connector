from __future__ import annotations

import gc
import unittest
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import seafile_ragflow_connector.search.server as search_server
from seafile_ragflow_connector.config.settings import SearchServiceSettings
from seafile_ragflow_connector.openwebui.sources import (
    DOCUMENT_VIEWER_PURPOSE,
    SEARCH_PREVIEW_AUDIENCE,
    SOURCE_PREVIEW_PURPOSE,
    sign_preview_payload,
    verify_preview_token,
)
from seafile_ragflow_connector.persistence import Base, get_engine, get_session_factory
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.search.server import (
    SearchBindError,
    SearchPermissionError,
    SearchUser,
    _compose_answer_from_sources,
    _handle_chat,
    _handle_document_proxy,
    _handle_pdf_page_image_proxy,
    _handle_query,
    _search_results_from_ragflow,
    _user_from_headers,
    _validate_trusted_header_boundary,
)
from seafile_ragflow_connector.search.ui import SEARCH_HTML


class SearchServerTests(unittest.TestCase):
    def test_public_production_bind_requires_narrow_trusted_proxy_networks(self) -> None:
        with self.assertRaisesRegex(SearchBindError, "SEARCH_TRUSTED_PROXY_CIDRS"):
            _validate_trusted_header_boundary(_settings())
        with self.assertRaisesRegex(SearchBindError, "must not trust every"):
            _validate_trusted_header_boundary(
                _settings(search_trusted_proxy_cidrs_csv="0.0.0.0/0")
            )

        _validate_trusted_header_boundary(
            _settings(search_trusted_proxy_cidrs_csv="10.20.30.0/28")
        )

    def test_identity_headers_are_accepted_only_from_direct_trusted_peer(self) -> None:
        settings = _settings(search_trusted_proxy_cidrs_csv="10.20.30.0/28")
        headers = {
            "X-Forwarded-User": "olaf",
            "X-Forwarded-Email": "olaf@example.local",
            "X-Forwarded-For": "10.20.30.5",
        }

        user = _user_from_headers(settings, headers, "10.20.30.4")

        self.assertEqual(user.username, "olaf")
        self.assertEqual(user.email, "olaf@example.local")
        with self.assertRaises(SearchPermissionError):
            _user_from_headers(settings, headers, "203.0.113.7")

    def test_ui_contains_required_search_surface(self) -> None:
        self.assertIn("Wissenssuche", SEARCH_HTML)
        self.assertIn('data-theme-choice="light"', SEARCH_HTML)
        self.assertIn('data-theme-choice="dark"', SEARCH_HTML)
        self.assertIn("connector-search-theme", SEARCH_HTML)
        self.assertIn("selectAllProfiles", SEARCH_HTML)
        self.assertIn("clearProfiles", SEARCH_HTML)
        self.assertIn("selectionCount", SEARCH_HTML)
        self.assertIn("Dokumente finden", SEARCH_HTML)
        self.assertIn("Antwort mit Quellen", SEARCH_HTML)
        self.assertIn("Quelle öffnen", SEARCH_HTML)
        self.assertIn("Vorschau", SEARCH_HTML)
        self.assertIn("answer-sources", SEARCH_HTML)
        self.assertIn("answer-source-link", SEARCH_HTML)
        self.assertIn("Originallink", SEARCH_HTML)
        self.assertIn("sourceRail", SEARCH_HTML)
        self.assertIn("sourceHover", SEARCH_HTML)
        self.assertIn("Passage suchen", SEARCH_HTML)
        self.assertIn("documentViewer", SEARCH_HTML)
        self.assertIn("viewerFrame", SEARCH_HTML)
        self.assertIn("viewerTextPreview", SEARCH_HTML)
        self.assertIn('role="document"', SEARCH_HTML)
        self.assertIn("viewerExcerpt", SEARCH_HTML)
        self.assertIn("Trefferpassage", SEARCH_HTML)
        self.assertIn("Passage kopieren", SEARCH_HTML)
        self.assertIn("Zur Passage", SEARCH_HTML)
        self.assertIn("answer-citation-marker", SEARCH_HTML)
        self.assertIn("function renderAnswerText", SEARCH_HTML)
        self.assertIn("function appendAnswerSegments", SEARCH_HTML)
        self.assertIn("function findPassageRange", SEARCH_HTML)
        self.assertIn("function findFocusedPassageRange", SEARCH_HTML)
        self.assertIn("function focusTerms", SEARCH_HTML)
        self.assertIn("function normalizeForMatch", SEARCH_HTML)
        self.assertIn("sourcePassage(source)", SEARCH_HTML)
        self.assertIn("kurzer Trefferanker gelb markiert", SEARCH_HTML)
        self.assertIn("viewer-focus-note", SEARCH_HTML)
        self.assertIn("bestPassageAnchorRange", SEARCH_HTML)
        self.assertIn("passageLineScore", SEARCH_HTML)
        self.assertIn("snippetHighlightTerms", SEARCH_HTML)
        self.assertIn("broadTerms", SEARCH_HTML)
        self.assertIn("citation.sourceIds", SEARCH_HTML)
        self.assertIn("citation.source_ids", SEARCH_HTML)
        self.assertIn("primary-viewer-action", SEARCH_HTML)
        self.assertIn("border-left: 3px solid", SEARCH_HTML)
        self.assertIn(
            '<p class="viewer-passage-text">${snippet ? escapeHtml(snippet)',
            SEARCH_HTML,
        )
        self.assertNotIn("<p class=\"viewer-passage-text\">${snippet ? `<mark>", SEARCH_HTML)
        self.assertIn("requestSubmit", SEARCH_HTML)
        self.assertIn('id="submitSearch"', SEARCH_HTML)
        self.assertIn("composer", SEARCH_HTML)
        self.assertIn("[hidden] { display: none !important; }", SEARCH_HTML)
        self.assertIn("results-details", SEARCH_HTML)
        self.assertIn("Fundstellen prüfen", SEARCH_HTML)
        self.assertIn("inlineSources", SEARCH_HTML)
        self.assertIn("inlineSourceRail", SEARCH_HTML)
        self.assertIn("inline-source-card", SEARCH_HTML)
        self.assertIn("libraryToggle", SEARCH_HTML)
        self.assertIn("is-collapsed", SEARCH_HTML)
        self.assertIn("function syncLibraryCollapse", SEARCH_HTML)
        self.assertIn("function loadTextPreview", SEARCH_HTML)
        self.assertIn("function loadBinaryPreview", SEARCH_HTML)
        self.assertIn("function loadPdfPagePreview", SEARCH_HTML)
        self.assertIn('id="viewerPdfScroll"', SEARCH_HTML)
        self.assertIn('id="viewerPdfPage"', SEARCH_HTML)
        self.assertIn("/api/search/source/document/page-image", SEARCH_HTML)
        self.assertIn("URL.createObjectURL", SEARCH_HTML)
        self.assertIn("source.viewer_kind === 'download'", SEARCH_HTML)
        self.assertIn("Datei herunterladen", SEARCH_HTML)
        self.assertNotIn("Datei öffnen", SEARCH_HTML)
        self.assertIn("source.viewer_kind === 'text'", SEARCH_HTML)
        self.assertIn("viewerExcerptEl.classList.toggle('is-expanded')", SEARCH_HTML)
        self.assertIn(".search-panel > *", SEARCH_HTML)
        self.assertIn("flex-direction: column", SEARCH_HTML)
        self.assertIn("grid-template-rows: auto clamp(170px, 22vh, 260px) auto", SEARCH_HTML)
        self.assertIn("@media (max-width: 1280px)", SEARCH_HTML)
        self.assertIn(".sources-panel { display: none; }", SEARCH_HTML)
        self.assertNotIn("grid-template-rows: auto minmax(220px, 34vh) auto", SEARCH_HTML)
        self.assertNotIn("min-height: 62px", SEARCH_HTML)
        self.assertIn("showToast", SEARCH_HTML)
        self.assertIn('id="toast"', SEARCH_HTML)
        self.assertIn("frame-src 'self' blob:", search_server.SEARCH_CONTENT_SECURITY_POLICY)

    def test_query_calls_ragflow_only_for_allowed_profiles(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        seen_profile_ids: list[list[str]] = []

        def fake_authz(
            _settings: SearchServiceSettings,
            _user: SearchUser,
            profile_ids: list[str],
        ) -> dict[str, list[dict[str, str]]]:
            seen_profile_ids.append(profile_ids)
            allowed = []
            denied = []
            for profile_id in profile_ids:
                if profile_id == "repo-anleitungen":
                    allowed.append(
                        {
                            "profile_id": "repo-anleitungen",
                            "repo_id": "repo-anleitungen",
                            "ragflow_dataset_id": "dataset-anleitungen",
                            "display_name": "Anleitungen",
                        }
                    )
                else:
                    denied.append(
                        {
                            "profile_id": profile_id,
                            "repo_id": profile_id,
                            "reason": "user_not_in_library_acl",
                        }
                    )
            return {"allowed": allowed, "denied": denied}

        search_server._authz_filter_profiles = fake_authz
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.retrieval_options = []
        try:
            result = _handle_query(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen", "repo-geheim"],
                    "question": "FI Typ B Wartungsintervall",
                    "top_k": 10,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(_FakeRAGFlowClient.calls, ["dataset-anleitungen"])
        self.assertEqual(_FakeRAGFlowClient.retrieval_options[0]["top_k"], 1024)
        self.assertEqual(_FakeRAGFlowClient.retrieval_options[0]["page_size"], 10)
        self.assertTrue(_FakeRAGFlowClient.retrieval_options[0]["keyword"])
        self.assertTrue(_FakeRAGFlowClient.retrieval_options[0]["highlight"])
        self.assertEqual(seen_profile_ids, [["repo-anleitungen", "repo-geheim"]])
        self.assertEqual(result["diagnostics"]["profiles_allowed"], 1)
        self.assertEqual(result["diagnostics"]["profiles_denied"], 1)
        self.assertEqual(result["diagnostics"]["search_template_source"], "builtin")
        self.assertEqual(result["diagnostics"]["candidate_top_k"], 1024)
        self.assertEqual(result["results"][0]["document_name"], "Handbuch FI Typ B.pdf")
        self.assertEqual(result["results"][0]["source_id"], "S1")
        self.assertEqual(result["results"][0]["citation_label"], "S1")
        self.assertEqual(result["results"][0]["id"], "S1")
        self.assertEqual(result["results"][0]["label"], "S1")
        self.assertEqual(result["results"][0]["fileName"], "Handbuch FI Typ B.pdf")
        self.assertEqual(result["results"][0]["libraryName"], "Anleitungen")
        self.assertEqual(result["results"][0]["contentType"], "application/pdf")
        self.assertEqual(
            result["results"][0]["passageTextExact"],
            "Wartungsintervall alle 6 Monate.",
        )
        self.assertEqual(result["results"][0]["locator"]["page"], 12)
        self.assertEqual(result["results"][0]["locator"]["quality"], "page")
        self.assertTrue(result["results"][0]["preview_url"].startswith("/api/search/source/preview?token="))
        token = unquote(result["results"][0]["preview_url"].rsplit("token=", 1)[1])
        preview = verify_preview_token(
            token,
            settings.effective_search_source_preview_secret,
            expected_purpose=SOURCE_PREVIEW_PURPOSE,
            expected_audience=SEARCH_PREVIEW_AUDIENCE,
        )
        self.assertEqual(preview["document_name"], "Handbuch FI Typ B.pdf")
        self.assertEqual(preview["citation_label"], "S1")
        self.assertTrue(
            result["results"][0]["viewer_url"].startswith("/api/search/source/document?token=")
        )
        viewer_token = unquote(
            result["results"][0]["viewer_url"].rsplit("token=", 1)[1].split("#", 1)[0]
        )
        viewer_payload = verify_preview_token(
            viewer_token,
            settings.effective_search_source_preview_secret,
            expected_purpose=DOCUMENT_VIEWER_PURPOSE,
            expected_audience=SEARCH_PREVIEW_AUDIENCE,
        )
        self.assertEqual(viewer_payload["repo_id"], "repo-anleitungen")
        self.assertEqual(viewer_payload["source_path"], "/Anleitungen/FI/Handbuch FI Typ B.pdf")
        self.assertEqual(result["results"][0]["viewer_kind"], "pdf")
        self.assertIn("Bildvorschau", result["results"][0]["viewer_message"])

    def test_subset_selection_queries_only_checked_libraries(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        seen_profile_ids: list[list[str]] = []

        def fake_authz(
            _settings: SearchServiceSettings,
            _user: SearchUser,
            profile_ids: list[str],
        ) -> dict[str, list[dict[str, str]]]:
            seen_profile_ids.append(profile_ids)
            allowed = [
                {
                    "profile_id": profile_id,
                    "repo_id": profile_id,
                    "ragflow_dataset_id": profile_id.replace("repo-", "dataset-"),
                    "display_name": profile_id.replace("repo-", "").title(),
                }
                for profile_id in profile_ids
            ]
            return {"allowed": allowed, "denied": []}

        search_server._authz_filter_profiles = fake_authz
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.retrieval_options = []
        try:
            result = _handle_query(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen", "repo-wiki"],
                    "question": "FI Typ B Wartungsintervall",
                    "top_k": 10,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(seen_profile_ids, [["repo-anleitungen", "repo-wiki"]])
        self.assertEqual(_FakeRAGFlowClient.calls, ["dataset-anleitungen", "dataset-wiki"])
        self.assertEqual(result["diagnostics"]["profiles_allowed"], 2)

    def test_empty_selection_raises_before_authz_or_ragflow(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        authz_called = False

        def fake_authz(
            _settings: SearchServiceSettings,
            _user: SearchUser,
            _profile_ids: list[str],
        ) -> dict[str, list[dict[str, str]]]:
            nonlocal authz_called
            authz_called = True
            return {"allowed": [], "denied": []}

        search_server._authz_filter_profiles = fake_authz
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.retrieval_options = []
        try:
            with self.assertRaises(SearchPermissionError):
                _handle_query(
                    settings,
                    SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                    {
                        "profile_ids": [],
                        "question": "FI Typ B Wartungsintervall",
                        "top_k": 8,
                    },
                )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertFalse(authz_called)
        self.assertEqual(_FakeRAGFlowClient.calls, [])

    def test_completely_denied_selection_raises_before_ragflow(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [],
            "denied": [{"profile_id": "repo-geheim", "reason": "user_not_in_library_acl"}],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.retrieval_options = []
        try:
            with self.assertRaises(SearchPermissionError):
                _handle_query(
                    settings,
                    SearchUser(username="alfred", email="alfred@example.local", display_name=None),
                    {
                        "profile_ids": ["repo-geheim"],
                        "question": "Geheim",
                        "top_k": 8,
                    },
                )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(_FakeRAGFlowClient.calls, [])

    def test_ragflow_document_keyword_and_doc_aggs_are_user_facing_source_fields(self) -> None:
        results = _search_results_from_ragflow(
            {
                "chunks": [
                    {
                        "document_id": "doc-1",
                        "document_keyword": "acl-live-test.md",
                        "content": "Eindeutiger Suchbegriff ACLOHNECONFIG20260617.",
                        "similarity": 0.73,
                        "positions": [[1, 0, 0, 0, 0]],
                    },
                    {
                        "document_id": "doc-2",
                        "content": "Treffer aus Dokument-Aggregaten.",
                        "similarity": 0.62,
                    },
                ],
                "doc_aggs": [
                    {"doc_id": "doc-2", "doc_name": "aggregated-name.pdf"},
                ],
            },
            {
                "repo_id": "repo-anleitungen",
                "ragflow_dataset_id": "dataset-anleitungen",
                "display_name": "Anleitungen",
            },
        )

        self.assertEqual(results[0]["document_name"], "acl-live-test.md")
        self.assertEqual(results[0]["source_path"], "/Anleitungen/acl-live-test.md")
        self.assertEqual(results[0]["page"], 1)
        self.assertEqual(results[1]["document_name"], "aggregated-name.pdf")
        self.assertEqual(results[1]["source_path"], "/Anleitungen/aggregated-name.pdf")

    def test_ragflow_display_path_is_repaired_from_state_db(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "state.db"
            database_url = f"sqlite:///{db_path.as_posix()}"
            engine = get_engine(database_url)
            Base.metadata.create_all(engine)
            session_factory = get_session_factory(database_url)
            with session_factory() as session:
                session.add(
                    Library(
                        repo_id="repo-betrieb",
                        name="Testnetz Admin Betrieb",
                        name_slug="testnetz-admin-betrieb",
                    )
                )
                session.add(
                    File(
                        repo_id="repo-betrieb",
                        path="/codex-filetype-smoke/codex-dateityp-smoke.pdf",
                        normalized_path="/codex-filetype-smoke/codex-dateityp-smoke.pdf",
                        ragflow_document_id="doc-pdf",
                        ragflow_document_name="codex-dateityp-smoke.pdf",
                        ingestion_strategy="direct",
                        sync_status="synced",
                    )
                )
                session.commit()

            search_server._search_state_session_factory.cache_clear()
            try:
                results = _search_results_from_ragflow(
                    {
                        "chunks": [
                            {
                                "document_id": "doc-pdf",
                                "content": "CODEX-DATEITYP-SMOKE-20260630-PDF",
                                "similarity": 0.73,
                            }
                        ],
                        "doc_aggs": [
                            {"doc_id": "doc-pdf", "doc_name": "codex-dateityp-smoke.pdf"},
                        ],
                    },
                    {
                        "repo_id": "repo-betrieb",
                        "ragflow_dataset_id": "dataset-betrieb",
                        "display_name": "Testnetz Admin Betrieb",
                    },
                    settings=SearchServiceSettings(
                        database_url=database_url,
                        search_authz_base_url="http://connector-controller:8080",
                        search_authz_shared_secret="authz-secret",
                        search_ragflow_base_url="http://ragflow:9380",
                        search_ragflow_api_key="ragflow-key",
                    ),
                )
            finally:
                state_factory = search_server._search_state_session_factory(database_url)
                state_bind = getattr(state_factory, "bind", None)
                if state_bind is not None:
                    state_bind.dispose()
                search_server._search_state_session_factory.cache_clear()
                test_bind = getattr(session_factory, "bind", None)
                if test_bind is not None:
                    test_bind.dispose()
                engine.dispose()
                gc.collect()

        self.assertEqual(
            results[0]["source_path"],
            "/codex-filetype-smoke/codex-dateityp-smoke.pdf",
        )

    def test_projected_text_results_hide_ingestion_header_and_link_to_seafile(self) -> None:
        results = _search_results_from_ragflow(
            {
                "chunks": [
                    {
                        "document_name": "4c6f30f466699b19__admin-handbuch-test.md.txt",
                        "content": (
                            "Source path: /admin-handbuch-test.md\n"
                            "Source path hash: 4c6f30f466699b19\n\n"
                            "----- BEGIN SOURCE CONTENT -----\n"
                            "# Testnetz Admin Handbuch\n"
                            "TESTNETZADMIN-HANDBUCH-20260617 Wartungsintervall.\n"
                            "----- END SOURCE CONTENT -----"
                        ),
                        "similarity": 0.73,
                        "positions": [[2, 0, 0, 0, 0]],
                    }
                ],
            },
            {
                "repo_id": "repo-anleitungen",
                "ragflow_dataset_id": "dataset-anleitungen",
                "display_name": "Anleitungen",
            },
            settings=SearchServiceSettings(
                search_authz_base_url="http://connector-controller:8080",
                search_authz_shared_secret="authz-secret",
                search_ragflow_base_url="http://ragflow:9380",
                search_ragflow_api_key="ragflow-key",
                search_seafile_public_base_url="https://sea.top.secret",
            ),
        )

        self.assertEqual(results[0]["document_name"], "admin-handbuch-test.md")
        self.assertEqual(results[0]["source_path"], "/admin-handbuch-test.md")
        self.assertIn("TESTNETZADMIN-HANDBUCH-20260617", results[0]["snippet"])
        self.assertNotIn("Source path", results[0]["snippet"])
        self.assertNotIn("Source path hash", results[0]["snippet"])
        self.assertNotIn("BEGIN SOURCE CONTENT", results[0]["snippet"])
        self.assertEqual(
            results[0]["open_url"],
            "https://sea.top.secret/lib/repo-anleitungen/file/admin-handbuch-test.md#page=2",
        )

    def test_chat_answer_is_not_raw_s_number_source_dump(self) -> None:
        answer = _compose_answer_from_sources(
            "Test",
            [
                {
                    "citation_label": "S1",
                    "document_name": "admin-handbuch-test.md",
                    "dataset_name": "Anleitungen",
                    "snippet": "TESTNETZADMIN-HANDBUCH-20260617 Wartungsintervall.",
                }
            ],
        )

        self.assertIn("Wartungsintervall.", answer)
        self.assertIn("[S1]", answer)
        self.assertNotIn("TESTNETZADMIN-HANDBUCH-20260617", answer)
        self.assertNotIn("liefern die freigegebenen Quellen folgende belastbare", answer)
        self.assertNotIn("Ich habe noch keinen separaten KI-Antworttext generiert", answer)

    def test_chat_answer_fallback_uses_synthesized_source_markers(self) -> None:
        answer = _compose_answer_from_sources(
            "test",
            [
                {
                    "citation_label": "S1",
                    "document_name": "user-handbuch-test.md",
                    "dataset_name": "Testnetz User Handbuch",
                    "snippet": (
                        "# Testnetz User Handbuch TESTNETZUSER-HANDBUCH-20260617 "
                        "Dieses Dokument dient normalen Testnetz-Nutzern."
                    ),
                },
                {
                    "citation_label": "S2",
                    "document_name": "admin-handbuch-test.md",
                    "dataset_name": "Testnetz Admin Handbuch",
                    "snippet": (
                        "# Testnetz Admin Handbuch TESTNETZADMIN-HANDBUCH-20260617 "
                        "Dieses Labor-Dokument ist nur für die Admin-Gruppe freigegeben."
                    ),
                },
            ],
        )

        self.assertIn("kurze Zusammenfassung", answer)
        self.assertIn("[S1]", answer)
        self.assertIn("[S2]", answer)
        self.assertIn("Dieses Dokument dient normalen Testnetz-Nutzern.", answer)
        self.assertNotIn("TESTNETZUSER-HANDBUCH-20260617", answer)
        self.assertNotIn("TESTNETZADMIN-HANDBUCH-20260617", answer)

    def test_answer_generation_uses_exact_passage_not_display_snippet(self) -> None:
        sources = [
            {
                "citation_label": "S1",
                "document_name": "admin-handbuch-test.md",
                "dataset_name": "Testnetz Admin Handbuch",
                "snippet": "Gekürzte Kartenfassung.",
                "passage_text_exact": (
                    "Die vollständige Passage erklärt, dass GS_Testnetz_Admin "
                    "das Admin-Handbuch sehen darf."
                ),
            }
        ]

        prompt = search_server._answer_source_prompt(sources)
        answer = _compose_answer_from_sources("Wer darf das sehen?", sources)

        self.assertIn("GS_Testnetz_Admin", prompt)
        self.assertNotIn("Gekürzte Kartenfassung", prompt)
        self.assertIn("GS_Testnetz_Admin", answer)
        self.assertIn("[S1]", answer)

    def test_chat_uses_ragflow_answer_chat_after_retrieval(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.answer_messages = []
        _FakeRAGFlowClient.chats = [{"id": "chat-answer", "name": "connector_search_answer"}]
        _FakeRAGFlowClient.answer_error = None
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(result["answer"]["mode"], "ragflow_chat")
        self.assertIn("6 Monate [S1]", result["answer"]["text"])
        prompt = _FakeRAGFlowClient.answer_messages[-1][-1]["content"]
        self.assertIn("[S1]", prompt)
        self.assertIn("Wartungsintervall alle 6 Monate.", prompt)

    def test_chat_uses_openai_compatible_answer_when_configured(self) -> None:
        settings = _settings(
            search_answer_llm_base_url="http://llm.local/v1",
            search_answer_llm_model="local-model",
            search_answer_llm_api_key="llm-key",
        )
        original_authz = search_server._authz_filter_profiles
        original_ragflow_client = search_server.RAGFlowClient
        original_httpx_client = search_server.httpx.Client
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        search_server.httpx.Client = _FakeOpenAIClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.answer_messages = []
        _FakeOpenAIClient.reset()
        _FakeOpenAIClient.response_payload = {
            "choices": [
                {
                    "message": {
                        "content": "Das Wartungsintervall beträgt 6 Monate [S1].",
                    }
                }
            ]
        }
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_ragflow_client  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]

        self.assertEqual(result["answer"]["mode"], "openai_compatible")
        self.assertIn("6 Monate [S1]", result["answer"]["text"])
        self.assertEqual(_FakeRAGFlowClient.calls, ["dataset-anleitungen"])
        self.assertEqual(_FakeRAGFlowClient.answer_messages, [])
        self.assertEqual(len(_FakeOpenAIClient.requests), 1)
        request = _FakeOpenAIClient.requests[0]
        self.assertEqual(request["url"], "http://llm.local/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer llm-key")
        self.assertEqual(request["json"]["model"], "local-model")
        self.assertIn("[S1]", request["json"]["messages"][-1]["content"])
        self.assertTrue(result["diagnostics"]["answer_generation"]["llm_attempted"])
        self.assertEqual(result["diagnostics"]["answer_generation"]["llm_model"], "local-model")

    def test_chat_adds_bracketed_sources_to_openai_answer_without_markers(self) -> None:
        settings = _settings(
            search_answer_llm_base_url="http://llm.local/v1/chat/completions",
            search_answer_llm_model="local-model",
        )
        original_authz = search_server._authz_filter_profiles
        original_ragflow_client = search_server.RAGFlowClient
        original_httpx_client = search_server.httpx.Client
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        search_server.httpx.Client = _FakeOpenAIClient  # type: ignore[assignment]
        _FakeOpenAIClient.reset()
        _FakeOpenAIClient.response_payload = {
            "choices": [
                {
                    "message": {
                        "content": "Das Wartungsintervall beträgt 6 Monate.",
                    }
                }
            ]
        }
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_ragflow_client  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]

        self.assertEqual(result["answer"]["mode"], "openai_compatible")
        self.assertIn("Quellen: [S1].", result["answer"]["text"])
        self.assertEqual(_FakeOpenAIClient.requests[0]["url"], "http://llm.local/v1/chat/completions")

    def test_chat_llm_error_falls_back_without_losing_sources(self) -> None:
        settings = _settings(
            search_answer_llm_base_url="http://llm.local/v1",
            search_answer_llm_model="local-model",
        )
        original_authz = search_server._authz_filter_profiles
        original_ragflow_client = search_server.RAGFlowClient
        original_httpx_client = search_server.httpx.Client
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        search_server.httpx.Client = _FakeOpenAIClient  # type: ignore[assignment]
        _FakeOpenAIClient.reset()
        _FakeOpenAIClient.error = search_server.httpx.ConnectError("unreachable")
        _FakeRAGFlowClient.chats = []
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_ragflow_client  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]
            _FakeRAGFlowClient.chats = [
                {"id": "chat-answer", "name": "connector_search_answer"},
            ]

        self.assertEqual(result["answer"]["mode"], "source_summary_fallback")
        self.assertIn("Wartungsintervall alle 6 Monate.", result["answer"]["text"])
        self.assertIn("[S1]", result["answer"]["text"])
        diagnostics = result["diagnostics"]["answer_generation"]
        self.assertEqual(diagnostics["fallback_reason"], "answer_chat_not_found")
        self.assertEqual(diagnostics["llm_fallback_reason"], "llm_ConnectError")

    def test_chat_adds_bracketed_sources_to_answer_without_markers(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.answer_messages = []
        _FakeRAGFlowClient.chats = [{"id": "chat-answer", "name": "connector_search_answer"}]
        _FakeRAGFlowClient.answer_error = None
        _FakeRAGFlowClient.answer_content = "Das Wartungsintervall beträgt 6 Monate."
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]
            _FakeRAGFlowClient.answer_content = "Das Wartungsintervall beträgt 6 Monate [S1]."

        self.assertEqual(result["answer"]["mode"], "ragflow_chat")
        self.assertIn("Quellen: [S1].", result["answer"]["text"])
        self.assertNotIn("Quellen: S1.", result["answer"]["text"])

    def test_chat_falls_back_to_source_summary_when_answer_chat_missing(self) -> None:
        settings = _settings()
        original_authz = search_server._authz_filter_profiles
        original_client = search_server.RAGFlowClient
        search_server._authz_filter_profiles = lambda _settings, _user, _profile_ids: {
            "allowed": [
                {
                    "profile_id": "repo-anleitungen",
                    "repo_id": "repo-anleitungen",
                    "ragflow_dataset_id": "dataset-anleitungen",
                    "display_name": "Anleitungen",
                }
            ],
            "denied": [],
        }
        search_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.calls = []
        _FakeRAGFlowClient.answer_messages = []
        _FakeRAGFlowClient.chats = []
        _FakeRAGFlowClient.answer_error = None
        try:
            result = _handle_chat(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                {
                    "profile_ids": ["repo-anleitungen"],
                    "question": "Wie oft Wartung?",
                    "top_k": 8,
                },
            )
        finally:
            search_server._authz_filter_profiles = original_authz
            search_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(result["answer"]["mode"], "source_summary_fallback")
        self.assertIn("Wartungsintervall alle 6 Monate.", result["answer"]["text"])
        self.assertIn("[S1]", result["answer"]["text"])
        self.assertEqual(
            result["diagnostics"]["answer_generation"]["fallback_reason"],
            "answer_chat_not_found",
        )

    def test_document_proxy_rejects_expired_viewer_token_before_authz(self) -> None:
        settings = _settings()
        token = sign_preview_payload(
            {
                "repo_id": "repo-anleitungen",
                "source_path": "/report.pdf",
                "dataset_id": "dataset-anleitungen",
                "expires_at": 1,
            },
            settings.effective_search_source_preview_secret,
            now=1,
            ttl_seconds=1,
            purpose=DOCUMENT_VIEWER_PURPOSE,
            audience=SEARCH_PREVIEW_AUDIENCE,
        )

        with self.assertRaises(ValueError):
            _handle_document_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                token,
            )

    def test_document_proxy_rejects_content_length_before_reading_body(self) -> None:
        settings = _settings(search_document_viewer_max_mb=1)
        token = sign_preview_payload(
            {
                "repo_id": "repo-anleitungen",
                "source_path": "/Anleitungen/report.pdf",
                "dataset_id": "dataset-anleitungen",
            },
            settings.effective_search_source_preview_secret,
            purpose=DOCUMENT_VIEWER_PURPOSE,
            audience=SEARCH_PREVIEW_AUDIENCE,
        )
        original_authz_check = search_server._authz_check_source
        original_httpx_client = search_server.httpx.Client

        class _OversizedResponse:
            status_code = 200
            headers = {"Content-Length": str(1024 * 1024 + 1)}

            def __enter__(self) -> _OversizedResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def iter_bytes(self) -> object:
                raise AssertionError("oversized response body must not be read")

        class _FakeDocumentClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __enter__(self) -> _FakeDocumentClient:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def stream(self, *args: object, **kwargs: object) -> _OversizedResponse:
                return _OversizedResponse()

        try:
            search_server._authz_check_source = lambda *args, **kwargs: None  # type: ignore[assignment]
            search_server.httpx.Client = _FakeDocumentClient  # type: ignore[assignment]
            body, status, _headers = _handle_document_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                token,
            )
        finally:
            search_server._authz_check_source = original_authz_check  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]

        self.assertEqual(status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self.assertIn(b"document too large", body)

    def test_document_proxy_forces_pdf_inline_even_if_upstream_sends_attachment(self) -> None:
        settings = _settings()
        token = sign_preview_payload(
            {
                "repo_id": "repo-anleitungen",
                "source_path": "/Anleitungen/report.pdf",
                "dataset_id": "dataset-anleitungen",
            },
            settings.effective_search_source_preview_secret,
            purpose=DOCUMENT_VIEWER_PURPOSE,
            audience=SEARCH_PREVIEW_AUDIENCE,
        )
        original_authz_check = search_server._authz_check_source
        original_httpx_client = search_server.httpx.Client

        class _FakeDocumentResponse:
            status_code = 200
            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="report.pdf"',
            }
            content = b"%PDF-1.3\n"
            is_error = False

            def __enter__(self) -> _FakeDocumentResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> object:
                return iter((self.content,))

        class _FakeDocumentClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __enter__(self) -> _FakeDocumentClient:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def stream(self, *args: object, **kwargs: object) -> _FakeDocumentResponse:
                return _FakeDocumentResponse()

        try:
            search_server._authz_check_source = lambda *args, **kwargs: None  # type: ignore[assignment]
            search_server.httpx.Client = _FakeDocumentClient  # type: ignore[assignment]

            body, status, headers = _handle_document_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                token,
            )
        finally:
            search_server._authz_check_source = original_authz_check  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]

        self.assertEqual(body, b"%PDF-1.3\n")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="report.pdf"')

    def test_pdf_page_image_proxy_renders_png_after_authz_document_fetch(self) -> None:
        settings = _settings()
        original_document_proxy = search_server._handle_document_proxy
        original_renderer = search_server._render_pdf_page_png
        seen: dict[str, object] = {}

        def fake_document_proxy(
            _settings: SearchServiceSettings,
            _user: SearchUser,
            token: str | None,
        ) -> tuple[bytes, HTTPStatus, dict[str, str]]:
            seen["token"] = token
            return (
                b"%PDF-1.3\n",
                HTTPStatus.OK,
                {
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'inline; filename="report.pdf"',
                },
            )

        def fake_renderer(body: bytes, page: int) -> bytes:
            seen["body"] = body
            seen["page"] = page
            return b"\x89PNG\r\n\x1a\n"

        try:
            search_server._handle_document_proxy = fake_document_proxy  # type: ignore[assignment]
            search_server._render_pdf_page_png = fake_renderer  # type: ignore[assignment]

            body, status, headers = _handle_pdf_page_image_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                "signed-token",
                "2",
            )
        finally:
            search_server._handle_document_proxy = original_document_proxy  # type: ignore[assignment]
            search_server._render_pdf_page_png = original_renderer  # type: ignore[assignment]

        self.assertEqual(seen["token"], "signed-token")
        self.assertEqual(seen["body"], b"%PDF-1.3\n")
        self.assertEqual(seen["page"], 2)
        self.assertEqual(body, b"\x89PNG\r\n\x1a\n")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="pdf-page-2.png"')

    def test_document_proxy_keeps_office_files_as_explicit_downloads(self) -> None:
        settings = _settings()
        token = sign_preview_payload(
            {
                "repo_id": "repo-anleitungen",
                "source_path": "/Anleitungen/report.docx",
                "dataset_id": "dataset-anleitungen",
            },
            settings.effective_search_source_preview_secret,
            purpose=DOCUMENT_VIEWER_PURPOSE,
            audience=SEARCH_PREVIEW_AUDIENCE,
        )
        original_authz_check = search_server._authz_check_source
        original_httpx_client = search_server.httpx.Client

        class _FakeDocumentResponse:
            status_code = 200
            headers = {
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "Content-Disposition": 'inline; filename="report.docx"',
            }
            content = b"PK\x03\x04"
            is_error = False

            def __enter__(self) -> _FakeDocumentResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> object:
                return iter((self.content,))

        class _FakeDocumentClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __enter__(self) -> _FakeDocumentClient:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def stream(self, *args: object, **kwargs: object) -> _FakeDocumentResponse:
                return _FakeDocumentResponse()

        try:
            search_server._authz_check_source = lambda *args, **kwargs: None  # type: ignore[assignment]
            search_server.httpx.Client = _FakeDocumentClient  # type: ignore[assignment]

            body, status, headers = _handle_document_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                token,
            )
        finally:
            search_server._authz_check_source = original_authz_check  # type: ignore[assignment]
            search_server.httpx.Client = original_httpx_client  # type: ignore[assignment]

        self.assertEqual(body, b"PK\x03\x04")
        self.assertEqual(status, 200)
        self.assertIn("wordprocessingml.document", headers["Content-Type"])
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="report.docx"')


def _settings(**overrides: object) -> SearchServiceSettings:
    values: dict[str, object] = {
        "search_authz_base_url": "http://connector-controller:8080",
        "search_authz_shared_secret": "authz-secret",
        "search_ragflow_base_url": "http://ragflow:9380",
        "search_ragflow_api_key": "ragflow-key",
    }
    values.update(overrides)
    return SearchServiceSettings(**values)


class _FakeRAGFlowClient:
    calls: list[str] = []
    retrieval_options: list[dict[str, object]] = []
    chats: list[dict[str, str]] = [{"id": "chat-answer", "name": "connector_search_answer"}]
    answer_messages: list[list[dict[str, object]]] = []
    answer_error: Exception | None = None
    answer_content: str = "Das Wartungsintervall beträgt 6 Monate [S1]."

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def retrieve_chunks(self, **kwargs: object) -> dict[str, object]:
        dataset_id = str(kwargs["dataset_id"])
        self.__class__.calls.append(dataset_id)
        self.__class__.retrieval_options.append(dict(kwargs.get("retrieval_options") or {}))
        return {
            "chunks": [
                {
                    "document_name": "Handbuch FI Typ B.pdf",
                    "content": "Wartungsintervall alle 6 Monate.",
                    "path": "/Anleitungen/FI/Handbuch FI Typ B.pdf",
                    "score": 0.82,
                    "page": 12,
                }
            ]
        }

    def list_chats(
        self,
        *,
        name: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, str]]:
        del chat_id
        if name is None:
            return list(self.__class__.chats)
        return [chat for chat in self.__class__.chats if chat.get("name") == name]

    def chat_completion(
        self,
        *,
        chat_id: str,
        messages: list[dict[str, object]],
        model: str = "model",
        stream: bool = False,
    ) -> dict[str, object]:
        del chat_id, model, stream
        self.__class__.answer_messages.append(messages)
        if self.__class__.answer_error is not None:
            raise self.__class__.answer_error
        return {
            "choices": [
                {
                    "message": {
                        "content": self.__class__.answer_content,
                    }
                }
            ]
        }

    def close(self) -> None:
        pass


class _FakeOpenAIResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class _FakeOpenAIClient:
    requests: list[dict[str, object]] = []
    response_payload: dict[str, object] = {}
    error: Exception | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self) -> _FakeOpenAIClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> _FakeOpenAIResponse:
        if self.__class__.error is not None:
            raise self.__class__.error
        self.__class__.requests.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "client_kwargs": self.kwargs,
            }
        )
        return _FakeOpenAIResponse(self.__class__.response_payload)

    @classmethod
    def reset(cls) -> None:
        cls.requests = []
        cls.response_payload = {
            "choices": [
                {
                    "message": {
                        "content": "Das Wartungsintervall beträgt 6 Monate [S1].",
                    }
                }
            ]
        }
        cls.error = None


if __name__ == "__main__":
    unittest.main()
