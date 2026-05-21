from __future__ import annotations

from typing import Any

from seafile_ragflow_connector.clients.http import ApiError, VerifyConfig, make_client, unwrap_response


class RAGFlowClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        verify: VerifyConfig = True,
    ) -> None:
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            verify=verify,
        )

    def close(self) -> None:
        self._client.close()

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
        if isinstance(data, dict) and "datasets" in data:
            return list(data["datasets"])
        return list(data or [])

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        data = unwrap_response(self._client.get(f"/api/v1/datasets/{dataset_id}"))
        if isinstance(data, dict):
            return data
        msg = f"unexpected dataset response for {dataset_id}"
        raise TypeError(msg)

    def create_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = unwrap_response(self._client.post("/api/v1/datasets", json=payload))
        if isinstance(data, dict):
            return data
        msg = "unexpected dataset create response"
        raise TypeError(msg)

    def upload_document(
        self,
        dataset_id: str,
        *,
        document_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        files = {"file": (document_name, content, mime_type)}
        data = unwrap_response(
            self._client.post(f"/api/v1/datasets/{dataset_id}/documents", files=files)
        )
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        msg = "unexpected document upload response"
        raise TypeError(msg)

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> Any:
        try:
            return self._delete_documents_once(dataset_id, document_ids)
        except ApiError as exc:
            if not _is_missing_document_delete_response(exc.payload):
                raise
            if len(document_ids) <= 1:
                return exc.payload
            results = []
            for document_id in document_ids:
                try:
                    results.append(self._delete_documents_once(dataset_id, [document_id]))
                except ApiError as single_exc:
                    if _is_missing_document_delete_response(single_exc.payload):
                        continue
                    raise
            return results

    def delete_datasets(self, dataset_ids: list[str]) -> Any:
        try:
            return unwrap_response(
                self._client.request("DELETE", "/api/v1/datasets", json={"ids": dataset_ids})
            )
        except ApiError as exc:
            if _is_missing_dataset_delete_response(exc.payload):
                return exc.payload
            raise

    def delete_chats(self, chat_ids: list[str]) -> Any:
        try:
            return unwrap_response(
                self._client.request("DELETE", "/api/v1/chats", json={"ids": chat_ids})
            )
        except ApiError as exc:
            if _is_missing_chat_response(exc.payload):
                return exc.payload
            raise

    def _delete_documents_once(self, dataset_id: str, document_ids: list[str]) -> Any:
        return unwrap_response(
            self._client.request(
                "DELETE",
                f"/api/v1/datasets/{dataset_id}/documents",
                json={"ids": document_ids},
            )
        )

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> Any:
        return unwrap_response(
            self._client.post(
                f"/api/v1/datasets/{dataset_id}/chunks",
                json={"document_ids": document_ids},
            )
        )

    def list_documents(
        self,
        dataset_id: str,
        *,
        run: str | None = None,
        keywords: str | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if run:
            params["run"] = run
        if keywords:
            params["keywords"] = keywords
        if page_size:
            params["page_size"] = str(page_size)
        data = unwrap_response(
            self._client.get(f"/api/v1/datasets/{dataset_id}/documents", params=params)
        )
        if isinstance(data, dict) and "docs" in data:
            return list(data["docs"])
        if isinstance(data, dict) and "documents" in data:
            return list(data["documents"])
        return list(data or [])

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
        data = unwrap_response(self._client.get("/api/v1/chats", params=params))
        if isinstance(data, dict) and "chats" in data:
            return list(data["chats"])
        return list(data or [])

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        try:
            data = unwrap_response(self._client.get(f"/api/v1/chats/{chat_id}"))
        except ApiError as exc:
            if _is_missing_chat_response(exc.payload):
                return None
            raise
        if isinstance(data, dict):
            return data
        msg = f"unexpected chat response for {chat_id}"
        raise TypeError(msg)

    def create_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = unwrap_response(self._client.post("/api/v1/chats", json=payload))
        if isinstance(data, dict):
            return data
        msg = "unexpected chat create response"
        raise TypeError(msg)

    def update_chat(self, chat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = unwrap_response(self._client.patch(f"/api/v1/chats/{chat_id}", json=payload))
        if isinstance(data, dict):
            return data
        msg = f"unexpected chat update response for {chat_id}"
        raise TypeError(msg)

    def retrieve_chunks(
        self,
        *,
        dataset_id: str,
        question: str,
        top_k: int = 5,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": question,
            "dataset_ids": [dataset_id],
            "top_k": top_k,
        }
        if page_size is not None:
            payload["page_size"] = page_size
        data = unwrap_response(self._client.post("/api/v1/retrieval", json=payload))
        if isinstance(data, dict):
            return data
        return {"chunks": list(data or [])}

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
            "extra_body": {"reference": True},
        }
        try:
            data = unwrap_response(
                self._client.post(
                    f"/api/v1/openai/{chat_id}/chat/completions",
                    json=payload,
                )
            )
        except ApiError as exc:
            if not _is_missing_openai_chat_completion_endpoint(exc):
                raise
            try:
                data = unwrap_response(
                    self._client.post(
                        f"/api/v1/chats_openai/{chat_id}/chat/completions",
                        json=payload,
                    )
                )
            except ApiError as fallback_exc:
                if not _is_missing_openai_chat_completion_endpoint(fallback_exc):
                    raise
                data = unwrap_response(
                    self._client.post(
                        "/api/v1/chat/completions",
                        json={"chat_id": chat_id, "messages": messages, "stream": stream},
                    )
                )
        if isinstance(data, dict):
            return data
        return {"content": str(data or "")}


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
