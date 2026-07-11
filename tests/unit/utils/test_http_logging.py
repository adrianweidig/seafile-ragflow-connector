from __future__ import annotations

from seafile_ragflow_connector.utils.http_logging import sanitize_http_access_message


def test_access_log_removes_entire_query_string() -> None:
    message = '127.0.0.1 - - [now] "GET /preview?token=secret&view=1 HTTP/1.1" 200 42'

    sanitized = sanitize_http_access_message(message)

    assert sanitized == '127.0.0.1 - - [now] "GET /preview HTTP/1.1" 200 42'
    assert "secret" not in sanitized


def test_access_log_keeps_request_without_query_unchanged() -> None:
    message = '127.0.0.1 - - [now] "POST /api/search HTTP/1.1" 200 42'

    assert sanitize_http_access_message(message) == message
