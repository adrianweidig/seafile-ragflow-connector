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
                    "message": "These documents do not belong to dataset ds or Document not found: missing",
                },
                request=request,
            )
        return httpx.Response(200, json={"code": 0, "data": {"deleted": ids}}, request=request)

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


if __name__ == "__main__":
    unittest.main()
