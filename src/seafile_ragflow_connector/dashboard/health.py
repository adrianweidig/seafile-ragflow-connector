from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from redis import Redis

from seafile_ragflow_connector.clients.tls import classify_httpx_error, safe_url_for_logs
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import (
    DashboardEventStore,
    isoformat,
    safe_text,
    utcnow,
)

HEALTH_TIMEOUT_SECONDS = 0.5
RAGFLOW_HEALTH_TIMEOUT_SECONDS = 3.0


def collect_dashboard_health(
    *,
    store: DashboardEventStore,
    settings: Settings,
    started_at: datetime,
) -> dict[str, Any]:
    status = store.connector_status(started_at=started_at)
    checks = [
        _check_dashboard(),
        _timed_check("database", "Datenbank", _check_database(store)),
        _timed_check("redis", "Redis", _check_redis(settings.redis_url)),
        _timed_check("seafile", "Seafile Admin API", _check_seafile(settings)),
        _timed_check("ragflow", "RAGFlow API", _check_ragflow(settings)),
        _check_openwebui(settings),
        _check_sync_jobs(status),
    ]
    _ensure_transport_fields(settings, checks)
    summary = {
        "ok": sum(1 for item in checks if item["status"] == "ok"),
        "warning": sum(1 for item in checks if item["status"] == "warning"),
        "error": sum(1 for item in checks if item["status"] == "error"),
    }
    overall = "ok"
    if summary["error"]:
        overall = "degraded"
    elif summary["warning"]:
        overall = "warning"
    return {
        "status": overall,
        "dashboard_enabled": True,
        "generated_at": isoformat(utcnow()),
        "checks": checks,
        "summary": summary,
    }


def collect_tls_health(settings: Settings) -> dict[str, Any]:
    return {
        "seafile": _tls_probe(
            name="seafile",
            route="Connector Proxy -> Seafile",
            url=(settings.seafile_internal_url or settings.seafile_base_url).rstrip("/"),
            path="/api/v2.1/admin/libraries/",
            headers={"Authorization": f"Token {settings.seafile_admin_token}"},
            params={"page": 1, "per_page": 1},
            verify=settings.seafile_httpx_verify,
            ca_hint="SEAFILE_CA_BUNDLE prüfen",
        ),
        "ragflow": _tls_probe(
            name="ragflow",
            route="Connector Proxy -> RAGFlow",
            url=(settings.ragflow_internal_url or settings.ragflow_base_url).rstrip("/"),
            path="/api/v1/datasets",
            headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
            params={"page": 1, "page_size": 1},
            verify=settings.ragflow_httpx_verify,
            ca_hint="RAGFLOW_CA_BUNDLE prüfen",
        ),
    }


def _check_dashboard() -> dict[str, Any]:
    return {
        "name": "dashboard",
        "label": "Dashboard HTTP",
        "status": "ok",
        "latency_ms": 0,
        "message": "Dashboard antwortet.",
    }


def _timed_check(
    name: str,
    label: str,
    check: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = check()
    except Exception as exc:  # pragma: no cover - exercised by live dependency failures
        result = {
            "status": "error",
            "message": safe_text(exc, max_length=600) or "Healthcheck fehlgeschlagen.",
        }
    result.setdefault("name", name)
    result.setdefault("label", label)
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def _check_database(store: DashboardEventStore) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        store.ping_database()
        return {"status": "ok", "message": "SQL-Ping erfolgreich."}

    return run


def _check_redis(redis_url: str) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        client = Redis.from_url(
            redis_url,
            socket_connect_timeout=HEALTH_TIMEOUT_SECONDS,
            socket_timeout=HEALTH_TIMEOUT_SECONDS,
        )
        try:
            client.ping()
        finally:
            client.close()
        return {"status": "ok", "message": "Redis-Ping erfolgreich."}

    return run


def _check_seafile(settings: Settings) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        base_url = (settings.seafile_internal_url or settings.seafile_base_url).rstrip("/")
        with httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Token {settings.seafile_admin_token}"},
            timeout=HEALTH_TIMEOUT_SECONDS,
            verify=settings.seafile_httpx_verify,
        ) as client:
            response = client.get("/api/v2.1/admin/libraries/", params={"page": 1, "per_page": 1})
            response.raise_for_status()
            payload = _safe_json(response)
        visible = _count_seafile_libraries(payload)
        return {
            "status": "ok",
            "message": f"Admin-API erreichbar, {visible} Library-Eintrag geprüft.",
            "endpoint": base_url,
            **_transport_fields(settings, "seafile", base_url),
        }

    return run


def _check_ragflow(settings: Settings) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        base_url = (settings.ragflow_internal_url or settings.ragflow_base_url).rstrip("/")
        with httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
            timeout=RAGFLOW_HEALTH_TIMEOUT_SECONDS,
            verify=settings.ragflow_httpx_verify,
        ) as client:
            response = client.get(
                "/api/v1/datasets",
                params={"name": settings.ragflow_template_dataset_name},
            )
            response.raise_for_status()
            payload = _safe_json(response)
        code = payload.get("code") if isinstance(payload, dict) else None
        if code not in (None, 0, "0", 200):
            return {
                "status": "warning",
                "message": f"API erreichbar, meldet Code {code}.",
                "endpoint": base_url,
                **_transport_fields(settings, "ragflow", base_url),
            }
        datasets = _extract_ragflow_datasets(payload)
        if not datasets and settings.ragflow_template_required:
            return {
                "status": "warning",
                "message": f"Template '{settings.ragflow_template_dataset_name}' nicht gefunden.",
                "endpoint": base_url,
                **_transport_fields(settings, "ragflow", base_url),
            }
        return {
            "status": "ok",
            "message": f"API erreichbar, {len(datasets)} Template-Treffer.",
            "endpoint": base_url,
            **_transport_fields(settings, "ragflow", base_url),
        }

    return run


def _check_openwebui(settings: Settings) -> dict[str, Any]:
    if settings.openwebui_effective_sync_mode == "disabled":
        return {
            "name": "openwebui",
            "label": "OpenWebUI",
            "status": "ok",
            "latency_ms": 0,
            "message": "Integration deaktiviert.",
        }
    if not settings.openwebui_admin_api_key:
        return {
            "name": "openwebui",
            "label": "OpenWebUI",
            "status": "warning",
            "latency_ms": 0,
            "message": "Admin-API-Key fehlt.",
        }
    return _timed_check("openwebui", "OpenWebUI", _check_openwebui_api(settings))


def _check_openwebui_api(settings: Settings) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        with httpx.Client(
            base_url=settings.openwebui_base_url,
            headers={"Authorization": f"Bearer {settings.openwebui_admin_api_key}"},
            timeout=HEALTH_TIMEOUT_SECONDS,
            verify=settings.openwebui_httpx_verify,
            follow_redirects=False,
        ) as client:
            response = client.get("/api/v1/functions/list")
            response.raise_for_status()
        return {
            "status": "ok",
            "message": "Functions-API erreichbar.",
            "endpoint": settings.openwebui_base_url,
            **_transport_fields(settings, "openwebui", settings.openwebui_base_url),
        }

    return run


def _check_sync_jobs(status: dict[str, Any]) -> dict[str, Any]:
    failed = int(status.get("failed_jobs") or 0)
    queued = int(status.get("queued_or_retrying_jobs") or 0)
    running = int(status.get("running_jobs") or 0)
    if failed:
        state = "error"
        message = f"{failed} tote Jobs vorhanden."
    elif queued:
        state = "warning"
        message = f"{queued} Jobs warten oder retryen."
    else:
        state = "ok"
        message = f"{running} laufende Jobs, keine toten Jobs."
    return {
        "name": "sync_jobs",
        "label": "Sync-Jobs",
        "status": state,
        "latency_ms": 0,
        "message": message,
    }


def _tls_probe(
    *,
    name: str,
    route: str,
    url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, str | int | float | bool | None],
    verify: bool | str,
    ca_hint: str,
) -> dict[str, Any]:
    safe_url = safe_url_for_logs(url)
    try:
        with httpx.Client(
            base_url=url,
            headers=headers,
            timeout=3.0,
            verify=verify,
            follow_redirects=False,
        ) as client:
            response = client.get(path, params=params)
        return {
            "url": safe_url,
            "route": route,
            "tls": "ok",
            "scheme": urlparse(url).scheme,
            "encrypted": urlparse(url).scheme == "https",
            "status": response.status_code,
        }
    except Exception as exc:
        return {
            "url": safe_url,
            "route": route,
            "tls": "failed",
            "scheme": urlparse(url).scheme,
            "encrypted": urlparse(url).scheme == "https",
            "error_type": classify_httpx_error(exc),
            "hint": ca_hint,
            "name": name,
        }


def _transport_fields(settings: Settings, service: str, endpoint: str) -> dict[str, Any]:
    status = settings.connector_transport_status.get(service)
    if not isinstance(status, dict):
        scheme = urlparse(endpoint).scheme or "unknown"
        return {
            "scheme": scheme,
            "encrypted": scheme == "https",
            "transport": {
                "service": service,
                "scheme": scheme,
                "encrypted": scheme == "https",
                "selected_url": safe_url_for_logs(endpoint),
                "configured_url": safe_url_for_logs(endpoint),
            },
        }
    scheme = str(status.get("scheme") or urlparse(endpoint).scheme or "unknown")
    return {
        "scheme": scheme,
        "encrypted": bool(status.get("encrypted")),
        "transport": status,
    }


def _ensure_transport_fields(settings: Settings, checks: list[dict[str, Any]]) -> None:
    endpoints = {
        "seafile": settings.seafile_internal_url or settings.seafile_base_url,
        "ragflow": settings.ragflow_internal_url or settings.ragflow_base_url,
        "openwebui": settings.openwebui_base_url,
    }
    for check in checks:
        name = str(check.get("name") or "")
        endpoint = endpoints.get(name)
        if endpoint and "transport" not in check:
            check.update(_transport_fields(settings, name, endpoint))


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


def _count_seafile_libraries(payload: Any) -> int:
    if isinstance(payload, dict):
        for key in ("repos", "repo_list", "libraries"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    if isinstance(payload, list):
        return len(payload)
    return 0


def _extract_ragflow_datasets(payload: Any) -> list[Any]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict) and isinstance(data.get("datasets"), list):
        return list(data["datasets"])
    if isinstance(data, list):
        return data
    return []
