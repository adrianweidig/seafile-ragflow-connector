from __future__ import annotations

from typing import Any

from seafile_ragflow_connector.clients.http import ApiError, make_client, unwrap_response


class RAGFlowClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 60.0) -> None:
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None) -> list[dict[str, Any]]:
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
        data = unwrap_response(self._client.post(f"/api/v1/datasets/{dataset_id}/documents", files=files))
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
        data = unwrap_response(self._client.get(f"/api/v1/datasets/{dataset_id}/documents", params=params))
        if isinstance(data, dict) and "docs" in data:
            return list(data["docs"])
        if isinstance(data, dict) and "documents" in data:
            return list(data["documents"])
        return list(data or [])


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
