from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from seafile_ragflow_connector.clients.http import ApiError


@dataclass(frozen=True)
class OpenWebUICapabilities:
    reachable: bool
    functions_list: bool = False
    functions_write: bool = False
    functions_valves: bool = False
    tools_list: bool = False
    tools_write: bool = False
    tools_valves: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "functions_list": self.functions_list,
            "functions_write": self.functions_write,
            "functions_valves": self.functions_valves,
            "tools_list": self.tools_list,
            "tools_write": self.tools_write,
            "tools_valves": self.tools_valves,
            "error": self.error,
        }


class OpenWebUIClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            verify=verify_ssl,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def healthcheck(self) -> dict[str, Any]:
        return _json_dict(self._client.get("/api/v1/functions/list"))

    def probe_capabilities(self) -> OpenWebUICapabilities:
        try:
            functions_list = self._is_available("GET", "/api/v1/functions/list")
            tools_list = self._is_available("GET", "/api/v1/tools/list")
        except Exception as exc:
            return OpenWebUICapabilities(reachable=False, error=str(exc))
        return OpenWebUICapabilities(
            reachable=functions_list or tools_list,
            functions_list=functions_list,
            functions_write=functions_list,
            functions_valves=functions_list,
            tools_list=tools_list,
            tools_write=tools_list,
            tools_valves=tools_list,
        )

    def list_functions(self) -> list[dict[str, Any]]:
        data = _json(
            self._client.get(
                "/api/v1/functions/export",
                params={"include_valves": "true"},
            )
        )
        return list(data or [])

    def get_function(self, function_id: str) -> dict[str, Any] | None:
        response = self._client.get(f"/api/v1/functions/id/{function_id}")
        if _is_missing_artifact_response(response):
            return None
        return _json_dict(response)

    def create_function(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(self._client.post("/api/v1/functions/create", json=payload))

    def update_function(self, function_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(
            self._client.post(f"/api/v1/functions/id/{function_id}/update", json=payload)
        )

    def update_function_valves(self, function_id: str, valves: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(
            self._client.post(
                f"/api/v1/functions/id/{function_id}/valves/update",
                json=valves,
            )
        )

    def delete_function(self, function_id: str) -> bool:
        return _delete_result(self._client.delete(f"/api/v1/functions/id/{function_id}/delete"))

    def ensure_function_active(self, function_id: str) -> dict[str, Any] | None:
        function = self.get_function(function_id)
        if function and not bool(function.get("is_active")):
            return _json_dict(self._client.post(f"/api/v1/functions/id/{function_id}/toggle"))
        return function

    def list_tools(self) -> list[dict[str, Any]]:
        data = _json(self._client.get("/api/v1/tools/export"))
        return list(data or [])

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        response = self._client.get(f"/api/v1/tools/id/{tool_id}")
        if _is_missing_artifact_response(response):
            return None
        return _json_dict(response)

    def create_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(self._client.post("/api/v1/tools/create", json=payload))

    def update_tool(self, tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(self._client.post(f"/api/v1/tools/id/{tool_id}/update", json=payload))

    def update_tool_valves(self, tool_id: str, valves: dict[str, Any]) -> dict[str, Any]:
        return _json_dict(
            self._client.post(f"/api/v1/tools/id/{tool_id}/valves/update", json=valves)
        )

    def delete_tool(self, tool_id: str) -> bool:
        return _delete_result(self._client.delete(f"/api/v1/tools/id/{tool_id}/delete"))

    def _is_available(self, method: str, path: str) -> bool:
        response = self._client.request(method, path)
        if response.status_code in {200, 204}:
            return True
        if response.status_code in {401, 403}:
            raise ApiError(
                f"OpenWebUI API rejected credentials for {path}",
                status_code=response.status_code,
                payload=_safe_payload(response),
            )
        return False


def _json(response: httpx.Response) -> Any:
    payload = _safe_payload(response)
    if response.is_error:
        method = response.request.method
        url = response.request.url
        raise ApiError(
            f"HTTP {response.status_code} returned by {method} {url}",
            status_code=response.status_code,
            payload=payload,
        )
    return payload


def _json_dict(response: httpx.Response) -> dict[str, Any]:
    payload = _json(response)
    if isinstance(payload, dict):
        return payload
    return {"value": payload}


def _delete_result(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return False
    payload = _safe_payload(response)
    if response.status_code == 401 and _payload_is_not_found(payload):
        return False
    if response.is_error:
        method = response.request.method
        url = response.request.url
        raise ApiError(
            f"HTTP {response.status_code} returned by {method} {url}",
            status_code=response.status_code,
            payload=payload,
        )
    return bool(payload) if isinstance(payload, bool) else True


def _is_missing_artifact_response(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code == 401 and _payload_is_not_found(_safe_payload(response)):
        return True
    return False


def _payload_is_not_found(payload: Any) -> bool:
    if isinstance(payload, dict):
        detail = str(payload.get("detail") or payload.get("message") or "").lower()
    else:
        detail = str(payload).lower()
    return "not found" in detail or "could not find" in detail


def _safe_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
