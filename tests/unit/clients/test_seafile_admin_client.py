from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.seafile_admin import SeafileAdminClient


class _FakeHttpClient:
    def get(self, path: str, *, params: dict[str, str | int] | None = None) -> httpx.Response:
        request = httpx.Request("GET", f"http://seafile.local{path}")
        if path == "/api/v2.1/admin/shares/":
            return httpx.Response(
                200,
                json={"shares": [{"user_email": "olaf@example.local", "permission": "rw"}]},
                request=request,
            )
        if path == "/api/v2.1/admin/groups/42/members/":
            return httpx.Response(
                200,
                json={"members": [{"email": "carla@example.local"}]},
                request=request,
            )
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

    def test_reads_library_shares_and_group_members(self) -> None:
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = _FakeHttpClient()  # type: ignore[assignment]

        shares = client.list_library_shares("repo-1", share_type="user")
        members = client.list_group_members("42")

        self.assertEqual(shares[0]["user_email"], "olaf@example.local")
        self.assertEqual(members[0]["email"], "carla@example.local")


if __name__ == "__main__":
    unittest.main()
