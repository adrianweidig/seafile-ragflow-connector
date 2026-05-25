from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import structlog

from seafile_ragflow_connector.clients.tls import classify_httpx_error, safe_url_for_logs
from seafile_ragflow_connector.config.settings import Settings

ProbeFn = Callable[
    [str, str, dict[str, str], dict[str, str | int | float | bool | None], bool | str, float],
    "TransportProbeResult",
]


@dataclass(frozen=True)
class TransportProbeResult:
    ok: bool
    status_code: int | None = None
    error_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class TransportSelection:
    service: str
    selected_url: str
    configured_url: str
    scheme: str
    https_attempted: bool
    https_status_code: int | None
    https_error_type: str | None
    fallback_used: bool
    fallback_reason: str | None
    tls_verify: bool | str

    def as_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "selected_url": safe_url_for_logs(self.selected_url),
            "configured_url": safe_url_for_logs(self.configured_url),
            "scheme": self.scheme,
            "encrypted": self.scheme == "https",
            "https_attempted": self.https_attempted,
            "https_status_code": self.https_status_code,
            "https_error_type": self.https_error_type,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "tls_verify": self.tls_verify,
        }


def resolve_service_transports(
    settings: Settings,
    *,
    probe: ProbeFn | None = None,
    timeout_seconds: float = 3.0,
) -> None:
    """Resolve service base URLs with HTTPS preference and HTTP fallback."""

    selected_probe = probe or _probe_transport
    selections: dict[str, TransportSelection] = {}
    seafile = _select_transport(
        service="seafile",
        configured_url=settings.seafile_base_url,
        path="/api/v2.1/admin/libraries/",
        headers={"Authorization": f"Token {settings.seafile_admin_token}"},
        params={"page": 1, "per_page": 1},
        verify=settings.seafile_httpx_verify,
        probe=selected_probe,
        timeout_seconds=timeout_seconds,
    )
    settings.seafile_base_url = seafile.selected_url
    selections["seafile"] = seafile

    ragflow = _select_transport(
        service="ragflow",
        configured_url=settings.ragflow_base_url,
        path="/api/v1/datasets",
        headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
        params={"page": 1, "page_size": 1},
        verify=settings.ragflow_httpx_verify,
        probe=selected_probe,
        timeout_seconds=timeout_seconds,
    )
    settings.ragflow_base_url = ragflow.selected_url
    selections["ragflow"] = ragflow

    if settings.openwebui_effective_sync_mode != "disabled":
        openwebui = _select_transport(
            service="openwebui",
            configured_url=settings.openwebui_base_url,
            path="/api/v1/functions/list",
            headers=(
                {"Authorization": f"Bearer {settings.openwebui_admin_api_key}"}
                if settings.openwebui_admin_api_key
                else {}
            ),
            params={},
            verify=settings.openwebui_httpx_verify,
            probe=selected_probe,
            timeout_seconds=timeout_seconds,
        )
        settings.openwebui_base_url = openwebui.selected_url
        selections["openwebui"] = openwebui
    else:
        selections["openwebui"] = _disabled_selection(
            "openwebui",
            settings.openwebui_base_url,
            settings.openwebui_httpx_verify,
        )

    settings.connector_transport_status = {
        service: selection.as_dict() for service, selection in selections.items()
    }
    for selection in selections.values():
        openwebui_disabled = (
            selection.service == "openwebui"
            and settings.openwebui_effective_sync_mode == "disabled"
        )
        if openwebui_disabled:
            continue
        structlog.get_logger(__name__).info(
            "transport.selected",
            service=selection.service,
            scheme=selection.scheme,
            encrypted=selection.scheme == "https",
            target=safe_url_for_logs(selection.selected_url),
            fallback_used=selection.fallback_used,
            fallback_reason=selection.fallback_reason,
        )


def _select_transport(
    *,
    service: str,
    configured_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, str | int | float | bool | None],
    verify: bool | str,
    probe: ProbeFn,
    timeout_seconds: float,
) -> TransportSelection:
    candidates = _transport_candidates(configured_url)
    https_url = next((url for url in candidates if urlparse(url).scheme == "https"), None)
    https_result: TransportProbeResult | None = None
    if https_url:
        https_result = probe(https_url, path, headers, params, verify, timeout_seconds)
        if https_result.ok:
            return _selection(
                service=service,
                configured_url=configured_url,
                selected_url=https_url,
                verify=verify,
                https_result=https_result,
                fallback_used=False,
                fallback_reason=None,
            )
    http_url = next((url for url in candidates if urlparse(url).scheme == "http"), None)
    if http_url:
        http_result = probe(http_url, path, headers, params, verify, timeout_seconds)
        if http_result.ok:
            return _selection(
                service=service,
                configured_url=configured_url,
                selected_url=http_url,
                verify=verify,
                https_result=https_result,
                fallback_used=bool(https_url),
                fallback_reason=(
                    f"https_failed:{https_result.error_type or 'unknown'}"
                    if https_result
                    else "https_not_configurable"
                ),
            )
    selected_url = configured_url.rstrip("/")
    selected_scheme = urlparse(selected_url).scheme
    fallback_used = bool(https_result and selected_scheme == "http")
    return _selection(
        service=service,
        configured_url=configured_url,
        selected_url=selected_url,
        verify=verify,
        https_result=https_result,
        fallback_used=fallback_used,
        fallback_reason=(
            f"https_failed:{https_result.error_type or 'unknown'};http_unreachable"
            if https_result
            else "no_reachable_candidate"
        ),
    )


def _selection(
    *,
    service: str,
    configured_url: str,
    selected_url: str,
    verify: bool | str,
    https_result: TransportProbeResult | None,
    fallback_used: bool,
    fallback_reason: str | None,
) -> TransportSelection:
    return TransportSelection(
        service=service,
        selected_url=selected_url.rstrip("/"),
        configured_url=configured_url.rstrip("/"),
        scheme=urlparse(selected_url).scheme or "unknown",
        https_attempted=https_result is not None,
        https_status_code=https_result.status_code if https_result else None,
        https_error_type=https_result.error_type if https_result else None,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        tls_verify=verify,
    )


def _disabled_selection(
    service: str,
    configured_url: str,
    verify: bool | str,
) -> TransportSelection:
    return TransportSelection(
        service=service,
        selected_url=configured_url.rstrip("/"),
        configured_url=configured_url.rstrip("/"),
        scheme=urlparse(configured_url).scheme or "unknown",
        https_attempted=False,
        https_status_code=None,
        https_error_type=None,
        fallback_used=False,
        fallback_reason="disabled",
        tls_verify=verify,
    )


def _transport_candidates(configured_url: str) -> list[str]:
    parsed = urlparse(configured_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [configured_url.rstrip("/")]
    https_url = urlunparse(parsed._replace(scheme="https"))
    http_url = urlunparse(parsed._replace(scheme="http"))
    return [https_url, http_url]


def _probe_transport(
    base_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, str | int | float | bool | None],
    verify: bool | str,
    timeout_seconds: float,
) -> TransportProbeResult:
    try:
        with httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout_seconds,
            verify=verify,
            follow_redirects=False,
        ) as client:
            response = client.get(path, params=params)
        return TransportProbeResult(ok=True, status_code=response.status_code)
    except Exception as exc:
        return TransportProbeResult(
            ok=False,
            error_type=classify_httpx_error(exc),
            error=str(exc),
        )
