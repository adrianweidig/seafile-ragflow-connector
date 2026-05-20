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
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "chat-1", "dataset_ids": ["ds-1"]}},
            request=request,
        )

    def post(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("POST", f"http://ragflow.local{path}")
        if path == "/api/v1/chats":
            self.created_payload = json
            return httpx.Response(
                200,
                json={"code": 0, "data": {"id": "chat-new", **json}},
                request=request,
            )
        if path == "/api/v1/retrieval":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"chunks": [{"id": "chunk-1", "document_id": "doc-1"}]}},
                request=request,
            )
        if path == "/api/v1/chat/completions":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"content": "answer", "reference": {"chunks": []}}},
                request=request,
            )
        raise AssertionError(path)

    def patch(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("PATCH", f"http://ragflow.local{path}")
        self.updated_payload = json
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "chat-1", **json}},
            request=request,
        )

    def request(self, method: str, path: str, *, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request(method, f"http://ragflow.local{path}")
        self.deleted_payloads.append((path, json))
        return httpx.Response(200, json={"code": 0, "data": True}, request=request)

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
        self.assertEqual(
            client.update_chat("chat-1", {"dataset_ids": ["ds-1"]})["id"],
            "chat-1",
        )
        self.assertEqual(
            client.retrieve_chunks(dataset_id="ds-1", question="q")["chunks"][0]["id"],
            "chunk-1",
        )
        self.assertEqual(
            client.chat_completion(
                chat_id="chat-1",
                messages=[{"role": "user", "content": "q"}],
            )["content"],
            "answer",
        )
        self.assertTrue(client.delete_chats(["chat-1"]))
        self.assertTrue(client.delete_datasets(["ds-1"]))
        self.assertEqual(
            http_client.deleted_payloads,
            [
                ("/api/v1/chats", {"ids": ["chat-1"]}),
                ("/api/v1/datasets", {"ids": ["ds-1"]}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
