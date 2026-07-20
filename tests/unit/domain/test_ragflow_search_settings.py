from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.domain.ragflow_search_settings import (
    RagflowRetrievalOverrides,
    RagflowSearchTemplateConfig,
    apply_retrieval_settings_to_chat_payload,
    ensure_search_template,
    resolve_search_template,
)


class RagflowSearchSettingsTests(unittest.TestCase):
    def test_search_app_template_wins_and_ignores_dataset_scope(self) -> None:
        client = _FakeRAGFlowClient(
            search_apps=[
                {
                    "id": "search-1",
                    "name": "search_template",
                    "search_config": {
                        "dataset_ids": ["forbidden-dataset"],
                        "kb_ids": ["forbidden-kb"],
                        "document_ids": ["forbidden-doc"],
                        "similarity_threshold": 0.12,
                        "vector_similarity_weight": 0.45,
                        "top_n": 10,
                        "top_k": 2048,
                        "rerank_id": "reranker@provider",
                        "keyword": True,
                        "highlight": True,
                        "cross_languages": ["German", "English"],
                        "use_kg": True,
                        "toc_enhance": True,
                    },
                }
            ]
        )

        resolved = resolve_search_template(client, RagflowSearchTemplateConfig())
        options = resolved.settings.to_retrieval_options(requested_results=8)
        search_config = resolved.settings.to_search_config()

        self.assertEqual(resolved.source, "search_app")
        self.assertEqual(resolved.template_id, "search-1")
        self.assertEqual(options["top_k"], 2048)
        self.assertEqual(options["page_size"], 10)
        self.assertEqual(options["rerank_id"], "reranker@provider")
        self.assertNotIn("dataset_ids", search_config)
        self.assertNotIn("kb_ids", search_config)
        self.assertNotIn("document_ids", search_config)

    def test_chat_template_is_used_when_search_app_is_missing(self) -> None:
        client = _FakeRAGFlowClient(
            chats=[
                {
                    "id": "chat-1",
                    "name": "search_template",
                    "similarity_threshold": 0.08,
                    "vector_similarity_weight": 0.25,
                    "top_n": 12,
                    "top_k": 1536,
                    "prompt_config": {
                        "keyword": False,
                        "toc_enhance": True,
                        "use_kg": False,
                    },
                }
            ]
        )

        resolved = resolve_search_template(client, RagflowSearchTemplateConfig())

        self.assertEqual(resolved.source, "chat")
        self.assertEqual(resolved.settings.similarity_threshold, 0.08)
        self.assertEqual(resolved.settings.vector_similarity_weight, 0.25)
        self.assertEqual(resolved.settings.top_n, 12)
        self.assertEqual(resolved.settings.top_k, 1536)
        self.assertFalse(resolved.settings.keyword)
        self.assertTrue(resolved.settings.toc_enhance)

    def test_builtin_defaults_preserve_large_candidate_pool(self) -> None:
        resolved = resolve_search_template(_FakeRAGFlowClient(), RagflowSearchTemplateConfig())
        options = resolved.settings.to_retrieval_options(requested_results=8)

        self.assertEqual(resolved.source, "builtin")
        self.assertEqual(options["top_k"], 1024)
        self.assertEqual(options["page_size"], 8)
        self.assertEqual(options["similarity_threshold"], 0.2)
        self.assertEqual(options["vector_similarity_weight"], 0.3)
        self.assertTrue(options["keyword"])
        self.assertTrue(options["highlight"])

    def test_explicit_overrides_win_over_template_values(self) -> None:
        client = _FakeRAGFlowClient(
            search_apps=[
                {
                    "id": "search-1",
                    "name": "search_template",
                    "search_config": {
                        "similarity_threshold": 0.4,
                        "top_k": 512,
                        "highlight": False,
                    },
                }
            ]
        )
        resolved = resolve_search_template(
            client,
            RagflowSearchTemplateConfig(
                overrides=RagflowRetrievalOverrides(
                    similarity_threshold=0.05,
                    top_k=4096,
                    highlight=True,
                )
            ),
        )

        self.assertEqual(resolved.settings.similarity_threshold, 0.05)
        self.assertEqual(resolved.settings.top_k, 4096)
        self.assertTrue(resolved.settings.highlight)

    def test_openwebui_chat_payload_receives_retrieval_fields(self) -> None:
        resolved = resolve_search_template(_FakeRAGFlowClient(), RagflowSearchTemplateConfig())
        payload = apply_retrieval_settings_to_chat_payload(
            {"name": "chat", "prompt_config": {"quote": True}},
            resolved,
        )

        self.assertEqual(payload["top_n"], 8)
        self.assertEqual(payload["top_k"], 1024)
        self.assertEqual(payload["similarity_threshold"], 0.2)
        self.assertEqual(payload["vector_similarity_weight"], 0.3)
        self.assertTrue(payload["prompt_config"]["quote"])
        self.assertTrue(payload["prompt_config"]["keyword"])

    def test_auto_create_search_app_uses_builtin_config(self) -> None:
        client = _FakeRAGFlowClient()

        resolved = ensure_search_template(
            client,
            RagflowSearchTemplateConfig(auto_create=True),
        )

        self.assertEqual(resolved.source, "search_app")
        self.assertEqual(resolved.template_id, "created-search")
        self.assertEqual(client.created_searches[0]["name"], "search_template")
        self.assertEqual(client.created_searches[0]["search_config"]["top_k"], 1024)

    def test_auto_create_search_app_requires_owner_detail_verification(self) -> None:
        client = _UnverifiedSearchClient()

        with self.assertRaisesRegex(RuntimeError, "could not be verified"):
            ensure_search_template(
                client,
                RagflowSearchTemplateConfig(auto_create=True, required=True),
            )

        self.assertEqual(client.deleted_searches, ["created-search"])

    def test_required_existing_search_requires_verifiable_detail(self) -> None:
        client = _UnverifiedSearchClient(
            search_apps=[
                {
                    "id": "search-1",
                    "name": "search_template",
                    "search_config": {"top_k": 1024},
                }
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "could not be updated"):
            ensure_search_template(
                client,
                RagflowSearchTemplateConfig(required=True),
            )

    def test_owner_preflight_failure_creates_no_search_app(self) -> None:
        client = _OwnerMismatchPreflightSearchClient()

        with self.assertRaisesRegex(RuntimeError, "could not be created"):
            ensure_search_template(
                client,
                RagflowSearchTemplateConfig(auto_create=True, required=True),
            )

        self.assertEqual(client.created_searches, [])

    def test_unverified_create_is_not_repeated_with_auto_suffix(self) -> None:
        client = _InvisibleCreatedSearchClient()
        config = RagflowSearchTemplateConfig(auto_create=True)

        first = ensure_search_template(client, config)
        second = ensure_search_template(client, config)

        self.assertEqual(len(client.created_searches), 1)
        self.assertIn("search_app_auto_create_unverified", first.warnings)
        self.assertIn("search_app_auto_create_rolled_back", first.warnings)
        self.assertEqual(client.deleted_searches, ["created-search"])
        self.assertIn("search_app_auto_create_blocked", second.warnings)

    def test_unverified_create_reports_failed_rollback(self) -> None:
        client = _InvisibleCreatedSearchClient(rollback_error=ApiError("delete failed"))

        resolved = ensure_search_template(
            client,
            RagflowSearchTemplateConfig(auto_create=True),
        )

        self.assertIn("search_app_auto_create_unverified", resolved.warnings)
        self.assertIn("search_app_auto_create_rollback_failed", resolved.warnings)
        self.assertEqual(client.deleted_searches, ["created-search"])

    def test_required_unverified_create_fails_when_rollback_fails(self) -> None:
        client = _InvisibleCreatedSearchClient(rollback_error=ApiError("delete failed"))

        with self.assertRaisesRegex(RuntimeError, "rollback failed") as raised:
            ensure_search_template(
                client,
                RagflowSearchTemplateConfig(auto_create=True, required=True),
            )

        self.assertIsInstance(raised.exception.__cause__, ApiError)
        self.assertEqual(client.deleted_searches, ["created-search"])

    def test_auto_create_search_app_binds_native_datasets_and_chat_model(self) -> None:
        client = _FakeRAGFlowClient()

        ensure_search_template(
            client,
            RagflowSearchTemplateConfig(auto_create=True),
            native_dataset_ids=["dataset-2", "dataset-1", "dataset-2", " "],
            chat_model_id="model@provider",
        )

        search_config = client.created_searches[0]["search_config"]
        self.assertEqual(search_config["kb_ids"], ["dataset-1", "dataset-2"])
        self.assertEqual(search_config["chat_id"], "model@provider")

    def test_search_create_id_only_response_preserves_resolved_settings(self) -> None:
        client = _FakeRAGFlowClient()

        resolved = ensure_search_template(
            client,
            RagflowSearchTemplateConfig(
                auto_create=True,
                overrides=RagflowRetrievalOverrides(
                    top_k=4096,
                    similarity_threshold=0.05,
                ),
            ),
        )

        self.assertEqual(resolved.template_id, "created-search")
        self.assertEqual(resolved.settings.top_k, 4096)
        self.assertEqual(resolved.settings.similarity_threshold, 0.05)

    def test_existing_search_app_is_updated_idempotently_and_can_clear_datasets(self) -> None:
        client = _FakeRAGFlowClient(
            search_apps=[
                {
                    "id": "search-1",
                    "name": "search_template",
                    "description": "old",
                    "search_config": {
                        "top_k": 1024,
                        "kb_ids": ["stale-dataset"],
                        "chat_id": "old-model",
                    },
                }
            ]
        )
        config = RagflowSearchTemplateConfig(auto_create=True)

        first = ensure_search_template(
            client,
            config,
            native_dataset_ids=[],
            chat_model_id="model@provider",
        )
        second = ensure_search_template(
            client,
            config,
            native_dataset_ids=[],
            chat_model_id="model@provider",
        )

        self.assertEqual(first.source, "search_app")
        self.assertEqual(second.source, "search_app")
        self.assertEqual(len(client.updated_searches), 1)
        search_config = client.updated_searches[0][1]["search_config"]
        self.assertEqual(search_config["kb_ids"], [])
        self.assertEqual(search_config["chat_id"], "model@provider")

    def test_search_app_request_error_falls_back_to_builtin(self) -> None:
        client = _FakeRAGFlowClient(search_error=httpx.ConnectError("connection refused"))

        resolved = resolve_search_template(client, RagflowSearchTemplateConfig())

        self.assertEqual(resolved.source, "builtin")
        self.assertIn("search_app_api_unavailable", resolved.warnings)

    def test_chat_request_error_falls_back_to_builtin(self) -> None:
        client = _FakeRAGFlowClient(chat_error=httpx.ConnectError("connection refused"))

        resolved = resolve_search_template(client, RagflowSearchTemplateConfig())

        self.assertEqual(resolved.source, "builtin")
        self.assertIn("chat_template_api_unavailable", resolved.warnings)


class _FakeRAGFlowClient:
    def __init__(
        self,
        *,
        search_apps: list[dict[str, object]] | None = None,
        chats: list[dict[str, object]] | None = None,
        search_error: Exception | None = None,
        chat_error: Exception | None = None,
    ) -> None:
        self.search_apps = search_apps or []
        self.chats = chats or []
        self.search_error = search_error
        self.chat_error = chat_error
        self.created_searches: list[dict[str, object]] = []
        self.updated_searches: list[tuple[str, dict[str, object]]] = []

    def list_searches(self, *, keywords: str | None = None, page_size: int | None = None):
        _ = page_size
        if self.search_error is not None:
            raise self.search_error
        if keywords:
            return [item for item in self.search_apps if item.get("name") == keywords]
        return self.search_apps

    def get_search(self, search_id: str):
        return next((item for item in self.search_apps if item.get("id") == search_id), None)

    def create_search(self, payload: dict[str, object]):
        self.created_searches.append(payload)
        self.search_apps.append({"id": "created-search", **payload})
        return {"search_id": "created-search"}

    def update_search(self, search_id: str, payload: dict[str, object]):
        self.updated_searches.append((search_id, payload))
        for index, search in enumerate(self.search_apps):
            if search.get("id") == search_id:
                updated = {**search, **payload}
                self.search_apps[index] = updated
                return updated
        raise AssertionError(search_id)

    def list_chats(self, *, name: str | None = None):
        if self.chat_error is not None:
            raise self.chat_error
        if name:
            return [item for item in self.chats if item.get("name") == name]
        return self.chats

    def get_chat(self, chat_id: str):
        return next((item for item in self.chats if item.get("id") == chat_id), None)


class _UnverifiedSearchClient(_FakeRAGFlowClient):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.deleted_searches: list[str] = []

    def get_search(self, search_id: str):
        _ = search_id
        return None

    def delete_search(self, search_id: str):
        self.deleted_searches.append(search_id)


class _InvisibleCreatedSearchClient(_UnverifiedSearchClient):
    def __init__(self, *, rollback_error: Exception | None = None) -> None:
        super().__init__()
        self.rollback_error = rollback_error

    def create_search(self, payload: dict[str, object]):
        self.created_searches.append(payload)
        return {"search_id": "created-search"}

    def delete_search(self, search_id: str):
        super().delete_search(search_id)
        if self.rollback_error is not None:
            raise self.rollback_error


class _OwnerMismatchPreflightSearchClient(_FakeRAGFlowClient):
    artifact_owner_id = "owner-1"

    def verify_artifact_owner(self) -> None:
        raise ApiError("owner mismatch", status_code=200)


if __name__ == "__main__":
    unittest.main()
