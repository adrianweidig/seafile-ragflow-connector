from __future__ import annotations

import unittest

import httpx

from seafile_ragflow_connector.clients.seafile_admin import SeafileAdminClient


class _FakeHttpClient:
    def __init__(self) -> None:
        self.user_sources: list[str | None] = []

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
        if path == "/api/v2.1/admin/users/":
            source = str((params or {}).get("source") or "")
            self.user_sources.append(source or None)
            users_by_source = {
                "db": [{"email": "admin@example.local", "contact_email": "admin@example.local"}],
                "ldapimport": [
                    {"email": "ldap-internal@auth.local", "contact_email": "ldap@example.local"}
                ],
            }
            return httpx.Response(
                200,
                json={"data": users_by_source.get(source, [])},
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

    def test_iter_users_reads_db_and_ldapimport_sources(self) -> None:
        fake = _FakeHttpClient()
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = fake  # type: ignore[assignment]

        users = list(client.iter_users())

        self.assertEqual(
            users,
            [
                {"email": "admin@example.local", "contact_email": "admin@example.local"},
                {"email": "ldap-internal@auth.local", "contact_email": "ldap@example.local"},
            ],
        )
        self.assertEqual(fake.user_sources, ["db", "ldapimport"])


if __name__ == "__main__":
    unittest.main()
