from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.seafile_admin import SeafileAdminClient


class _FakeHttpClient:
    def get(self, path: str, *, params: dict[str, str | int]) -> httpx.Response:
        request = httpx.Request("GET", f"http://seafile.local{path}")
        return httpx.Response(
            200,
            json={
                "repos": [
                    {
                        "id": "repo-1",
                        "name": "Meine Bibliothek",
                        "head_commit_id": "commit-1",
                    }
                ]
            },
            request=request,
        )

    def close(self) -> None:
        return None


class SeafileAdminClientTests(unittest.TestCase):
    def test_accepts_admin_libraries_repos_shape(self) -> None:
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = _FakeHttpClient()  # type: ignore[assignment]

        libraries = client.list_libraries()

        self.assertEqual(len(libraries), 1)
        self.assertEqual(libraries[0]["id"], "repo-1")


if __name__ == "__main__":
    unittest.main()
