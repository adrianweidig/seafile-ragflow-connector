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
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append((path, dict(params or {})))
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": self.data},
            request=request,
        )

    def close(self) -> None:
        return None


class _ArtifactDetailHttpClient:
    def __init__(self, data: object) -> None:
        self.data = data

    def get(self, path: str) -> httpx.Response:
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": self.data},
            request=request,
        )

    def close(self) -> None:
        return None


class _ArtifactAccessDeniedHttpClient:
    def get(self, path: str) -> httpx.Response:
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        is_search = "/searches/" in path
        return httpx.Response(
            200,
            json={
                "code": 103 if is_search else 109,
                "message": "Has no permission." if is_search else "No authorization.",
            },
            request=request,
        )

    def close(self) -> None:
        return None


class _ArtifactChatMutationHttpClient:
    def __init__(
        self,
        owner_id: str | None,
        *,
        identity_owner_id: str | None = "owner-1",
    ) -> None:
        self.owner_id = owner_id
        self.identity_owner_id = identity_owner_id
        self.identity_calls = 0
        self.mutation_calls = 0

    def get(self, path: str) -> httpx.Response:
        if path != "/api/v1/users/me":
            raise AssertionError(path)
        self.identity_calls += 1
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        data = (
            {"id": self.identity_owner_id}
            if self.identity_owner_id is not None
            else {}
        )
        return httpx.Response(200, json={"code": 0, "data": data}, request=request)

    def _response(self, method: str, path: str, payload: dict[str, object]) -> httpx.Response:
        request = httpx.Request(method, f"http://ragflow.local{path}")
        data: dict[str, object] = {"id": "chat-1", **payload}
        if self.owner_id is not None:
            data["tenant_id"] = self.owner_id
        return httpx.Response(200, json={"code": 0, "data": data}, request=request)

    def post(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        self.mutation_calls += 1
        return self._response("POST", path, json)

    def patch(self, path: str, *, json: dict[str, object]) -> httpx.Response:
        self.mutation_calls += 1
        return self._response("PATCH", path, json)

    def close(self) -> None:
        return None


class _ArtifactSearchDeleteHttpClient:
    def __init__(self, *, identity_owner_id: str) -> None:
        self.identity_owner_id = identity_owner_id
        self.identity_calls = 0
        self.deleted_paths: list[str] = []

    def get(self, path: str) -> httpx.Response:
        if path != "/api/v1/users/me":
            raise AssertionError(path)
        self.identity_calls += 1
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": self.identity_owner_id}},
            request=request,
        )

    def delete(self, path: str) -> httpx.Response:
        self.deleted_paths.append(path)
        request = httpx.Request("DELETE", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": {"deleted": True}},
            request=request,
        )

    def close(self) -> None:
        return None


class _DeleteDocumentsHttpClient:
    def __init__(self, *, single_missing_status_code: int = 200) -> None:
        self.deleted: list[list[str]] = []
        self.single_missing_status_code = single_missing_status_code

    def request(self, method: str, path: str, *, json: dict[str, list[str]]) -> httpx.Response:
        request = httpx.Request(method, f"http://ragflow.local{path}")
        ids = json["ids"]
        self.deleted.append(ids)
        if "missing" in ids:
            status_code = self.single_missing_status_code if len(ids) == 1 else 200
            return httpx.Response(
                status_code,
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


class _UploadDocumentHttpClient:
    def __init__(self, data: object) -> None:
        self.data = data

    def post(self, path: str, *, files: dict[str, object]) -> httpx.Response:
        _ = files
        request = httpx.Request("POST", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": self.data},
            request=request,
        )

    def close(self) -> None:
        return None


class _RenameDocumentHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def put(self, path: str, *, json: dict[str, str]) -> httpx.Response:
        self.calls.append((path, dict(json)))
        request = httpx.Request("PUT", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "doc-1", **json}},
            request=request,
        )

    def close(self) -> None:
        return None


class _DeleteResponseHttpClient:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self.payload = payload
        self.calls = 0

    def request(self, method: str, path: str, *, json: dict[str, object]) -> httpx.Response:
        _ = json
        self.calls += 1
        request = httpx.Request(method, f"http://ragflow.local{path}")
        return httpx.Response(self.status_code, json=self.payload, request=request)

    def close(self) -> None:
        return None


class _PaginatedDocumentsHttpClient:
    def __init__(
        self,
        count: int,
        *,
        ignore_page: bool = False,
        page_cycle: int | None = None,
    ) -> None:
        self.documents = [{"id": f"doc-{index}"} for index in range(count)]
        self.ignore_page = ignore_page
        self.page_cycle = page_cycle
        self.params: list[dict[str, str]] = []

    def get(self, path: str, *, params: dict[str, str]) -> httpx.Response:
        self.params.append(dict(params))
        requested_page = int(params["page"])
        page = 1 if self.ignore_page else requested_page
        if self.page_cycle:
            page = ((requested_page - 1) % self.page_cycle) + 1
        page_size = int(params["page_size"])
        start = (page - 1) * page_size
        documents = self.documents[start : start + page_size]
        request = httpx.Request("GET", f"http://ragflow.local{path}")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"total": len(self.documents), "docs": documents},
            },
            request=request,
        )

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
    def test_interactive_owner_preflight_blocks_mutation_and_caches_success(self) -> None:
        mismatched_http = _ArtifactChatMutationHttpClient(
            "owner-2",
            identity_owner_id="owner-2",
        )
        mismatched = RAGFlowClient(
            "http://ragflow.local",
            "token",
            artifact_owner_id="owner-1",
        )
        mismatched._client = mismatched_http  # type: ignore[assignment]

        with self.assertRaisesRegex(ApiError, "identity does not match"):
            mismatched.create_chat({"name": "demo"})

        self.assertEqual(mismatched_http.identity_calls, 1)
        self.assertEqual(mismatched_http.mutation_calls, 0)

        verified_http = _ArtifactChatMutationHttpClient("owner-1")
        verified = RAGFlowClient(
            "http://ragflow.local",
            "token",
            artifact_owner_id="owner-1",
        )
        verified._client = verified_http  # type: ignore[assignment]

        verified.create_chat({"name": "demo"})
        verified.update_chat("chat-1", {"name": "updated"})

        self.assertEqual(verified_http.identity_calls, 1)
        self.assertEqual(verified_http.mutation_calls, 2)

    def test_interactive_owner_preflight_rejects_missing_identity(self) -> None:
        http_client = _ArtifactChatMutationHttpClient(
            "owner-1",
            identity_owner_id=None,
        )
        client = RAGFlowClient(
            "http://ragflow.local",
            "token",
            artifact_owner_id="owner-1",
        )
        client._client = http_client  # type: ignore[assignment]

        with self.assertRaisesRegex(ApiError, "identity does not match"):
            client.create_chat({"name": "demo"})

        self.assertEqual(http_client.mutation_calls, 0)

    def test_delete_search_uses_verified_owner_and_exact_search_id(self) -> None:
        http_client = _ArtifactSearchDeleteHttpClient(identity_owner_id="owner-1")
        client = RAGFlowClient(
            "http://ragflow.local",
            "token",
            artifact_owner_id="owner-1",
        )
        client._client = http_client  # type: ignore[assignment]

        client.delete_search("search-created")

        self.assertEqual(http_client.identity_calls, 1)
        self.assertEqual(http_client.deleted_paths, ["/api/v1/searches/search-created"])

        mismatched_http = _ArtifactSearchDeleteHttpClient(identity_owner_id="owner-2")
        mismatched = RAGFlowClient(
            "http://ragflow.local",
            "token",
            artifact_owner_id="owner-1",
        )
        mismatched._client = mismatched_http  # type: ignore[assignment]

        with self.assertRaisesRegex(ApiError, "identity does not match"):
            mismatched.delete_search("search-created")

        self.assertEqual(mismatched_http.deleted_paths, [])

    def test_interactive_owner_filter_rejects_foreign_and_ownerless_artifacts(self) -> None:
        artifacts = [
            {"id": "tenant-owned", "tenant_id": "owner-1"},
            {"id": "creator-owned", "created_by": "owner-1"},
            {
                "id": "both-owned",
                "tenant_id": "owner-1",
                "created_by": "owner-1",
            },
            {"id": "foreign", "tenant_id": "owner-2"},
            {
                "id": "mixed",
                "tenant_id": "owner-1",
                "created_by": "owner-2",
            },
            {"id": "ownerless"},
        ]
        for operation_name in ("list_chats", "list_searches"):
            with self.subTest(operation=operation_name):
                http_client = _MalformedListHttpClient(artifacts)
                client = RAGFlowClient(
                    "http://ragflow.local",
                    "token",
                    artifact_owner_id=" owner-1 ",
                )
                client._client = http_client  # type: ignore[assignment]

                visible = getattr(client, operation_name)()

                self.assertEqual(
                    [item["id"] for item in visible],
                    ["tenant-owned", "creator-owned", "both-owned"],
                )
                self.assertEqual(client.artifact_owner_id, "owner-1")
                self.assertEqual(http_client.calls[0][1]["owner_ids"], "owner-1")

    def test_interactive_owner_filter_applies_to_chat_and_search_details(self) -> None:
        for operation_name in ("get_chat", "get_search"):
            with self.subTest(operation=operation_name, owner="matching"):
                client = RAGFlowClient(
                    "http://ragflow.local",
                    "token",
                    artifact_owner_id="owner-1",
                )
                client._client = _ArtifactDetailHttpClient(  # type: ignore[assignment]
                    {"id": "artifact-1", "tenant_id": "owner-1"}
                )
                self.assertIsNotNone(getattr(client, operation_name)("artifact-1"))

            for detail in (
                {"id": "artifact-1"},
                {"id": "artifact-1", "tenant_id": "owner-2"},
            ):
                with self.subTest(operation=operation_name, detail=detail):
                    client = RAGFlowClient(
                        "http://ragflow.local",
                        "token",
                        artifact_owner_id="owner-1",
                    )
                    client._client = _ArtifactDetailHttpClient(detail)  # type: ignore[assignment]
                    self.assertIsNone(getattr(client, operation_name)("artifact-1"))

            with self.subTest(operation=operation_name, owner="denied"):
                client = RAGFlowClient(
                    "http://ragflow.local",
                    "token",
                    artifact_owner_id="owner-1",
                )
                client._client = _ArtifactAccessDeniedHttpClient()  # type: ignore[assignment]
                self.assertIsNone(getattr(client, operation_name)("artifact-1"))

    def test_interactive_owner_is_verified_after_chat_mutations(self) -> None:
        for operation_name in ("create_chat", "update_chat"):
            with self.subTest(operation=operation_name, owner="matching"):
                client = RAGFlowClient(
                    "http://ragflow.local",
                    "token",
                    artifact_owner_id="owner-1",
                )
                client._client = _ArtifactChatMutationHttpClient(  # type: ignore[assignment]
                    "owner-1"
                )
                if operation_name == "create_chat":
                    result = client.create_chat({"name": "demo"})
                else:
                    result = client.update_chat("chat-1", {"name": "demo"})
                self.assertEqual(result["tenant_id"], "owner-1")

            for returned_owner in (None, "owner-2"):
                with self.subTest(operation=operation_name, owner=returned_owner):
                    client = RAGFlowClient(
                        "http://ragflow.local",
                        "token",
                        artifact_owner_id="owner-1",
                    )
                    client._client = _ArtifactChatMutationHttpClient(  # type: ignore[assignment]
                        returned_owner
                    )
                    with self.assertRaisesRegex(ApiError, "owner does not match"):
                        if operation_name == "create_chat":
                            client.create_chat({"name": "demo"})
                        else:
                            client.update_chat("chat-1", {"name": "demo"})

    def test_rename_document_restores_friendly_remote_name(self) -> None:
        http_client = _RenameDocumentHttpClient()
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        renamed = client.rename_document("dataset", "doc-1", "report.pdf")

        self.assertEqual(renamed["name"], "report.pdf")
        self.assertEqual(
            http_client.calls,
            [
                (
                    "/api/v1/datasets/dataset/documents/doc-1",
                    {"name": "report.pdf"},
                )
            ],
        )

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

    def test_upload_document_validates_document_identifier(self) -> None:
        valid_cases = (
            ({"id": "doc-1"}, {"id": "doc-1"}),
            ([{"document_id": "doc-2"}], {"document_id": "doc-2"}),
        )
        for response, expected in valid_cases:
            with self.subTest(response=response):
                client = RAGFlowClient("http://ragflow.local", "token")
                client._client = _UploadDocumentHttpClient(response)  # type: ignore[assignment]

                document = client.upload_document(
                    "dataset",
                    document_name="report.pdf",
                    content=b"content",
                    mime_type="application/pdf",
                )

                self.assertEqual(document, expected)

        for response in ({}, {"id": ""}, [], [{}], [{"document_id": None}], "doc-1"):
            with self.subTest(response=response):
                client = RAGFlowClient("http://ragflow.local", "token")
                client._client = _UploadDocumentHttpClient(response)  # type: ignore[assignment]

                with self.assertRaisesRegex(ApiError, "did not contain a document id"):
                    client.upload_document(
                        "dataset",
                        document_name="report.pdf",
                        content=b"content",
                        mime_type="application/pdf",
                    )

    def test_missing_delete_suppression_requires_successful_http_envelope(self) -> None:
        cases = (
            (
                "documents",
                {"code": 102, "message": "Document not found: missing"},
                lambda client: client.delete_documents("dataset", ["missing"]),
            ),
            (
                "datasets",
                {"code": 102, "message": "Dataset not found"},
                lambda client: client.delete_datasets(["dataset"]),
            ),
            (
                "chats",
                {"code": 102, "message": "Chat not found"},
                lambda client: client.delete_chats(["chat"]),
            ),
        )
        for endpoint, payload, operation in cases:
            with self.subTest(endpoint=endpoint, status_code=200):
                http_client = _DeleteResponseHttpClient(200, payload)
                client = RAGFlowClient("http://ragflow.local", "token")
                client._client = http_client  # type: ignore[assignment]

                self.assertEqual(operation(client), payload)

            for status_code in (201, 404, 429, 500):
                with self.subTest(endpoint=endpoint, status_code=status_code):
                    http_client = _DeleteResponseHttpClient(status_code, payload)
                    client = RAGFlowClient("http://ragflow.local", "token")
                    client._client = http_client  # type: ignore[assignment]

                    with self.assertRaises(ApiError) as raised:
                        operation(client)

                    self.assertEqual(raised.exception.status_code, status_code)
                    self.assertEqual(http_client.calls, 1)

            for invalid_payload in (
                {"code": 101, "message": payload["message"]},
                {"code": 102, "message": "different error"},
            ):
                with self.subTest(endpoint=endpoint, payload=invalid_payload):
                    http_client = _DeleteResponseHttpClient(200, invalid_payload)
                    client = RAGFlowClient("http://ragflow.local", "token")
                    client._client = http_client  # type: ignore[assignment]

                    with self.assertRaises(ApiError):
                        operation(client)

        http_client = _DeleteDocumentsHttpClient(single_missing_status_code=500)
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        with self.assertRaises(ApiError) as raised:
            client.delete_documents("dataset", ["valid", "missing"])

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(http_client.deleted, [["valid", "missing"], ["valid"], ["missing"]])

    def test_iter_documents_fetches_all_pages_with_bounded_page_size(self) -> None:
        http_client = _PaginatedDocumentsHttpClient(205)
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = http_client  # type: ignore[assignment]

        documents = list(
            client.iter_documents(
                "dataset",
                run="RUNNING",
                keywords="report",
                page_size=1024,
            )
        )

        self.assertEqual(len(documents), 205)
        self.assertEqual(documents[0]["id"], "doc-0")
        self.assertEqual(documents[-1]["id"], "doc-204")
        self.assertEqual([params["page"] for params in http_client.params], ["1", "2", "3"])
        self.assertTrue(all(params["page_size"] == "100" for params in http_client.params))
        self.assertTrue(all(params["run"] == "RUNNING" for params in http_client.params))
        self.assertTrue(all(params["keywords"] == "report" for params in http_client.params))

    def test_iter_documents_rejects_server_that_ignores_page(self) -> None:
        client = RAGFlowClient("http://ragflow.local", "token")
        client._client = _PaginatedDocumentsHttpClient(100, ignore_page=True)  # type: ignore[assignment]

        with self.assertRaisesRegex(ApiError, "pagination did not advance"):
            list(client.iter_documents("dataset"))

    def test_iter_documents_rejects_cyclic_full_pages(self) -> None:
        client = RAGFlowClient("http://ragflow.local", "token")
        http_client = _PaginatedDocumentsHttpClient(200, page_cycle=2)
        client._client = http_client  # type: ignore[assignment]

        with self.assertRaisesRegex(ApiError, "pagination did not advance"):
            list(client.iter_documents("dataset"))

        self.assertEqual([params["page"] for params in http_client.params], ["1", "2", "3"])

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
