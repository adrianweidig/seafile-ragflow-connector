from __future__ import annotations

import re

_REQUEST_LINE_RE = re.compile(
    r"(?P<method>[A-Z]+) (?P<target>\S+) (?P<version>HTTP/\d(?:\.\d)?)"
)


def sanitize_http_access_message(message: str) -> str:
    """Remove query strings from HTTP request lines before they reach logs."""

    def replace(match: re.Match[str]) -> str:
        target = match.group("target").split("?", 1)[0].split("#", 1)[0]
        return f'{match.group("method")} {target} {match.group("version")}'

    return _REQUEST_LINE_RE.sub(replace, message)
