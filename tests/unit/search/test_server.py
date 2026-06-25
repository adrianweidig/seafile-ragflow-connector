from __future__ import annotations

import unittest
from urllib.parse import unquote

import seafile_ragflow_connector.search.server as search_server
from seafile_ragflow_connector.config.settings import SearchServiceSettings
from seafile_ragflow_connector.openwebui.sources import sign_preview_payload, verify_preview_token
from seafile_ragflow_connector.search.server import (
    SearchPermissionError,
    SearchUser,
    _compose_answer_from_sources,
    _handle_chat,
    _handle_document_proxy,
    _handle_query,
    _search_results_from_ragflow,
)
from seafile_ragflow_connector.search.ui import SEARCH_HTML


class SearchServerTests(unittest.TestCase):
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
        self.assertIn("viewerExcerpt", SEARCH_HTML)
        self.assertIn("composer", SEARCH_HTML)

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
        self.assertEqual(result["results"][0]["locator"]["page"], 12)
        self.assertEqual(result["results"][0]["locator"]["quality"], "page")
        self.assertTrue(result["results"][0]["preview_url"].startswith("/api/search/source/preview?token="))
        token = unquote(result["results"][0]["preview_url"].rsplit("token=", 1)[1])
        preview = verify_preview_token(token, settings.effective_search_source_preview_secret)
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
        )
        self.assertEqual(viewer_payload["repo_id"], "repo-anleitungen")
        self.assertEqual(viewer_payload["source_path"], "/Anleitungen/FI/Handbuch FI Typ B.pdf")
        self.assertEqual(result["results"][0]["viewer_kind"], "pdf")
        self.assertIn("native", result["results"][0]["viewer_message"])

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

        self.assertIn("TESTNETZADMIN-HANDBUCH-20260617", answer)
        self.assertIn("[S1]", answer)
        self.assertNotIn("Ich habe noch keinen separaten KI-Antworttext generiert", answer)

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
        )

        with self.assertRaises(ValueError):
            _handle_document_proxy(
                settings,
                SearchUser(username="olaf", email="olaf@example.local", display_name=None),
                token,
            )


def _settings() -> SearchServiceSettings:
    return SearchServiceSettings(
        search_authz_base_url="http://connector-controller:8080",
        search_authz_shared_secret="authz-secret",
        search_ragflow_base_url="http://ragflow:9380",
        search_ragflow_api_key="ragflow-key",
    )


class _FakeRAGFlowClient:
    calls: list[str] = []
    retrieval_options: list[dict[str, object]] = []
    chats: list[dict[str, str]] = [{"id": "chat-answer", "name": "connector_search_answer"}]
    answer_messages: list[list[dict[str, object]]] = []
    answer_error: Exception | None = None

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
                        "content": "Das Wartungsintervall beträgt 6 Monate [S1].",
                    }
                }
            ]
        }

    def close(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
