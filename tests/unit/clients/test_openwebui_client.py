from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.openwebui import OpenWebUIClient


class _OpenWebUIHttpClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object] | None]] = []

    def request(self, method: str, path: str) -> httpx.Response:
        request = httpx.Request(method, f"http://openwebui.local{path}")
        return httpx.Response(200, json=[], request=request)

    def get(self, path: str, **kwargs) -> httpx.Response:
        request = httpx.Request("GET", f"http://openwebui.local{path}")
        if path.endswith("/missing"):
            return httpx.Response(404, json={"detail": "not found"}, request=request)
        if path.endswith("/unauthorized"):
            return httpx.Response(401, json={"detail": "unauthorized"}, request=request)
        return httpx.Response(
            200,
            json={"id": path.rsplit("/", 1)[-1], "is_active": False},
            request=request,
        )

    def post(self, path: str, *, json: dict[str, object] | None = None) -> httpx.Response:
        request = httpx.Request("POST", f"http://openwebui.local{path}")
        self.posts.append((path, json))
        return httpx.Response(200, json={"id": path, "ok": True}, request=request)

    def delete(self, path: str) -> httpx.Response:
        request = httpx.Request("DELETE", f"http://openwebui.local{path}")
        if path.endswith("/missing/delete"):
            return httpx.Response(401, json={"detail": "Not found"}, request=request)
        return httpx.Response(200, json=True, request=request)

    def close(self) -> None:
        return None


class OpenWebUIClientTests(unittest.TestCase):
    def test_capability_probe_and_function_tool_updates(self) -> None:
        http_client = _OpenWebUIHttpClient()
        client = OpenWebUIClient("http://openwebui.local", "admin")
        client._client = http_client  # type: ignore[assignment]

        capabilities = client.probe_capabilities()

        self.assertTrue(capabilities.functions_list)
        self.assertTrue(capabilities.tools_list)

        client.create_function({"id": "fn"})
        client.update_function("fn", {"id": "fn"})
        client.update_function_valves("fn", {"A": "B"})
        client.ensure_function_active("fn")
        client.create_tool({"id": "tool"})
        client.update_tool_valves("tool", {"A": "B"})
        self.assertTrue(client.delete_function("fn"))
        self.assertTrue(client.delete_tool("tool"))
        self.assertFalse(client.delete_function("missing"))
        self.assertFalse(client.delete_tool("missing"))

        paths = [path for path, _payload in http_client.posts]
        self.assertIn("/api/v1/functions/create", paths)
        self.assertIn("/api/v1/functions/id/fn/valves/update", paths)
        self.assertIn("/api/v1/functions/id/fn/toggle", paths)
        self.assertIn("/api/v1/tools/create", paths)

    def test_auth_errors_are_not_treated_as_missing_artifacts(self) -> None:
        http_client = _OpenWebUIHttpClient()
        client = OpenWebUIClient("http://openwebui.local", "admin")
        client._client = http_client  # type: ignore[assignment]

        with self.assertRaises(ApiError):
            client.get_function("unauthorized")

        with self.assertRaises(ApiError):
            client.get_tool("unauthorized")


if __name__ == "__main__":
    unittest.main()
