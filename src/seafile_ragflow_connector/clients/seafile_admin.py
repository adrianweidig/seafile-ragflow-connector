from __future__ import annotations

from collections.abc import Generator
from typing import Any

from seafile_ragflow_connector.clients.http import VerifyConfig, make_client, unwrap_response


class SeafileAdminClient:
    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        timeout: float = 60.0,
        verify: VerifyConfig = True,
    ) -> None:
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Token {admin_token}"},
            timeout=timeout,
            verify=verify,
        )

    def close(self) -> None:
        self._client.close()

    def list_libraries(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
        owner: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"page": page, "per_page": per_page}
        if owner:
            params["owner"] = owner
        data = unwrap_response(self._client.get("/api/v2.1/admin/libraries/", params=params))
        if isinstance(data, dict) and "repos" in data:
            return list(data["repos"])
        if isinstance(data, dict) and "repo_list" in data:
            return list(data["repo_list"])
        if isinstance(data, dict) and "libraries" in data:
            return list(data["libraries"])
        return list(data or [])

    def iter_libraries(
        self,
        *,
        per_page: int = 100,
        owner: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        page = 1
        while True:
            libraries = self.list_libraries(page=page, per_page=per_page, owner=owner)
            if not libraries:
                break
            yield from libraries
            if len(libraries) < per_page:
                break
            page += 1

    def list_library_shares(self, repo_id: str, *, share_type: str) -> list[dict[str, Any]]:
        params = {"repo_id": repo_id, "share_type": share_type}
        data = unwrap_response(self._client.get("/api/v2.1/admin/shares/", params=params))
        if isinstance(data, dict):
            for key in ("shares", "share_list", "items", "data"):
                if isinstance(data.get(key), list):
                    return list(data[key])
            return [data]
        return list(data or [])

    def list_users(
        self,
        *,
        page: int = 1,
        per_page: int = 100,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"page": page, "per_page": per_page}
        if source:
            params["source"] = source
        data = unwrap_response(self._client.get("/api/v2.1/admin/users/", params=params))
        if isinstance(data, dict):
            for key in ("users", "user_list", "items", "data"):
                if isinstance(data.get(key), list):
                    return list(data[key])
            return [data]
        return list(data or [])

    def iter_users(self, *, per_page: int = 100) -> Generator[dict[str, Any], None, None]:
        for source in ("db", "ldapimport"):
            page = 1
            while True:
                users = self.list_users(page=page, per_page=per_page, source=source)
                if not users:
                    break
                yield from users
                if len(users) < per_page:
                    break
                page += 1

    def list_group_members(self, group_id: str | int) -> list[dict[str, Any]]:
        data = unwrap_response(self._client.get(f"/api/v2.1/admin/groups/{group_id}/members/"))
        if isinstance(data, dict):
            for key in ("members", "member_list", "users", "items", "data"):
                if isinstance(data.get(key), list):
                    return list(data[key])
            return [data]
        return list(data or [])
