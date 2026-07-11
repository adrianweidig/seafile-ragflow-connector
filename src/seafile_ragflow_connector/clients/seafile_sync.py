from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from seafile_ragflow_connector.clients.http import VerifyConfig, make_client, unwrap_response

DownloadOrigin = tuple[str, str, int]


class SeafileDownloadTooLargeError(ValueError):
    pass


class SeafileSyncClient:
    def __init__(
        self,
        base_url: str,
        sync_token: str,
        *,
        timeout: float = 120.0,
        verify: VerifyConfig = True,
        rewrite_download_urls: bool = False,
        rewrite_from: str | None = None,
        rewrite_to: str | None = None,
        allowed_download_origins: tuple[str, ...] = (),
        max_download_bytes: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rewrite_download_urls = rewrite_download_urls
        self.rewrite_from = rewrite_from
        self.rewrite_to = rewrite_to
        self.verify = verify
        if max_download_bytes is not None and max_download_bytes <= 0:
            raise ValueError("max_download_bytes must be positive")
        self.max_download_bytes = max_download_bytes
        trusted_origins = {_http_origin(self.base_url)}
        trusted_origins.update(_http_origin(value) for value in allowed_download_origins)
        if self.rewrite_download_urls and self.rewrite_to:
            trusted_origins.add(_http_origin(self.rewrite_to))
        self._trusted_download_origins = frozenset(trusted_origins)
        self._client = make_client(
            base_url,
            headers={"Authorization": f"Token {sync_token}"},
            timeout=timeout,
            verify=verify,
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
        rewritten = self._rewrite_download_url(url)
        self._require_trusted_download_url(rewritten)
        return rewritten

    def download_file(self, repo_id: str, path: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                url = self.get_file_download_url(repo_id, path)
                return self._download_url(url)
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

    def _require_trusted_download_url(self, url: str) -> None:
        origin = _http_origin(url)
        if origin not in self._trusted_download_origins:
            msg = "Seafile download URL origin is not trusted"
            raise ValueError(msg)

    def _download_url(self, url: str) -> bytes:
        self._require_trusted_download_url(url)
        with httpx.stream(
            "GET",
            url,
            headers=dict(self._client.headers),
            timeout=self._client.timeout,
            verify=self.verify,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            self._check_content_length(response.headers.get("Content-Length"))
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if self.max_download_bytes is not None and len(body) > self.max_download_bytes:
                    raise SeafileDownloadTooLargeError("Seafile download exceeds configured limit")
            return bytes(body)

    def _check_content_length(self, raw_value: str | None) -> None:
        if self.max_download_bytes is None or not raw_value:
            return
        try:
            content_length = int(raw_value)
        except ValueError:
            return
        if content_length > self.max_download_bytes:
            raise SeafileDownloadTooLargeError("Seafile download exceeds configured limit")


def _http_origin(url: str) -> DownloadOrigin:
    try:
        parsed = urlsplit(str(url).strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid Seafile download origin") from exc
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("Seafile download URLs must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Seafile download URLs must not contain credentials")
    try:
        normalized_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid Seafile download hostname") from exc
    return scheme, normalized_hostname, port or (443 if scheme == "https" else 80)
