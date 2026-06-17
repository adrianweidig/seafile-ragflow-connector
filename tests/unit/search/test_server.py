from __future__ import annotations

import unittest

import seafile_ragflow_connector.search.server as search_server
from seafile_ragflow_connector.config.settings import SearchServiceSettings
from seafile_ragflow_connector.search.server import (
    SearchPermissionError,
    SearchUser,
    _compose_answer_from_sources,
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
        self.assertEqual(seen_profile_ids, [["repo-anleitungen", "repo-geheim"]])
        self.assertEqual(result["diagnostics"]["profiles_allowed"], 1)
        self.assertEqual(result["diagnostics"]["profiles_denied"], 1)
        self.assertEqual(result["results"][0]["document_name"], "Handbuch FI Typ B.pdf")

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
                    "document_name": "admin-handbuch-test.md",
                    "dataset_name": "Anleitungen",
                    "snippet": "TESTNETZADMIN-HANDBUCH-20260617 Wartungsintervall.",
                }
            ],
        )

        self.assertIn("1 passende Quelle", answer)
        self.assertNotIn("[S1]", answer)
        self.assertNotIn("TESTNETZADMIN-HANDBUCH-20260617", answer)


def _settings() -> SearchServiceSettings:
    return SearchServiceSettings(
        search_authz_base_url="http://connector-controller:8080",
        search_authz_shared_secret="authz-secret",
        search_ragflow_base_url="http://ragflow:9380",
        search_ragflow_api_key="ragflow-key",
    )


class _FakeRAGFlowClient:
    calls: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def retrieve_chunks(self, **kwargs: object) -> dict[str, object]:
        dataset_id = str(kwargs["dataset_id"])
        self.__class__.calls.append(dataset_id)
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

    def close(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
