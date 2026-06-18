from __future__ import annotations

import unittest

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
        self.assertEqual(client.created_searches[0]["name"], "search_template")
        self.assertEqual(client.created_searches[0]["search_config"]["top_k"], 1024)


class _FakeRAGFlowClient:
    def __init__(
        self,
        *,
        search_apps: list[dict[str, object]] | None = None,
        chats: list[dict[str, object]] | None = None,
    ) -> None:
        self.search_apps = search_apps or []
        self.chats = chats or []
        self.created_searches: list[dict[str, object]] = []

    def list_searches(self, *, keywords: str | None = None, page_size: int | None = None):
        _ = page_size
        if keywords:
            return [item for item in self.search_apps if item.get("name") == keywords]
        return self.search_apps

    def get_search(self, search_id: str):
        return next((item for item in self.search_apps if item.get("id") == search_id), None)

    def create_search(self, payload: dict[str, object]):
        self.created_searches.append(payload)
        search = {"id": "created-search", **payload}
        self.search_apps.append(search)
        return search

    def list_chats(self, *, name: str | None = None):
        if name:
            return [item for item in self.chats if item.get("name") == name]
        return self.chats

    def get_chat(self, chat_id: str):
        return next((item for item in self.chats if item.get("id") == chat_id), None)


if __name__ == "__main__":
    unittest.main()
