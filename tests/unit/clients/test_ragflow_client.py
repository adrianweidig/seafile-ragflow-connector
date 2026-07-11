from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient


class _MissingDatasetHttpClient:
    def get(self, path: str, *, params: dict[str, str]) -> httpx.Response:
        name = params["name"]
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={
                "code": 102,
                "message": f"User 'tenant' lacks permission for dataset '{name}'",
            },
            request=request,
        )

    def close(self) -> None:
        return None


class _OtherApiErrorHttpClient:
    def get(self, path: str, *, params: dict[str, str]) -> httpx.Response:
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(200, json={"code": 101, "message": "other error"}, request=request)

    def close(self) -> None:
        return None


class _MalformedListHttpClient:
    def __init__(self, data: object) -> None:
        self.data = data

    def get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        _ = params
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": self.data},
            request=request,
        )

    def close(self) -> None:
        return None


class _DeleteDocumentsHttpClient:
    def __init__(self) -> None:
        self.deleted: list[list[str]] = []

    def request(self, method: str, path: str, *, json: dict[str, list[str]]) -> httpx.Response:
        request = httpx.Request(method, f"http://ragflow.local{path}")
        ids = json["ids"]
        self.deleted.append(ids)
        if "missing" in ids:
            return httpx.Response(
                200,
                json={
                    "code": 102,
                    "message": (
                        "These documents do not belong to dataset ds "
                        "or Document not found: missing"
                    ),
                },
                request=request,
            )
        return httpx.Response(200, json={"code": 0, "data": {"deleted": ids}}, request=request)

    def close(self) -> None:
        return None


class _ChatHttpClient:
    def __init__(self) -> None:
        self.created_payload: dict[str, object] | None = None
        self.updated_payload: dict[str, object] | None = None
        self.deleted_payloads: list[tuple[str, dict[str, object]]] = []
        self.post_paths: list[str] = []
        self.put_payloads: list[tuple[str, dict[str, object]]] = []
        self.retrieval_payloads: list[dict[str, object]] = []

    def get(self, path: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        if path == "/api/v1/chats":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": "chat-1",
                            "name": params.get("name"),
                            "dataset_ids": ["ds-1"],
                        }
                    ],
                },
                request=request,
            )
        if path == "/api/v1/searches":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "search_apps": [
                            {
                                "id": "search-1",
                                "name": params.get("keywords"),
                                "search_config": {"top_k": 1024},
                            }
                        ]
                    },
                },
                request=request,
            )
        if path == "/api/v1/searches/search-1":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": "search-1",
                        "name": "search_template",
                        "search_config": {"top_k": 1024},
                    },
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "chat-1", "dataset_ids": ["ds-1"]}},
            request=request,
        )

    def post(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        self.post_paths.append(path)
        request = httpx.Request("POST", f"http://ragflow.local{path}")
        if path == "/api/v1/chats":
            self.created_payload = json
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": "chat-new", **json}},
                request=request,
            )
        if path == "/api/v1/searches":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": "search-new", **json}},
                request=request,
            )
        if path == "/api/v1/retrieval":
            self.retrieval_payloads.append(json)
            return httpx.Response(
                200,
                json={"code": 0, "data": {"chunks": [{"id": "chunk-1", "document_id": "doc-1"}]}},
                request=request,
            )
        if path == "/api/v1/openai/chat-1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "answer",
                                "reference": {"chunks": []},
                                "role": "assistant",
                            }
                        }
                    ],
                    "object": "chat.completion",
                },
                request=request,
            )
        raise AssertionError(path)

    def stream(self, method: str, path: str, *, json: dict[str, object]) -> _StreamResponse:
        self.post_paths.append(path)
        request = httpx.Request(method, f"http://ragflow.local{path}")
        return _StreamResponse(
            httpx.Response(
                200,
                content=(
                    b'data:{"code":0,"data":{"answer":"part 1 ","reference":{"chunks":[]}}}\n\n'
                    b'data:{"choices":[{"delta":{"content":"part 2"}}]}\n\n'
                    b'data:{"code":0,"data":{"choices":[{"delta":{"content":" part 3",'
                    b'"reference":{"chunks":{"2":{"id":"chunk-ref"}}}}}]}}\n\n'
                    b'data:{"code":0,"data":true}\n\n'
                ),
                request=request,
            )
        )

    def patch(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("PATCH", f"http://ragflow.local{path}")
        self.updated_payload = json
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "chat-1", **json}},
            request=request,
        )

    def put(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("PUT", f"http://ragflow.local{path}")
        self.put_payloads.append((path, json))
        if path == "/api/v1/datasets/ds-1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": "ds-1", **json}},
                request=request,
            )
        if path == "/api/v1/datasets/ds-1/documents/doc-1/metadata/config":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"metadata": json["metadata"]}},
                request=request,
            )
        if path == "/api/v1/searches/search-1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": "search-1", **json}},
                request=request,
            )
        raise AssertionError(path)

    def request(self, method: str, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request(method, f"http://ragflow.local{path}")
        self.deleted_payloads.append((path, json))
        return httpx.Response(200, json={"code": 0, "data": True}, request=request)

    def close(self) -> None:
        return None


class _RerankErrorHttpClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def post(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("POST", f"http://ragflow.local{path}")
        self.payloads.append(json)
        if len(self.payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "code": 100,
                    "message": "LookupError('Model(vllm/reranker) not authorized')",
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"chunks": [{"id": "chunk-1"}]}},
            request=request,
        )

    def close(self) -> None:
        return None


class _KeywordCompatibilityErrorHttpClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def post(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("POST", f"http://ragflow.local{path}")
        self.payloads.append(json)
        if len(self.payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "code": 100,
                    "message": "Exception('No default chat model is set.')",
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"code": 0, "data": {"chunks": [{"id": "chunk-1"}]}},
            request=request,
        )

    def close(self) -> None:
        return None


class RAGFlowClientTests(unittest.TestCase):
    def test_missing_named_dataset_is_empty_list(self) -> None:
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = _MissingDatasetHttpClient()  # type: ignore[assignment]

        self.assertEqual(client.list_datasets(name="missing"), [])

    def test_other_dataset_errors_are_not_suppressed(self) -> None:
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = _OtherApiErrorHttpClient()  # type: ignore[assignment]

        with self.assertRaises(ApiError):
            client.list_datasets(name="missing")

    def test_list_endpoints_reject_non_mapping_items_and_unknown_containers(self) -> None:
        cases = (
            ("datasets", {"status": "ok"}, lambda client: client.list_datasets()),
            ("documents", ["doc-1"], lambda client: client.list_documents("dataset-1")),
            ("chats", "chat-1", lambda client: client.list_chats()),
            ("searches", {"status": "ok"}, lambda client: client.list_searches()),
        )
        for endpoint, data, operation in cases:
            with self.subTest(endpoint=endpoint):
                client = RAGFlowClient("http://ragflow.local", "token")
                client._client = _MalformedListHttpClient(data)  # type: ignore[assignment]

                with self.assertRaisesRegex(ApiError, f"RAGFlow {endpoint} endpoint"):
                    operation(client)

    def test_delete_documents_ignores_missing_ids_but_retries_valid_ids(self) -> None:
        http_client = _DeleteDocumentsHttpClient()
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        client.delete_documents("ds", ["valid", "missing"])

        self.assertEqual(http_client.deleted, [["valid", "missing"], ["valid"], ["missing"]])

    def test_chat_and_retrieval_endpoints_use_current_http_api(self) -> None:
        http_client = _ChatHttpClient()
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        self.assertEqual(client.list_chats(name="demo")[0]["id"], "chat-1")
        self.assertEqual(client.get_chat("chat-1")["dataset_ids"], ["ds-1"])
        self.assertEqual(
            client.create_chat({"name": "demo", "dataset_ids": ["ds-1"]})["id"],
            "chat-new",
        )
        self.assertEqual(client.update_dataset("ds-1", {"parser_config": {}})["id"], "ds-1")
        self.assertEqual(
            client.update_document_metadata("ds-1", "doc-1", {"repo_id": "repo"})["metadata"],
            {"repo_id": "repo"},
        )
        self.assertEqual(
            client.update_chat("chat-1", {"dataset_ids": ["ds-1"]})["id"],
            "chat-1",
        )
        self.assertEqual(client.list_searches(keywords="search_template")[0]["id"], "search-1")
        self.assertEqual(client.get_search("search-1")["search_config"]["top_k"], 1024)
        self.assertEqual(client.create_search({"name": "search_template"})["id"], "search-new")
        self.assertEqual(
            client.update_search("search-1", {"search_config": {"top_k": 2048}})["id"],
            "search-1",
        )
        self.assertEqual(
            client.retrieve_chunks(dataset_id="ds-1", question="q")["chunks"][0]["id"],
            "chunk-1",
        )
        self.assertEqual(http_client.retrieval_payloads[-1]["top_k"], 5)
        self.assertEqual(
            client.retrieve_chunks(
                dataset_id="ds-1",
                question="q",
                retrieval_options={"top_k": 1024, "page_size": 8, "highlight": True},
            )["chunks"][0]["id"],
            "chunk-1",
        )
        self.assertEqual(http_client.retrieval_payloads[-1]["top_k"], 1024)
        self.assertEqual(http_client.retrieval_payloads[-1]["page_size"], 8)
        self.assertTrue(http_client.retrieval_payloads[-1]["highlight"])
        response = client.chat_completion(
            chat_id="chat-1",
            messages=[{"role": "user", "content": "q"}],
        )
        self.assertEqual(response["choices"][0]["message"]["content"], "answer")
        streamed = client.chat_completion(
            chat_id="chat-1",
            messages=[{"role": "user", "content": "q"}],
            stream=True,
        )
        self.assertEqual(streamed["data"]["answer"], "part 1 part 2 part 3")
        self.assertEqual(streamed["data"]["reference"]["chunks"]["2"]["id"], "chunk-ref")
        self.assertIn("/api/v1/openai/chat-1/chat/completions", http_client.post_paths)
        self.assertTrue(client.delete_chats(["chat-1"]))
        self.assertTrue(client.delete_datasets(["ds-1"]))
        self.assertEqual(
            http_client.deleted_payloads,
            [
                ("/api/v1/chats", {"ids": ["chat-1"]}),
                ("/api/v1/datasets", {"ids": ["ds-1"]}),
            ],
        )

    def test_retrieve_chunks_retries_once_without_invalid_reranker(self) -> None:
        http_client = _RerankErrorHttpClient()
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        result = client.retrieve_chunks(
            dataset_id="ds-1",
            question="q",
            retrieval_options={
                "top_k": 1024,
                "page_size": 8,
                "rerank_id": "vllm/reranker",
            },
        )

        self.assertEqual(result["chunks"][0]["id"], "chunk-1")
        self.assertEqual(len(http_client.payloads), 2)
        self.assertEqual(http_client.payloads[0]["rerank_id"], "vllm/reranker")
        self.assertNotIn("rerank_id", http_client.payloads[1])
        self.assertTrue(result["_connector_retrieval_diagnostics"]["rerank_retry"])

    def test_retrieve_chunks_retries_without_keyword_when_chat_model_missing(self) -> None:
        http_client = _KeywordCompatibilityErrorHttpClient()
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        result = client.retrieve_chunks(
            dataset_id="ds-1",
            question="q",
            retrieval_options={
                "top_k": 1024,
                "page_size": 8,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "keyword": True,
                "highlight": True,
            },
        )

        self.assertEqual(result["chunks"][0]["id"], "chunk-1")
        self.assertEqual(len(http_client.payloads), 2)
        self.assertTrue(http_client.payloads[0]["keyword"])
        self.assertTrue(http_client.payloads[0]["highlight"])
        self.assertNotIn("keyword", http_client.payloads[1])
        self.assertNotIn("highlight", http_client.payloads[1])
        self.assertEqual(http_client.payloads[1]["top_k"], 1024)
        self.assertEqual(http_client.payloads[1]["page_size"], 8)
        self.assertTrue(result["_connector_retrieval_diagnostics"]["compatibility_retry"])


class _StreamResponse:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __enter__(self) -> httpx.Response:
        return self.response

    def __exit__(self, *args: object) -> None:
        self.response.close()


if __name__ == "__main__":
    unittest.main()
