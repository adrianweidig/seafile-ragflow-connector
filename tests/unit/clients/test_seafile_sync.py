from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from seafile_ragflow_connector.clients import seafile_sync
from seafile_ragflow_connector.clients.seafile_sync import (
    SeafileDownloadTooLargeError,
    SeafileSyncClient,
)
from seafile_ragflow_connector.sync.delta_sync import capture_commit_snapshot


class _StreamResponse:
    status_code = 200
    headers: dict[str, str]

    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self) -> Iterator[bytes]:
        yield from self._chunks


class _StreamContext:
    def __init__(self, response: _StreamResponse) -> None:
        self.response = response

    def __enter__(self) -> _StreamResponse:
        return self.response

    def __exit__(self, *args: object) -> None:
        return None


def test_download_origin_rejects_foreign_host_scheme_and_port() -> None:
    client = SeafileSyncClient("https://seafile.example", "sync-token")
    try:
        client._require_trusted_download_url("https://seafile.example/seafhttp/file")
        with pytest.raises(ValueError, match="not trusted"):
            client._require_trusted_download_url("https://evil.example/file")
        with pytest.raises(ValueError, match="not trusted"):
            client._require_trusted_download_url("http://seafile.example/file")
        with pytest.raises(ValueError, match="not trusted"):
            client._require_trusted_download_url("https://seafile.example:444/file")
        with pytest.raises(ValueError, match="http or https"):
            client._require_trusted_download_url("file:///tmp/token")
    finally:
        client.close()


def test_rewrite_target_and_explicit_origin_are_trusted() -> None:
    client = SeafileSyncClient(
        "https://seafile.example",
        "sync-token",
        rewrite_download_urls=True,
        rewrite_from="http://127.0.0.1/seafhttp",
        rewrite_to="http://seafile-internal/seafhttp",
        allowed_download_origins=("https://downloads.example:8443",),
    )
    try:
        rewritten = client._rewrite_download_url("http://127.0.0.1/seafhttp/files/a")
        assert rewritten == "http://seafile-internal/seafhttp/files/a"
        client._require_trusted_download_url(rewritten)
        client._require_trusted_download_url("https://downloads.example:8443/files/a")
    finally:
        client.close()


def test_streaming_download_sends_token_only_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_stream(method: str, url: str, **kwargs: Any) -> _StreamContext:
        seen.update({"method": method, "url": url, **kwargs})
        return _StreamContext(_StreamResponse([b"abc", b"def"], content_length="6"))

    monkeypatch.setattr(seafile_sync.httpx, "stream", fake_stream)
    client = SeafileSyncClient("https://seafile.example", "sync-token", max_download_bytes=10)
    try:
        assert client._download_url("https://seafile.example/file") == b"abcdef"
        assert seen["headers"]["authorization"] == "Token sync-token"
        assert seen["follow_redirects"] is False
        with pytest.raises(ValueError, match="not trusted"):
            client._download_url("https://evil.example/file")
    finally:
        client.close()


@pytest.mark.parametrize(
    ("chunks", "content_length"),
    [([b"abcdef"], "6"), ([b"abc", b"def"], None)],
)
def test_streaming_download_enforces_limit_before_or_during_read(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[bytes],
    content_length: str | None,
) -> None:
    monkeypatch.setattr(
        seafile_sync.httpx,
        "stream",
        lambda *args, **kwargs: _StreamContext(
            _StreamResponse(chunks, content_length=content_length)
        ),
    )
    client = SeafileSyncClient("https://seafile.example", "sync-token", max_download_bytes=5)
    try:
        with pytest.raises(SeafileDownloadTooLargeError, match="configured limit"):
            client._download_url("https://seafile.example/file")
    finally:
        client.close()


def test_commit_snapshot_and_revision_download_use_pinned_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/dir/"):
            return httpx.Response(
                200,
                request=request,
                json=[{"name": "a.txt", "type": "file", "id": "obj-a"}],
            )
        return httpx.Response(
            200,
            request=request,
            json="https://seafile.example/seafhttp/revision-token",
        )

    client = SeafileSyncClient("https://seafile.example", "sync-token")
    client._client.close()
    client._client = httpx.Client(  # type: ignore[assignment]
        base_url="https://seafile.example",
        headers={"Authorization": "Token sync-token"},
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(client, "_download_url", lambda url: url.encode())
    try:
        entries = client.list_dir_at_commit("repo", "commit-1", "/docs")
        body = client.download_file_revision("repo", "/docs/a.txt", "commit-1")
    finally:
        client.close()

    assert entries[0]["id"] == "obj-a"
    assert body == b"https://seafile.example/seafhttp/revision-token"
    assert requests[0].url.path == "/api/v2.1/repos/repo/commits/commit-1/dir/"
    assert requests[0].url.params["path"] == "/docs"
    assert requests[1].url.path == "/api2/repos/repo/file/revision/"
    assert requests[1].url.params["commit_id"] == "commit-1"


def test_commit_snapshot_recurses_with_hierarchical_path_parameter() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.params["path"]
        requested_paths.append(path)
        if path == "/":
            entries = [
                {"name": "docs", "type": "dir", "id": "dir-docs"},
                {"name": "root.txt", "type": "file", "id": "obj-root"},
            ]
        elif path == "/docs":
            entries = [
                {"name": "nested.txt", "type": "file", "id": "obj-nested"}
            ]
        else:
            pytest.fail(f"unexpected snapshot path: {path}")
        return httpx.Response(200, request=request, json=entries)

    client = SeafileSyncClient("https://seafile.example", "sync-token")
    client._client.close()
    client._client = httpx.Client(  # type: ignore[assignment]
        base_url="https://seafile.example",
        headers={"Authorization": "Token sync-token"},
        transport=httpx.MockTransport(handler),
    )
    try:
        snapshot = capture_commit_snapshot(client, "repo", "commit-1")
    finally:
        client.close()

    assert requested_paths == ["/", "/docs"]
    assert [entry.normalized_path for entry in snapshot] == [
        "/docs",
        "/docs/nested.txt",
        "/root.txt",
    ]


def test_commit_snapshot_rejects_mixed_entry_lists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=[{"name": "valid.txt", "type": "file"}, "invalid"],
        )

    client = SeafileSyncClient("https://seafile.example", "sync-token")
    client._client.close()
    client._client = httpx.Client(  # type: ignore[assignment]
        base_url="https://seafile.example",
        headers={"Authorization": "Token sync-token"},
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(TypeError, match="commit directory entries"):
            client.list_dir_at_commit("repo", "commit-1", "/")
    finally:
        client.close()
