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


class _ShareHttpClient:
    def __init__(
        self,
        shares: list[dict[str, str]] | None = None,
        *,
        persist_on_post: bool = True,
        post_status: int = 200,
    ) -> None:
        self.shares = list(shares or [])
        self.persist_on_post = persist_on_post
        self.post_status = post_status
        self.posts: list[dict[str, str]] = []

    def get(self, path: str, *, params: dict[str, str | int] | None = None) -> httpx.Response:
        request = httpx.Request("GET", f"http://seafile.local{path}")
        assert params == {"repo_id": "repo-1", "share_type": "user"}
        return httpx.Response(200, json={"shares": self.shares}, request=request)

    def post(self, path: str, *, data: dict[str, str]) -> httpx.Response:
        request = httpx.Request("POST", f"http://seafile.local{path}")
        self.posts.append(dict(data))
        if self.persist_on_post:
            self.shares.append(
                {
                    "repo_id": data["repo_id"],
                    "share_type": data["share_type"],
                    "path": data["path"],
                    "user_email": data["share_to"],
                    "permission": data["permission"],
                }
            )
        return httpx.Response(
            self.post_status,
            json={"failed": [{"reason": "response is not authoritative"}]},
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

    def test_existing_read_or_write_share_is_never_changed(self) -> None:
        for permission in ("r", "rw"):
            with self.subTest(permission=permission):
                fake = _ShareHttpClient(
                    [
                        {
                            "share_type": "user",
                            "path": "/",
                            "user_email": "sync@auth.local",
                            "permission": permission,
                        }
                    ]
                )
                client = SeafileAdminClient("http://seafile.local", "token")
                client._client = fake  # type: ignore[assignment]

                created = client.ensure_read_only_user_share(
                    "repo-1",
                    "sync@auth.local",
                )

                self.assertFalse(created)
                self.assertEqual(fake.posts, [])
                self.assertEqual(fake.shares[0]["permission"], permission)

    def test_creates_exact_read_only_root_share_and_verifies_with_get(self) -> None:
        fake = _ShareHttpClient()
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = fake  # type: ignore[assignment]

        created = client.ensure_read_only_user_share(
            "repo-1",
            "sync@auth.local",
        )

        self.assertTrue(created)
        self.assertEqual(
            fake.posts,
            [
                {
                    "repo_id": "repo-1",
                    "share_type": "user",
                    "path": "/",
                    "share_to": "sync@auth.local",
                    "permission": "r",
                }
            ],
        )

    def test_post_success_without_verified_share_fails_closed(self) -> None:
        fake = _ShareHttpClient(persist_on_post=False)
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = fake  # type: ignore[assignment]

        with self.assertRaisesRegex(RuntimeError, "did not persist"):
            client.ensure_read_only_user_share("repo-1", "sync@auth.local")

    def test_concurrent_share_after_failed_post_is_accepted_after_get(self) -> None:
        fake = _ShareHttpClient(post_status=409)
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = fake  # type: ignore[assignment]

        self.assertTrue(
            client.ensure_read_only_user_share("repo-1", "sync@auth.local")
        )

    def test_existing_unsupported_root_permission_is_not_mutated(self) -> None:
        fake = _ShareHttpClient(
            [
                {
                    "share_type": "user",
                    "path": "/",
                    "user_email": "sync@auth.local",
                    "permission": "admin",
                }
            ]
        )
        client = SeafileAdminClient("http://seafile.local", "token")
        client._client = fake  # type: ignore[assignment]

        with self.assertRaisesRegex(RuntimeError, "unsupported permission"):
            client.ensure_read_only_user_share("repo-1", "sync@auth.local")
        self.assertEqual(fake.posts, [])


if __name__ == "__main__":
    unittest.main()
