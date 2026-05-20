from __future__ import annotations

import time
from typing import Any
from urllib.parse import unquote

import httpx

from seafile_ragflow_connector.clients.http import make_client, unwrap_response


class SeafileSyncClient:
    def __init__(
        self,
        base_url: str,
        sync_token: str,
        *,
        timeout: float = 120.0,
        rewrite_download_urls: bool = False,
        rewrite_from: str | None = None,
        rewrite_to: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rewrite_download_urls = rewrite_download_urls
        self.rewrite_from = rewrite_from
        self.rewrite_to = rewrite_to
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Token {sync_token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def list_dir(self, repo_id: str, path: str = "/") -> list[dict[str, Any]]:
        data = unwrap_response(self._client.get(f"/api2/repos/{repo_id}/dir/", params={"p": path}))
        return list(data or [])

    def get_file_download_url(self, repo_id: str, path: str) -> str:
        data = unwrap_response(self._client.get(f"/api2/repos/{repo_id}/file/", params={"p": path}))
        if isinstance(data, str):
            url = data.strip().strip('"')
        elif isinstance(data, dict) and "url" in data:
            url = str(data["url"])
        else:
            msg = f"unexpected Seafile download URL response for {repo_id}:{path}"
            raise TypeError(msg)
        return self._rewrite_download_url(unquote(url))

    def download_file(self, repo_id: str, path: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                url = self.get_file_download_url(repo_id, path)
                response = httpx.get(
                    url,
                    headers=dict(self._client.headers),
                    timeout=self._client.timeout,
                )
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {429, 502, 503, 504}:
                    raise
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(min(30, 2 * attempt))
        if last_error:
            raise last_error
        msg = f"failed to download Seafile file after retries: {repo_id}:{path}"
        raise RuntimeError(msg)

    def get_commit_diff(self, repo_id: str, commit_id: str) -> dict[str, Any]:
        # Seafile deployments differ in commit detail endpoint availability. Keep the
        # method isolated so operators can override this client without touching sync logic.
        data = unwrap_response(self._client.get(f"/api/v2.1/repos/{repo_id}/commits/{commit_id}/"))
        if isinstance(data, dict):
            return data
        msg = f"unexpected commit diff response for {repo_id}:{commit_id}"
        raise TypeError(msg)

    def _rewrite_download_url(self, url: str) -> str:
        if (
            self.rewrite_download_urls
            and self.rewrite_from
            and self.rewrite_to
            and url.startswith(self.rewrite_from)
        ):
            return self.rewrite_to.rstrip("/") + url[len(self.rewrite_from.rstrip("/")) :]
        return url
