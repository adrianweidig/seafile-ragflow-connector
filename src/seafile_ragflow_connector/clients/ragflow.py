from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from seafile_ragflow_connector.app.metrics import (
    datasets_created_total,
    files_deleted_total,
    files_uploaded_total,
    parse_started_total,
)
from seafile_ragflow_connector.clients.http import (
    ApiError,
    VerifyConfig,
    make_client,
    unwrap_response,
)
from seafile_ragflow_connector.domain.ragflow_defaults import RAGFLOW_REFERENCE_METADATA_FIELDS

RAGFLOW_MAX_DOCUMENT_PAGE_SIZE = 100


class RAGFlowClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        verify: VerifyConfig = True,
        artifact_owner_id: str | None = None,
    ) -> None:
        self._artifact_owner_id = str(artifact_owner_id or "").strip() or None
        self._artifact_owner_verified = False
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            verify=verify,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def artifact_owner_id(self) -> str | None:
        return self._artifact_owner_id

    def verify_artifact_owner(self) -> None:
        if self._artifact_owner_id is None or self._artifact_owner_verified:
            return
        data = unwrap_response(self._client.get("/api/v1/users/me"))
        if not isinstance(data, dict):
            raise ApiError(
                "RAGFlow API-key identity response is not verifiable",
                status_code=200,
                payload={"identity_response_valid": False},
            )
        authenticated_owner_id = str(data.get("id") or "").strip()
        if authenticated_owner_id != self._artifact_owner_id:
            raise ApiError(
                "RAGFlow API-key identity does not match configured interactive owner",
                status_code=200,
                payload={
                    "identity_id_present": bool(authenticated_owner_id),
                    "identity_matches": False,
                },
            )
        self._artifact_owner_verified = True

    def _require_owned_artifact(
        self,
        artifact: dict[str, Any],
        *,
        artifact_type: str,
    ) -> None:
        if self._artifact_owner_id is None or _artifact_is_owned_by(
            artifact,
            self._artifact_owner_id,
        ):
            return
        raise ApiError(
            f"RAGFlow {artifact_type} owner does not match configured interactive owner",
            status_code=200,
            payload={"artifact_id": str(artifact.get("id") or "")},
        )

    def list_datasets(
        self,
        *,
        name: str | None = None,
        parse_status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if name:
            params["name"] = name
        if parse_status:
            params["parse_status"] = parse_status
        try:
            data = unwrap_response(self._client.get("/api/v1/datasets", params=params))
        except ApiError as exc:
            if name and _is_missing_dataset_name_response(exc.payload, name):
                return []
            raise
        return _mapping_list(data, endpoint="datasets", container_keys=("datasets",))

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        data = unwrap_response(self._client.get(f"/api/v1/datasets/{dataset_id}"))
        if isinstance(data, dict):
            return data
        msg = f"unexpected dataset response for {dataset_id}"
        raise TypeError(msg)

    def create_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.post("/api/v1/datasets", json=payload))
        if isinstance(data, dict):
            datasets_created_total.inc()
            return data
        msg = "unexpected dataset create response"
        raise TypeError(msg)

    def update_dataset(self, dataset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.put(f"/api/v1/datasets/{dataset_id}", json=payload))
        if isinstance(data, dict):
            return data
        msg = f"unexpected dataset update response for {dataset_id}"
        raise TypeError(msg)

    def upload_document(
        self,
        dataset_id: str,
        *,
        document_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        self.verify_artifact_owner()
        files = {"file": (document_name, content, mime_type)}
        data = unwrap_response(
            self._client.post(f"/api/v1/datasets/{dataset_id}/documents", files=files)
        )
        document: dict[str, Any] | None = None
        if isinstance(data, dict):
            document = dict(data)
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            document = dict(data[0])
        document_id = (document or {}).get("id") or (document or {}).get("document_id")
        if document is None or not str(document_id or "").strip():
            raise ApiError(
                "RAGFlow document upload response did not contain a document id",
                status_code=200,
                payload=data,
            )
        files_uploaded_total.inc()
        return document

    def update_document_metadata(
        self,
        dataset_id: str,
        document_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(
            self._client.put(
                f"/api/v1/datasets/{dataset_id}/documents/{document_id}/metadata/config",
                json={"metadata": metadata},
            )
        )
        if isinstance(data, dict):
            return data
        return {"data": data}

    def rename_document(
        self,
        dataset_id: str,
        document_id: str,
        document_name: str,
    ) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(
            self._client.put(
                f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
                json={"name": document_name},
            )
        )
        if isinstance(data, dict):
            return data
        return {"data": data}

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> Any:
        try:
            return self._delete_documents_once(dataset_id, document_ids)
        except ApiError as exc:
            if exc.status_code != 200 or not _is_missing_document_delete_response(exc.payload):
                raise
            if len(document_ids) <= 1:
                return exc.payload
            results = []
            for document_id in document_ids:
                try:
                    results.append(self._delete_documents_once(dataset_id, [document_id]))
                except ApiError as single_exc:
                    if single_exc.status_code == 200 and _is_missing_document_delete_response(
                        single_exc.payload
                    ):
                        continue
                    raise
            return results

    def delete_datasets(self, dataset_ids: list[str]) -> Any:
        self.verify_artifact_owner()
        try:
            return unwrap_response(
                self._client.request("DELETE", "/api/v1/datasets", json={"ids": dataset_ids})
            )
        except ApiError as exc:
            if exc.status_code == 200 and _is_missing_dataset_delete_response(exc.payload):
                return exc.payload
            raise

    def delete_chats(self, chat_ids: list[str]) -> Any:
        self.verify_artifact_owner()
        try:
            return unwrap_response(
                self._client.request("DELETE", "/api/v1/chats", json={"ids": chat_ids})
            )
        except ApiError as exc:
            if exc.status_code == 200 and _is_missing_chat_response(exc.payload):
                return exc.payload
            raise

    def _delete_documents_once(self, dataset_id: str, document_ids: list[str]) -> Any:
        self.verify_artifact_owner()
        result = unwrap_response(
            self._client.request(
                "DELETE",
                f"/api/v1/datasets/{dataset_id}/documents",
                json={"ids": document_ids},
            )
        )
        files_deleted_total.inc(len(document_ids))
        return result

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> Any:
        self.verify_artifact_owner()
        result = unwrap_response(
            self._client.post(
                f"/api/v1/datasets/{dataset_id}/chunks",
                json={"document_ids": document_ids},
            )
        )
        parse_started_total.inc(len(document_ids))
        return result

    def list_documents(
        self,
        dataset_id: str,
        *,
        run: str | None = None,
        keywords: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if run:
            params["run"] = run
        if keywords:
            params["keywords"] = keywords
        if page is not None:
            if page < 1:
                raise ValueError("page must be greater than zero")
            params["page"] = str(page)
        if page_size is not None:
            if page_size < 1:
                raise ValueError("page_size must be greater than zero")
            params["page_size"] = str(min(page_size, RAGFLOW_MAX_DOCUMENT_PAGE_SIZE))
        data = unwrap_response(
            self._client.get(f"/api/v1/datasets/{dataset_id}/documents", params=params)
        )
        return _mapping_list(
            data,
            endpoint="documents",
            container_keys=("docs", "documents"),
        )

    def iter_documents(
        self,
        dataset_id: str,
        *,
        run: str | None = None,
        keywords: str | None = None,
        page_size: int = RAGFLOW_MAX_DOCUMENT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        if page_size < 1:
            raise ValueError("page_size must be greater than zero")
        effective_page_size = min(page_size, RAGFLOW_MAX_DOCUMENT_PAGE_SIZE)
        seen_pages: set[tuple[str, ...]] = set()
        page = 1
        while True:
            documents = self.list_documents(
                dataset_id,
                run=run,
                keywords=keywords,
                page=page,
                page_size=effective_page_size,
            )
            if not documents:
                return
            page_marker = tuple(
                json.dumps(document, ensure_ascii=False, sort_keys=True, default=str)
                for document in documents
            )
            if page_marker in seen_pages:
                raise ApiError(
                    "RAGFlow document pagination did not advance",
                    status_code=200,
                    payload={"dataset_id": dataset_id, "page": page},
                )
            yield from documents
            if len(documents) < effective_page_size:
                return
            seen_pages.add(page_marker)
            page += 1

    def list_chats(
        self,
        *,
        name: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if name:
            params["name"] = name
        if chat_id:
            params["id"] = chat_id
        if self._artifact_owner_id:
            params["owner_ids"] = self._artifact_owner_id
        data = unwrap_response(self._client.get("/api/v1/chats", params=params))
        chats = _mapping_list(data, endpoint="chats", container_keys=("chats",))
        return _owned_artifacts(chats, self._artifact_owner_id)

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        try:
            data = unwrap_response(self._client.get(f"/api/v1/chats/{chat_id}"))
        except ApiError as exc:
            if _is_missing_chat_response(exc.payload) or (
                self._artifact_owner_id
                and _is_artifact_access_denied_response(exc.payload)
            ):
                return None
            raise
        if isinstance(data, dict) and _artifact_is_owned_by(data, self._artifact_owner_id):
            return data
        if isinstance(data, dict):
            return None
        msg = f"unexpected chat response for {chat_id}"
        raise TypeError(msg)

    def create_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.post("/api/v1/chats", json=payload))
        if isinstance(data, dict):
            self._require_owned_artifact(data, artifact_type="chat")
            return data
        msg = "unexpected chat create response"
        raise TypeError(msg)

    def update_chat(self, chat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.patch(f"/api/v1/chats/{chat_id}", json=payload))
        if isinstance(data, dict):
            self._require_owned_artifact(data, artifact_type="chat")
            return data
        msg = f"unexpected chat update response for {chat_id}"
        raise TypeError(msg)

    def list_searches(
        self,
        *,
        keywords: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if keywords:
            params["keywords"] = keywords
        if page is not None:
            params["page"] = str(page)
        if page_size is not None:
            params["page_size"] = str(page_size)
        if self._artifact_owner_id:
            params["owner_ids"] = self._artifact_owner_id
        data = unwrap_response(self._client.get("/api/v1/searches", params=params))
        searches = _mapping_list(
            data,
            endpoint="searches",
            container_keys=("search_apps", "searches"),
        )
        return _owned_artifacts(searches, self._artifact_owner_id)

    def get_search(self, search_id: str) -> dict[str, Any] | None:
        try:
            data = unwrap_response(self._client.get(f"/api/v1/searches/{search_id}"))
        except ApiError as exc:
            if _is_missing_search_response(exc.payload) or (
                self._artifact_owner_id
                and _is_artifact_access_denied_response(exc.payload)
            ):
                return None
            raise
        if isinstance(data, dict) and _artifact_is_owned_by(data, self._artifact_owner_id):
            return data
        if isinstance(data, dict):
            return None
        msg = f"unexpected search app response for {search_id}"
        raise TypeError(msg)

    def create_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.post("/api/v1/searches", json=payload))
        if isinstance(data, dict):
            return data
        msg = "unexpected search app create response"
        raise TypeError(msg)

    def update_search(self, search_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.verify_artifact_owner()
        data = unwrap_response(self._client.put(f"/api/v1/searches/{search_id}", json=payload))
        if isinstance(data, dict):
            return data
        msg = f"unexpected search app update response for {search_id}"
        raise TypeError(msg)

    def delete_search(self, search_id: str) -> Any:
        self.verify_artifact_owner()
        try:
            return unwrap_response(self._client.delete(f"/api/v1/searches/{search_id}"))
        except ApiError as exc:
            if exc.status_code == 200 and _is_missing_search_response(exc.payload):
                return exc.payload
            raise

    def retrieve_chunks(
        self,
        *,
        dataset_id: str,
        question: str,
        top_k: int = 5,
        page_size: int | None = None,
        retrieval_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": question,
            "dataset_ids": [dataset_id],
        }
        if retrieval_options:
            payload.update(
                {
                    key: value
                    for key, value in retrieval_options.items()
                    if value not in (None, "", [], {})
                }
            )
        else:
            payload["top_k"] = top_k
            if page_size is not None:
                payload["page_size"] = page_size
        data = self._retrieve_chunks_with_retries(payload)
        if isinstance(data, dict):
            return data
        return {"chunks": list(data or [])}

    def _retrieve_chunks_with_retries(self, payload: dict[str, Any]) -> dict[str, Any] | list[Any]:
        diagnostics: dict[str, Any] = {
            "rerank_retry": False,
            "compatibility_retry": False,
            "retrieval_payload_top_k": payload.get("top_k"),
            "retrieval_payload_page_size": payload.get("page_size"),
        }
        try:
            data = unwrap_response(self._client.post("/api/v1/retrieval", json=payload))
            return _with_retrieval_diagnostics(data, diagnostics)
        except ApiError as exc:
            if not payload.get("rerank_id") or not _is_rerank_retrieval_error(exc.payload):
                if not _is_retrieval_option_error(exc.payload):
                    raise
            else:
                retry_payload = dict(payload)
                retry_payload.pop("rerank_id", None)
                diagnostics["rerank_retry"] = True
                try:
                    data = unwrap_response(
                        self._client.post("/api/v1/retrieval", json=retry_payload)
                    )
                    return _with_retrieval_diagnostics(data, diagnostics)
                except ApiError as retry_exc:
                    if not _is_retrieval_option_error(retry_exc.payload):
                        raise
                    payload = retry_payload

        compatibility_payload = {
            key: payload[key]
            for key in (
                "question",
                "dataset_ids",
                "document_ids",
                "page",
                "page_size",
                "similarity_threshold",
                "vector_similarity_weight",
                "top_k",
            )
            if key in payload
        }
        diagnostics["compatibility_retry"] = True
        data = unwrap_response(self._client.post("/api/v1/retrieval", json=compatibility_payload))
        return _with_retrieval_diagnostics(data, diagnostics)

    def chat_completion(
        self,
        *,
        chat_id: str,
        messages: list[dict[str, Any]],
        model: str = "model",
        stream: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "model": model or "model",
            "messages": messages,
            "stream": stream,
            "extra_body": {
                "reference": True,
                "reference_metadata": {
                    "include": True,
                    "fields": list(RAGFLOW_REFERENCE_METADATA_FIELDS),
                },
            },
        }
        try:
            path = f"/api/v1/openai/{chat_id}/chat/completions"
            data = (
                self._collect_streaming_chat_completion(path, payload)
                if stream
                else unwrap_response(self._client.post(path, json=payload))
            )
        except ApiError as exc:
            if not _is_missing_openai_chat_completion_endpoint(exc):
                raise
            try:
                path = f"/api/v1/chats_openai/{chat_id}/chat/completions"
                data = (
                    self._collect_streaming_chat_completion(path, payload)
                    if stream
                    else unwrap_response(self._client.post(path, json=payload))
                )
            except ApiError as fallback_exc:
                if not _is_missing_openai_chat_completion_endpoint(fallback_exc):
                    raise
                fallback_payload = {"chat_id": chat_id, "messages": messages, "stream": stream}
                data = (
                    self._collect_streaming_chat_completion(
                        "/api/v1/chat/completions",
                        fallback_payload,
                    )
                    if stream
                    else unwrap_response(
                        self._client.post(
                            "/api/v1/chat/completions",
                            json=fallback_payload,
                        )
                    )
                )
        if isinstance(data, dict):
            return data
        return {"content": str(data or "")}

    def _collect_streaming_chat_completion(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        answer_parts: list[str] = []
        last_data: dict[str, Any] = {}
        reference: dict[str, Any] | None = None
        with self._client.stream("POST", path, json=payload) as response:
            if response.is_error:
                raise ApiError(
                    f"HTTP {response.status_code} returned by POST {response.request.url}",
                    status_code=response.status_code,
                    payload=response.text,
                )
            for raw_line in response.iter_lines():
                line = (
                    raw_line.decode("utf-8", "replace")
                    if isinstance(raw_line, bytes)
                    else raw_line
                )
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                event = line.removeprefix("data:").strip()
                if event == "[DONE]":
                    break
                try:
                    payload_data = json.loads(event)
                except ValueError:
                    continue
                data = (
                    payload_data.get("data")
                    if isinstance(payload_data, dict) and "data" in payload_data
                    else payload_data
                )
                if data is True:
                    break
                if not isinstance(data, dict):
                    continue
                last_data.update(data)
                if answer := _streaming_answer_fragment(data):
                    _merge_streamed_answer(answer_parts, answer)
                if streaming_reference := _streaming_reference(data):
                    reference = streaming_reference
        if answer_parts:
            last_data["answer"] = "".join(answer_parts)
        if reference is not None:
            last_data["reference"] = reference
        return {"data": last_data}


def _merge_streamed_answer(answer_parts: list[str], answer: str) -> None:
    current = "".join(answer_parts)
    if not answer or answer == current or current.endswith(answer):
        return
    if answer.startswith(current):
        answer_parts[:] = [answer]
        return
    answer_parts.append(answer)


def _mapping_list(
    data: Any,
    *,
    endpoint: str,
    container_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    value = data
    if isinstance(data, dict):
        matching_key = next((key for key in container_keys if key in data), None)
        if matching_key is None:
            raise ApiError(
                f"unexpected list response from RAGFlow {endpoint} endpoint",
                payload=data,
            )
        value = data[matching_key]
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ApiError(
            f"unexpected list response from RAGFlow {endpoint} endpoint",
            payload=data,
        )
    return [dict(item) for item in value]


def _owned_artifacts(
    artifacts: list[dict[str, Any]],
    owner_id: str | None,
) -> list[dict[str, Any]]:
    if owner_id is None:
        return artifacts
    return [artifact for artifact in artifacts if _artifact_is_owned_by(artifact, owner_id)]


def _artifact_is_owned_by(artifact: dict[str, Any], owner_id: str | None) -> bool:
    if owner_id is None:
        return True
    owner_values: list[str] = []
    for field_name in ("tenant_id", "created_by"):
        value = artifact.get(field_name)
        if isinstance(value, dict):
            value = value.get("id")
        normalized = str(value or "").strip()
        if normalized:
            owner_values.append(normalized)
    return bool(owner_values) and all(value == owner_id for value in owner_values)


def _streaming_answer_fragment(data: dict[str, Any]) -> str:
    if data.get("answer"):
        return str(data["answer"])
    if data.get("content"):
        return str(data["content"])
    choices = data.get("choices")
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            parts.append(str(delta["content"]))
            continue
        message = choice.get("message")
        if isinstance(message, dict) and message.get("content"):
            parts.append(str(message["content"]))
            continue
        if choice.get("text"):
            parts.append(str(choice["text"]))
    return "".join(parts)


def _streaming_reference(data: dict[str, Any]) -> dict[str, Any] | None:
    reference = data.get("reference")
    if isinstance(reference, dict):
        return dict(reference)
    choices = data.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for key in ("delta", "message"):
            container = choice.get(key)
            if not isinstance(container, dict):
                continue
            reference = container.get("reference")
            if isinstance(reference, dict):
                return dict(reference)
    return None


def _is_missing_dataset_name_response(payload: Any, name: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") not in (102, "102"):
        return False
    message = str(payload.get("message", ""))
    return "lacks permission for dataset" in message and f"'{name}'" in message


def _is_missing_document_delete_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") not in (102, "102"):
        return False
    message = str(payload.get("message", ""))
    return "Document not found" in message or "do not belong to dataset" in message


def _is_missing_dataset_delete_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") not in (102, "102"):
        return False
    message = str(payload.get("message", "")).lower()
    return "dataset" in message and (
        "not found" in message
        or "doesn't exist" in message
        or "does not exist" in message
        or "not exist" in message
    )


def _is_missing_chat_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") not in (102, "102"):
        return False
    message = str(payload.get("message", ""))
    return "chat" in message.lower() and "not found" in message.lower()


def _is_missing_search_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") not in (102, "102", 404, "404"):
        return False
    message = str(payload.get("message", "")).lower()
    return "search" in message and ("not found" in message or "can't find" in message)


def _is_artifact_access_denied_response(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("code") not in (103, "103", 109, "109"):
        return False
    message = str(payload.get("message", "")).lower()
    return "authorization" in message or "permission" in message


def _with_retrieval_diagnostics(
    data: Any,
    diagnostics: dict[str, Any],
) -> dict[str, Any] | list[Any]:
    if isinstance(data, dict):
        data.setdefault("_connector_retrieval_diagnostics", diagnostics)
        return data
    if isinstance(data, list):
        return data
    return []


def _is_rerank_retrieval_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    message = str(payload.get("message", "")).lower()
    return "rerank" in message or "reranker" in message or (
        "model" in message and ("authorized" in message or "not found" in message)
    )


def _is_retrieval_option_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    message = str(payload.get("message", "")).lower()
    if payload.get("code") not in (100, 101, 102, 400, "100", "101", "102", "400"):
        return False
    return any(
        marker in message
        for marker in (
            "unexpected",
            "unknown",
            "invalid",
            "not allowed",
            "unsupported",
            "keyword",
            "highlight",
            "cross_languages",
            "metadata_condition",
            "use_kg",
            "toc_enhance",
            "default chat model",
        )
    )


def _is_missing_openai_chat_completion_endpoint(exc: ApiError) -> bool:
    if exc.status_code == 404:
        return True
    payload = exc.payload
    if not isinstance(payload, dict):
        return False
    message = str(payload.get("message", "")).lower()
    return payload.get("code") in (101, 102, "101", "102") and (
        "not found" in message
        or "doesn't exist" in message
        or "does not exist" in message
        or "not exist" in message
    )
