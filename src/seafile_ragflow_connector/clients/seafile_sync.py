from __future__ import annotations

import time
from collections.abc import Callable
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
        self._verified_account_email: str | None = None
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

    def require_account_identity(self, expected_email: str) -> str:
        expected = expected_email.strip()
        if not expected:
            raise ValueError("expected Seafile sync-user email must not be empty")
        if self._verified_account_email is None:
            data = unwrap_response(self._client.get("/api2/account/info/"))
            if not isinstance(data, dict):
                raise TypeError("unexpected Seafile account-info response")
            raw_email = data.get("email")
            if not isinstance(raw_email, str) or not raw_email.strip():
                raise RuntimeError("Seafile sync token account has no canonical email")
            actual = raw_email.strip()
            if actual.casefold() != expected.casefold():
                raise RuntimeError(
                    "Seafile sync token identity does not match "
                    "SEAFILE_SYNC_USER_EMAIL"
                )
            self._verified_account_email = actual
        elif self._verified_account_email.casefold() != expected.casefold():
            raise RuntimeError(
                "cached Seafile sync token identity does not match "
                "SEAFILE_SYNC_USER_EMAIL"
            )
        return self._verified_account_email

    def list_dir_at_commit(
        self,
        repo_id: str,
        commit_id: str,
        path: str = "/",
    ) -> list[dict[str, Any]]:
        data = unwrap_response(
            self._client.get(
                f"/api/v2.1/repos/{repo_id}/commits/{commit_id}/dir/",
                params={"path": path},
            )
        )
        if isinstance(data, list):
            if not all(isinstance(item, dict) for item in data):
                raise TypeError(
                    f"unexpected Seafile commit directory entries for "
                    f"{repo_id}:{commit_id}:{path}"
                )
            return [dict(item) for item in data]
        if isinstance(data, dict):
            entries = data.get("entries") or data.get("dirents") or data.get("items")
            if isinstance(entries, list):
                if not all(isinstance(item, dict) for item in entries):
                    raise TypeError(
                        f"unexpected Seafile commit directory entries for "
                        f"{repo_id}:{commit_id}:{path}"
                    )
                return [dict(item) for item in entries]
        msg = f"unexpected Seafile commit directory response for {repo_id}:{commit_id}:{path}"
        raise TypeError(msg)

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
        return self._download_file_with_url(
            lambda: self.get_file_download_url(repo_id, path),
            label=f"{repo_id}:{path}",
        )

    def get_file_revision_download_url(
        self,
        repo_id: str,
        path: str,
        commit_id: str,
    ) -> str:
        data = unwrap_response(
            self._client.get(
                f"/api2/repos/{repo_id}/file/revision/",
                params={"p": path, "commit_id": commit_id},
            )
        )
        if isinstance(data, str):
            url = data.strip().strip('"')
        elif isinstance(data, dict) and "url" in data:
            url = str(data["url"])
        else:
            msg = f"unexpected Seafile revision URL response for {repo_id}:{commit_id}:{path}"
            raise TypeError(msg)
        rewritten = self._rewrite_download_url(url)
        self._require_trusted_download_url(rewritten)
        return rewritten

    def download_file_revision(self, repo_id: str, path: str, commit_id: str) -> bytes:
        return self._download_file_with_url(
            lambda: self.get_file_revision_download_url(repo_id, path, commit_id),
            label=f"{repo_id}:{commit_id}:{path}",
        )

    def _download_file_with_url(
        self,
        get_url: Callable[[], str],
        *,
        label: str,
    ) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                url = str(get_url())
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
        raise RuntimeError(f"failed to download Seafile file after retries: {label}")

    def get_commit_diff(self, repo_id: str, commit_id: str) -> dict[str, Any]:
        # Compatibility alias retained for callers that used the old, misleading name.
        # This endpoint returns commit information; portable delta sync uses snapshots.
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
