from __future__ import annotations

# ruff: noqa: E501
import base64
import binascii
import hmac
import ipaddress
import json
import mimetypes
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import structlog
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.orm import Session

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.openwebui import OpenWebUIClient
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.clients.seafile_sync import SeafileSyncClient
from seafile_ragflow_connector.clients.tls import classify_httpx_error, safe_url_for_logs
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.export import audit_export_filename, build_audit_workbook
from seafile_ragflow_connector.dashboard.health import (
    collect_dashboard_health,
    collect_dashboard_readiness,
    collect_tls_health,
)
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, new_sync_id
from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML
from seafile_ragflow_connector.domain.ragflow_search_settings import (
    ResolvedSearchTemplate,
    config_from_settings,
    resolve_search_template,
)
from seafile_ragflow_connector.i18n import localizer_for
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.openwebui.sources import (
    OPENWEBUI_PREVIEW_AUDIENCE,
    SOURCE_PREVIEW_PURPOSE,
    annotate_answer_citations,
    audit_rank_sources,
    curate_sources_for_answer,
    extract_answer_result,
    normalize_sources,
    render_sources_markdown,
    verify_preview_token,
)
from seafile_ragflow_connector.persistence.admin_control import (
    AdminControlStore,
    ControlAuditWriter,
)
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping
from seafile_ragflow_connector.persistence.models.search import SearchProfile
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
from seafile_ragflow_connector.persistence.sync_state import SyncStateStore
from seafile_ragflow_connector.security.access_control import (
    AccessControlService,
    AuthzResource,
    UserIdentity,
)
from seafile_ragflow_connector.sync.discovery import normalize_library, should_skip_library
from seafile_ragflow_connector.utils.http_logging import sanitize_http_access_message
from seafile_ragflow_connector.utils.readiness import ReadinessCache
from seafile_ragflow_connector.utils.redaction import redact_mapping

DASHBOARD_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "form-action 'none'"
)


class DashboardBindError(RuntimeError):
    pass


class AuthzDeniedError(PermissionError):
    pass


@dataclass
class DashboardServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@dataclass(frozen=True)
class DashboardContext:
    store: DashboardEventStore
    settings: Settings
    started_at: datetime
    orchestrator: Any | None = None
    openwebui_sync_service: Any | None = None
    job_store: Any | None = None
    signal_queue: Any | None = None
    control_store: Any | None = None


def start_dashboard_server(context: DashboardContext, *, background: bool = True) -> DashboardServerHandle:
    handler_class = _build_handler(context)
    try:
        server = ThreadingHTTPServer(
            (context.settings.connector_dashboard_host, context.settings.connector_dashboard_port),
            handler_class,
        )
    except OSError as exc:
        raise DashboardBindError(
            "dashboard port could not be bound: "
            f"{context.settings.connector_dashboard_host}:{context.settings.connector_dashboard_port}: {exc}"
        ) from exc
    thread = threading.Thread(target=server.serve_forever, name="connector-dashboard", daemon=True)
    if background:
        thread.start()
    return DashboardServerHandle(server=server, thread=thread)


def serve_dashboard_forever(context: DashboardContext) -> None:
    handle = start_dashboard_server(context, background=False)
    structlog.get_logger(__name__).info(
        "dashboard.started",
        host=context.settings.connector_dashboard_host,
        port=context.settings.connector_dashboard_port,
    )
    try:
        handle.server.serve_forever()
    finally:
        handle.server.server_close()


def _build_handler(context: DashboardContext) -> type[BaseHTTPRequestHandler]:
    readiness_cache: ReadinessCache[dict[str, Any]] = ReadinessCache(ttl_seconds=5.0)

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "SeafileRAGFlowConnectorDashboard/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/livez":
                    self._send_json({"status": "alive", "service": "connector-controller"})
                    return
                if parsed.path == "/readyz":
                    readiness = readiness_cache.get(
                        lambda: collect_dashboard_readiness(
                            store=context.store,
                            settings=context.settings,
                        )
                    )
                    status = (
                        HTTPStatus.OK
                        if readiness["status"] == "ready"
                        else HTTPStatus.SERVICE_UNAVAILABLE
                    )
                    self._send_json(readiness, status=status)
                    return
                if parsed.path == "/metrics":
                    self._send_binary(
                        generate_latest(),
                        headers={"Content-Type": CONTENT_TYPE_LATEST},
                    )
                    return
                if parsed.path == "/api/authz/profiles":
                    payload, status = _handle_authz_profiles(
                        context,
                        self.headers.get("Authorization"),
                        self.client_address[0],
                        self.headers.get("X-Authz-Username"),
                        self.headers.get("X-Authz-Email"),
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path == "/api/search/document":
                    params = parse_qs(parsed.query)
                    body, status, headers = _handle_search_document(
                        context,
                        params,
                        self.headers.get("Authorization"),
                        self.client_address[0],
                        self.headers.get("X-Authz-Username"),
                        self.headers.get("X-Authz-Email"),
                    )
                    self._send_binary(body, status=status, headers=headers)
                    return
                if parsed.path in {"/api/openwebui/sources/preview", "/api/sources/preview"}:
                    params = parse_qs(parsed.query)
                    self._send_html(_preview_html(context.settings, _one(params, "token")))
                    return
                if not context.settings.connector_dashboard_enabled:
                    self._send_json({"error": "dashboard disabled"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not _dashboard_auth_ok(context.settings, self.headers.get("Authorization")):
                    self._send_auth_required()
                    return
                if parsed.path in {"/", "/dashboard"}:
                    self._send_html(DASHBOARD_HTML)
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        collect_dashboard_health(
                            store=context.store,
                            settings=context.settings,
                            started_at=context.started_at,
                        )
                    )
                    return
                if parsed.path in {"/health/tls", "/api/health/tls"}:
                    self._send_json(collect_tls_health(context.settings))
                    return
                if parsed.path == "/api/status":
                    self._send_json(context.store.connector_status(started_at=context.started_at))
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(context.store.metrics())
                    return
                if parsed.path == "/api/systems":
                    systems = context.store.systems()
                    systems["transport"] = context.settings.connector_transport_status
                    self._send_json(systems)
                    return
                if parsed.path == "/api/workflow/control":
                    self._send_json(_handle_workflow_control(context))
                    return
                if parsed.path == "/api/workflow/libraries":
                    self._send_json(_handle_workflow_libraries(context))
                    return
                if parsed.path.startswith("/api/workflow/runs/"):
                    workflow_run_id = parsed.path.rsplit("/", 1)[-1]
                    payload, status = _handle_workflow_run_status(context, workflow_run_id)
                    self._send_json(payload, status=status)
                    return
                if parsed.path == "/api/sync-runs":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_sync_runs(
                            status=_one(params, "status"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path.startswith("/api/sync-runs/"):
                    sync_id = parsed.path.rsplit("/", 1)[-1]
                    item = context.store.get_sync_run(sync_id)
                    if item is None:
                        self._send_json({"error": "sync run not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        self._send_json(item)
                    return
                if parsed.path == "/api/cleanup-outbox":
                    if context.orchestrator is None:
                        self._send_json(
                            {"error": "orchestrator unavailable"},
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        )
                        return
                    params = parse_qs(parsed.query)
                    raw_status = _one(params, "status")
                    statuses = (
                        tuple(
                            value.strip()
                            for value in raw_status.split(",")
                            if value.strip()
                        )
                        if raw_status
                        else None
                    )
                    rows = context.orchestrator.list_cleanup_outbox(
                        repo_id=_one(params, "repo_id"),
                        statuses=statuses,
                        limit=_int(params, "limit") or 100,
                    )
                    self._send_json(
                        {
                            "items": [_cleanup_outbox_payload(row) for row in rows],
                            "count": len(rows),
                        }
                    )
                    return
                if parsed.path == "/api/changes":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_changes(
                            sync_id=_one(params, "sync_id"),
                            status=_one(params, "status"),
                            change_type=_one(params, "change_type"),
                            query=_one(params, "q"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path == "/api/logs":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_logs(
                            level=_one(params, "level"),
                            sync_id=_one(params, "sync_id"),
                            query=_one(params, "q"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path == "/api/diagnostics":
                    self._send_json(context.store.diagnostics(_safe_config(context.settings)))
                    return
                if parsed.path == "/api/openwebui/status":
                    self._send_json(context.store.openwebui_status())
                    return
                if parsed.path == "/api/openwebui/mappings":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_openwebui_mappings(
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path == "/api/openwebui/capabilities":
                    self._send_json(context.store.openwebui_capabilities())
                    return
                if parsed.path == "/api/openwebui/dry-run":
                    self._send_json(context.store.openwebui_dry_run())
                    return
                if parsed.path in {"/api/audit.xlsx", "/api/audit-export.xlsx"}:
                    snapshot = context.store.audit_snapshot(
                        started_at=context.started_at,
                        safe_config=_safe_config(context.settings),
                    )
                    self._send_xlsx(build_audit_workbook(snapshot), audit_export_filename())
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
                structlog.get_logger(__name__).debug(
                    "dashboard.client_disconnected", path=parsed.path, error=str(exc)
                )
                return
            except Exception as exc:
                structlog.get_logger(__name__).warning("dashboard.request_failed", path=parsed.path, error=str(exc))
                self._send_json(
                    {"error": "dashboard request failed", "message": "Die Daten konnten nicht geladen werden."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            admin_actor: str | None = None
            admin_body: dict[str, Any] | None = None
            try:
                if parsed.path == "/api/authz/check":
                    payload, status = _handle_authz_check(
                        context,
                        self._json_body(),
                        self.headers.get("Authorization"),
                        self.client_address[0],
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path == "/api/authz/filter-profiles":
                    payload, status = _handle_authz_filter_profiles(
                        context,
                        self._json_body(),
                        self.headers.get("Authorization"),
                        self.client_address[0],
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path == "/api/openwebui/proxy/query":
                    self._send_json(_handle_openwebui_query(context, self._json_body(), self.headers.get("Authorization")))
                    return
                if parsed.path == "/api/openwebui/proxy/chat":
                    self._send_json(_handle_openwebui_chat(context, self._json_body(), self.headers.get("Authorization")))
                    return
                if _is_dashboard_admin_mutation_path(parsed.path):
                    admin_actor, guard_payload, guard_status = _dashboard_admin_guard(
                        context,
                        authorization=self.headers.get("Authorization"),
                        content_type=self.headers.get("Content-Type"),
                        admin_action=self.headers.get("X-Connector-Admin-Action"),
                        fetch_site=self.headers.get("Sec-Fetch-Site"),
                    )
                    if guard_payload is not None:
                        if (
                            admin_actor is not None
                            and _admin_audit_scope(parsed.path) is not None
                        ):
                            _record_admin_audit(
                                context,
                                actor=admin_actor,
                                action=_admin_audit_action(parsed.path),
                                target=_admin_audit_target(parsed.path),
                                before=None,
                                after=None,
                                result="rejected",
                                status=guard_status,
                            )
                        if guard_status == HTTPStatus.UNAUTHORIZED:
                            self._send_auth_required()
                        else:
                            self._send_json(guard_payload, status=guard_status)
                        return
                    assert admin_actor is not None
                    try:
                        admin_body = self._json_body()
                    except ValueError as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor,
                            action=_admin_audit_action(parsed.path),
                            target=_admin_audit_target(parsed.path),
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.BAD_REQUEST,
                            error_type=type(exc).__name__,
                        )
                        raise
                else:
                    admin_actor = None
                    admin_body = None
                if parsed.path.startswith("/api/workflow/control/"):
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) != 4 or parts[:3] != ["api", "workflow", "control"]:
                        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    payload, status = _handle_workflow_control_action(
                        context,
                        unquote(parts[3]),
                        admin_body or {},
                        actor=admin_actor,
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path.startswith("/api/workflow/libraries/"):
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) != 5 or parts[:3] != ["api", "workflow", "libraries"]:
                        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    payload, status = _handle_workflow_library_action(
                        context,
                        unquote(parts[3]),
                        unquote(parts[4]),
                        actor=admin_actor,
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path in {"/api/workflow/run", "/api/workflow/runs"}:
                    payload, status = _handle_workflow_run(
                        context,
                        admin_body or {},
                        actor=admin_actor,
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path.startswith("/api/workflow/runs/"):
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) != 5 or parts[:3] != ["api", "workflow", "runs"]:
                        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    workflow_run_id, action = unquote(parts[3]), unquote(parts[4])
                    payload, status = _handle_workflow_run_action(
                        context,
                        workflow_run_id,
                        action,
                        admin_body or {},
                        actor=admin_actor,
                    )
                    self._send_json(payload, status=status)
                    return
                if parsed.path == "/api/jobs/dead/cleanup":
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="cleanup_dead_jobs",
                        target="jobs:dead",
                        before=None,
                        after=None,
                        result="attempted",
                        status=HTTPStatus.OK,
                    )
                    try:
                        cleanup_payload = _handle_dead_jobs_cleanup(context)
                    except Exception as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="cleanup_dead_jobs",
                            target="jobs:dead",
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                            error_type=type(exc).__name__,
                        )
                        raise
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="cleanup_dead_jobs",
                        target="jobs:dead",
                        before=None,
                        after=dict(cleanup_payload),
                        result="success",
                        status=HTTPStatus.OK,
                    )
                    self._send_json(cleanup_payload)
                    return
                if parsed.path.startswith("/api/cleanup-outbox/") and parsed.path.endswith(
                    "/retry"
                ):
                    if (
                        context.orchestrator is None
                        or context.job_store is None
                        or context.signal_queue is None
                    ):
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="retry_cleanup_outbox",
                            target=_admin_audit_target(parsed.path),
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        )
                        self._send_json(
                            {"error": "orchestrator unavailable"},
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        )
                        return
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) != 4 or parts[:2] != ["api", "cleanup-outbox"]:
                        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    try:
                        outbox_id = int(parts[2])
                    except ValueError as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="retry_cleanup_outbox",
                            target=_admin_audit_target(parsed.path),
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.BAD_REQUEST,
                            error_type=type(exc).__name__,
                        )
                        raise
                    cleanup_target = f"cleanup-outbox:{outbox_id}"
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="retry_cleanup_outbox",
                        target=cleanup_target,
                        before=None,
                        after=None,
                        result="attempted",
                        status=HTTPStatus.ACCEPTED,
                    )
                    try:
                        retry_payload, retry_status = _handle_cleanup_outbox_retry(
                            context,
                            outbox_id,
                        )
                    except Exception as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="retry_cleanup_outbox",
                            target=cleanup_target,
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                            error_type=type(exc).__name__,
                        )
                        raise
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="retry_cleanup_outbox",
                        target=cleanup_target,
                        before=None,
                        after=dict(retry_payload),
                        result="success" if retry_status == HTTPStatus.ACCEPTED else "failed",
                        status=retry_status,
                    )
                    self._send_json(
                        retry_payload,
                        status=retry_status,
                    )
                    return
                if parsed.path == "/api/openwebui/artifacts/delete":
                    artifact_payload = admin_body or {}
                    try:
                        artifact_kind = _required_text(artifact_payload, "target").strip().lower()
                        mapping_id = _required_int(artifact_payload, "mapping_id")
                        if artifact_kind not in {"pipe", "chat", "dataset"}:
                            raise ValueError("target muss pipe, chat oder dataset sein.")
                    except ValueError as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="delete_openwebui_artifact",
                            target="openwebui:artifact",
                            before=None,
                            after=None,
                            result="failed",
                            status=HTTPStatus.BAD_REQUEST,
                            error_type=type(exc).__name__,
                        )
                        raise
                    artifact_target = f"openwebui:{artifact_kind}:{mapping_id}"
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="delete_openwebui_artifact",
                        target=artifact_target,
                        before={"mapping_id": mapping_id, "target": artifact_kind},
                        after=None,
                        result="attempted",
                        status=HTTPStatus.OK,
                    )
                    try:
                        delete_payload = _handle_openwebui_artifact_delete(
                            context,
                            artifact_payload,
                        )
                    except Exception as exc:
                        _record_admin_audit(
                            context,
                            actor=admin_actor or "unknown",
                            action="delete_openwebui_artifact",
                            target=artifact_target,
                            before={"mapping_id": mapping_id, "target": artifact_kind},
                            after=None,
                            result="failed",
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                            error_type=type(exc).__name__,
                        )
                        raise
                    _record_admin_audit(
                        context,
                        actor=admin_actor or "unknown",
                        action="delete_openwebui_artifact",
                        target=artifact_target,
                        before={"mapping_id": mapping_id, "target": artifact_kind},
                        after=dict(delete_payload),
                        result="success",
                        status=HTTPStatus.OK,
                    )
                    self._send_json(delete_payload)
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except AuthzDeniedError:
                self._send_json(
                    {"error": "forbidden", "message": "Kein Zugriff auf diese Bibliothek."},
                    status=HTTPStatus.FORBIDDEN,
                )
            except PermissionError:
                self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            except ValueError as exc:
                self._send_json({"error": "bad request", "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError) as exc:
                structlog.get_logger(__name__).debug(
                    "dashboard.client_disconnected", path=parsed.path, error=str(exc)
                )
                return
            except Exception as exc:
                if parsed.path.startswith("/api/openwebui/proxy/"):
                    payload, status = _proxy_error_response(context.settings, parsed.path, exc)
                    self._send_json(payload, status=status)
                    return
                structlog.get_logger(__name__).warning("dashboard.request_failed", path=parsed.path, error=str(exc))
                self._send_json(
                    {"error": "dashboard request failed", "message": "Die Aktion konnte nicht ausgeführt werden."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args: Any) -> None:
            message = sanitize_http_access_message(format % args)
            structlog.get_logger(__name__).debug("dashboard.http_access", message=message)

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers(include_csp=True)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_xlsx(self, body: bytes, filename: str) -> None:
            self.send_response(HTTPStatus.OK.value)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_binary(
            self,
            body: bytes,
            *,
            status: HTTPStatus = HTTPStatus.OK,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status.value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_auth_required(self) -> None:
            body = json.dumps(
                {"error": "unauthorized", "message": "Dashboard-Anmeldung erforderlich."},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.UNAUTHORIZED.value)
            self.send_header(
                "WWW-Authenticate",
                'Basic realm="Seafile RAGFlow Connector Dashboard", charset="UTF-8"',
            )
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_security_headers(self, *, include_csp: bool = False) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if include_csp:
                self.send_header("Content-Security-Policy", DASHBOARD_CONTENT_SECURITY_POLICY)

        def _json_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length")
            length = int(raw_length or "0")
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid request body size")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError as exc:
                raise ValueError("invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

    return DashboardRequestHandler


def _dashboard_auth_ok(settings: Settings, authorization: str | None) -> bool:
    expected_username = settings.connector_dashboard_auth_username
    expected_password = settings.connector_dashboard_auth_password
    if not expected_username and not expected_password:
        return True
    if not expected_username or not expected_password:
        return False
    username, password = _parse_basic_auth(authorization)
    if username is None or password is None:
        return False
    username_matches = hmac.compare_digest(
        username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    return username_matches and password_matches


def _dashboard_admin_guard(
    context: DashboardContext,
    *,
    authorization: str | None,
    content_type: str | None,
    admin_action: str | None,
    fetch_site: str | None,
) -> tuple[str | None, dict[str, Any] | None, HTTPStatus]:
    settings = context.settings
    actor = _dashboard_admin_actor(settings, authorization)
    if not settings.connector_dashboard_enabled:
        return actor, {"error": "dashboard disabled"}, HTTPStatus.NOT_FOUND
    if actor is None:
        return (
            None,
            {"error": "unauthorized", "message": "Dashboard-Anmeldung erforderlich."},
            HTTPStatus.UNAUTHORIZED,
        )
    if not settings.connector_dashboard_control_enabled:
        return (
            actor,
            {
                "error": "forbidden",
                "message": "Dashboard-Steuerung ist nicht aktiviert.",
            },
            HTTPStatus.FORBIDDEN,
        )
    media_type = str(content_type or "").partition(";")[0].strip().lower()
    if media_type != "application/json":
        return (
            actor,
            {
                "error": "unsupported media type",
                "message": "Adminaktionen müssen als application/json gesendet werden.",
            },
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )
    if admin_action != "1":
        return (
            actor,
            {
                "error": "forbidden",
                "message": "Der Adminaktions-Header fehlt oder ist ungültig.",
            },
            HTTPStatus.FORBIDDEN,
        )
    normalized_fetch_site = str(fetch_site or "").strip().lower()
    if normalized_fetch_site not in {"", "none", "same-origin"}:
        return (
            actor,
            {
                "error": "forbidden",
                "message": "Site-übergreifende Adminaktionen werden abgewiesen.",
            },
            HTTPStatus.FORBIDDEN,
        )
    if not _workflow_control_available(context):
        return (
            actor,
            {
                "error": "admin control unavailable",
                "message": (
                    "Dashboard-Steuerung ist nur im laufenden Controller verfügbar."
                ),
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    return actor, None, HTTPStatus.OK


def _dashboard_admin_actor(settings: Settings, authorization: str | None) -> str | None:
    expected_username = settings.connector_dashboard_auth_username
    expected_password = settings.connector_dashboard_auth_password
    if not expected_username or not expected_password:
        return None
    username, password = _parse_basic_auth(authorization)
    if username is None or password is None:
        return None
    username_matches = hmac.compare_digest(
        username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )
    return username if username_matches and password_matches else None


def _is_dashboard_admin_mutation_path(path: str) -> bool:
    return (
        path in {
            "/api/workflow/run",
            "/api/workflow/runs",
            "/api/jobs/dead/cleanup",
            "/api/openwebui/artifacts/delete",
        }
        or path.startswith("/api/workflow/control/")
        or path.startswith("/api/workflow/libraries/")
        or path.startswith("/api/workflow/runs/")
        or (path.startswith("/api/cleanup-outbox/") and path.endswith("/retry"))
    )


def _admin_audit_scope(path: str) -> str | None:
    if path.startswith("/api/workflow/control/"):
        return "global"
    if path.startswith("/api/workflow/libraries/"):
        return "library"
    if path in {"/api/workflow/run", "/api/workflow/runs"} or path.startswith(
        "/api/workflow/runs/"
    ):
        return "run"
    if path == "/api/jobs/dead/cleanup":
        return "maintenance"
    if path.startswith("/api/cleanup-outbox/") and path.endswith("/retry"):
        return "cleanup"
    if path == "/api/openwebui/artifacts/delete":
        return "artifact"
    return None


def _admin_audit_action(path: str) -> str:
    if path in {"/api/workflow/run", "/api/workflow/runs"}:
        return "start"
    if path == "/api/jobs/dead/cleanup":
        return "cleanup_dead_jobs"
    if path.startswith("/api/cleanup-outbox/") and path.endswith("/retry"):
        return "retry_cleanup_outbox"
    if path == "/api/openwebui/artifacts/delete":
        return "delete_openwebui_artifact"
    parts = [unquote(part) for part in path.split("/") if part]
    return parts[-1] if parts else "unknown"


def _admin_audit_target(path: str) -> str:
    scope = _admin_audit_scope(path)
    parts = [unquote(part) for part in path.split("/") if part]
    if scope == "global":
        return "workflow"
    if scope == "library" and len(parts) >= 4:
        return f"library:{parts[3]}"
    if scope == "run":
        if path in {"/api/workflow/run", "/api/workflow/runs"}:
            return "workflow:new"
        if len(parts) >= 4:
            return f"workflow:{parts[3]}"
    if scope == "maintenance":
        return "jobs:dead"
    if scope == "cleanup" and len(parts) >= 3:
        return f"cleanup-outbox:{parts[2]}"
    if scope == "artifact":
        return "openwebui:artifact"
    return path


def _record_admin_audit(
    context: DashboardContext,
    *,
    actor: str,
    action: str,
    target: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    result: str,
    status: HTTPStatus | None = None,
    error_type: str | None = None,
    session: Session | None = None,
) -> None:
    scope = target.partition(":")[0] if ":" in target else "global"
    details: dict[str, Any] = {
        "actor": actor,
        "action": action,
        "target": target,
        "before": before,
        "after": after,
        "result": result,
    }
    if status is not None:
        details["http_status"] = int(status)
    if error_type is not None:
        details["error_type"] = error_type
    event_status = (
        "succeeded"
        if result == "success"
        else "pending"
        if result == "attempted"
        else "failed"
    )
    if session is not None:
        context.store.stage_change(
            session,
            sync_id=None,
            action=f"dashboard.admin.{action}",
            change_type=f"admin_{scope}_action",
            status=event_status,
            object_name=target,
            target_path=target,
            source_system="dashboard",
            target_system="connector",
            details=details,
        )
        return
    context.store.record_change(
        sync_id=None,
        action=f"dashboard.admin.{action}",
        change_type=f"admin_{scope}_action",
        status=event_status,
        object_name=target,
        target_path=target,
        source_system="dashboard",
        target_system="connector",
        details=details,
    )


def _control_audit_writer(
    context: DashboardContext,
    *,
    actor: str,
    action: str,
    target: str,
) -> ControlAuditWriter:
    def write(
        session: Session,
        before: dict[str, object],
        after: dict[str, object],
    ) -> None:
        _record_admin_audit(
            context,
            actor=actor,
            action=action,
            target=target,
            before=before,
            after=after,
            result="attempted",
            status=HTTPStatus.ACCEPTED,
            session=session,
        )

    return write


def _parse_basic_auth(authorization: str | None) -> tuple[str | None, str | None]:
    if not authorization:
        return None, None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "basic" or not token.strip():
        return None, None
    try:
        decoded = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None, None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None, None
    return username, password


def _handle_authz_check(
    context: DashboardContext,
    payload: dict[str, Any],
    authorization: str | None,
    client_host: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    if not _authz_request_ok(context.settings, authorization, client_host):
        return {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED
    service = _access_control_service(context)
    if service is None:
        return {"error": "authz unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    user = _user_identity_from_payload(payload.get("user"))
    resource = _resource_from_payload(payload.get("resource"))
    operation = str(payload.get("operation") or "search")
    decision = service.check_access(user, resource, operation)
    _log_authz_decision(user, resource, operation, decision.to_payload())
    return decision.to_payload(), HTTPStatus.OK


def _handle_authz_filter_profiles(
    context: DashboardContext,
    payload: dict[str, Any],
    authorization: str | None,
    client_host: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    if not _authz_request_ok(context.settings, authorization, client_host):
        return {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED
    service = _access_control_service(context)
    if service is None:
        return {"error": "authz unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    user = _user_identity_from_payload(payload.get("user"))
    profile_ids = _profile_ids_from_payload(payload.get("profile_ids"))
    profiles, denied = service.filter_profiles_for_user(user, profile_ids)
    allowed = []
    for profile in profiles:
        decision = service.check_access(
            user,
            AuthzResource(repo_id=profile.repo_id, ragflow_dataset_id=profile.ragflow_dataset_id),
            "search",
        )
        item = _search_profile_payload(profile, permission=decision.permission)
        item["profile_id"] = profile.repo_id
        allowed.append(item)
    return {"allowed": allowed, "denied": denied}, HTTPStatus.OK


def _handle_authz_profiles(
    context: DashboardContext,
    authorization: str | None,
    client_host: str,
    username: str | None,
    email: str | None,
) -> tuple[dict[str, Any], HTTPStatus]:
    if not _authz_request_ok(context.settings, authorization, client_host):
        return {"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED
    service = _access_control_service(context)
    if service is None:
        return {"error": "authz unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    user = UserIdentity(username=username, email=email)
    profiles, denied = service.filter_profiles_for_user(user, None)
    items: list[dict[str, Any]] = []
    for profile in profiles:
        decision = service.check_access(
            user,
            AuthzResource(repo_id=profile.repo_id, ragflow_dataset_id=profile.ragflow_dataset_id),
            "search",
        )
        items.append(_search_profile_payload(profile, permission=decision.permission))
    return {"profiles": items, "denied_count": len(denied)}, HTTPStatus.OK


def _handle_search_document(
    context: DashboardContext,
    params: dict[str, list[str]],
    authorization: str | None,
    client_host: str,
    username: str | None,
    email: str | None,
) -> tuple[bytes, HTTPStatus, dict[str, str]]:
    settings = context.settings
    if not settings.search_document_viewer_enabled:
        return _json_error_bytes("viewer disabled"), HTTPStatus.NOT_FOUND, {
            "Content-Type": "application/json; charset=utf-8"
        }
    if not _authz_request_ok(settings, authorization, client_host):
        return _json_error_bytes("unauthorized"), HTTPStatus.UNAUTHORIZED, {
            "Content-Type": "application/json; charset=utf-8"
        }
    try:
        repo_id = _required_query_text(params, "repo_id")
        source_path = _normalize_document_path(_required_query_text(params, "path"))
    except ValueError as exc:
        return _json_error_bytes(str(exc)), HTTPStatus.BAD_REQUEST, {
            "Content-Type": "application/json; charset=utf-8"
        }
    service = _access_control_service(context)
    if service is None:
        return _json_error_bytes("authz unavailable"), HTTPStatus.SERVICE_UNAVAILABLE, {
            "Content-Type": "application/json; charset=utf-8"
        }
    user = UserIdentity(username=username, email=email)
    decision = service.check_access(user, AuthzResource(repo_id=repo_id, ragflow_dataset_id=None), "search")
    _log_authz_decision(user, AuthzResource(repo_id=repo_id, ragflow_dataset_id=None), "search", decision.to_payload())
    if decision.decision != "allow":
        return _json_error_bytes("forbidden"), HTTPStatus.FORBIDDEN, {
            "Content-Type": "application/json; charset=utf-8"
        }
    try:
        body = _download_search_document(settings, repo_id=repo_id, source_path=source_path)
    except ApiError as exc:
        status = HTTPStatus.NOT_FOUND if exc.status_code == 404 else HTTPStatus.BAD_GATEWAY
        return _json_error_bytes("document unavailable"), status, {
            "Content-Type": "application/json; charset=utf-8"
        }
    except httpx.HTTPStatusError as exc:
        status = HTTPStatus.NOT_FOUND if exc.response.status_code == 404 else HTTPStatus.BAD_GATEWAY
        return _json_error_bytes("document unavailable"), status, {
            "Content-Type": "application/json; charset=utf-8"
        }
    except httpx.HTTPError:
        return _json_error_bytes("document unavailable"), HTTPStatus.BAD_GATEWAY, {
            "Content-Type": "application/json; charset=utf-8"
        }
    max_bytes = settings.search_document_viewer_max_mb * 1024 * 1024
    if len(body) > max_bytes:
        return _json_error_bytes("document too large"), HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {
            "Content-Type": "application/json; charset=utf-8"
        }
    return body, HTTPStatus.OK, _document_headers(source_path)


def _access_control_service(context: DashboardContext) -> AccessControlService | None:
    if context.store is None:
        return None
    return AccessControlService.from_settings(
        session_factory=context.store.session_factory,
        settings=context.settings,
    )


def _authz_request_ok(settings: Settings, authorization: str | None, client_host: str) -> bool:
    if not settings.authz_api_enabled:
        return False
    if not _bearer_matches(authorization, settings.authz_api_shared_secret):
        return False
    networks = settings.authz_api_allow_networks
    if not networks:
        return True
    try:
        address = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    for raw_network in networks:
        try:
            network = ipaddress.ip_network(raw_network, strict=False)
        except ValueError:
            continue
        if address in network:
            return True
    return False


def _bearer_matches(authorization: str | None, secret: str | None) -> bool:
    if not authorization or not secret:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return hmac.compare_digest(token.strip(), secret)


def _user_identity_from_payload(value: Any) -> UserIdentity:
    if not isinstance(value, dict):
        return UserIdentity(username=None, email=None)
    username = value.get("username") or value.get("name") or value.get("id")
    email = value.get("email")
    return UserIdentity(
        username=str(username) if username not in (None, "") else None,
        email=str(email) if email not in (None, "") else None,
    )


def _resource_from_payload(value: Any) -> AuthzResource:
    if not isinstance(value, dict):
        return AuthzResource(repo_id=None, ragflow_dataset_id=None)
    repo_id = value.get("repo_id")
    dataset_id = value.get("ragflow_dataset_id") or value.get("dataset_id")
    return AuthzResource(
        repo_id=str(repo_id) if repo_id not in (None, "") else None,
        ragflow_dataset_id=str(dataset_id) if dataset_id not in (None, "") else None,
    )


def _profile_ids_from_payload(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("profile_ids must be a list")
    return [str(item) for item in value if item not in (None, "")]


def _required_query_text(params: dict[str, list[str]], key: str) -> str:
    value = _one(params, key)
    if value in (None, ""):
        raise ValueError(f"{key} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _normalize_document_path(value: str) -> str:
    clean = str(value or "").strip().replace("\\", "/")
    if not clean:
        raise ValueError("path is required")
    return clean if clean.startswith("/") else f"/{clean}"


def _download_search_document(settings: Settings, *, repo_id: str, source_path: str) -> bytes:
    client = SeafileSyncClient(
        settings.seafile_internal_url or settings.seafile_base_url,
        settings.seafile_sync_user_token,
        verify=settings.seafile_httpx_verify,
        rewrite_download_urls=settings.seafile_rewrite_download_urls,
        rewrite_from=settings.seafile_download_rewrite_from,
        rewrite_to=settings.seafile_download_rewrite_to,
        allowed_download_origins=settings.seafile_download_allowed_origins,
        max_download_bytes=settings.search_document_viewer_max_mb * 1024 * 1024,
    )
    try:
        return client.download_file(repo_id, source_path)
    finally:
        client.close()


def _document_headers(source_path: str) -> dict[str, str]:
    content_type, disposition_mode = _document_content_type(source_path)
    return {
        "Content-Type": content_type,
        "Content-Disposition": f'{disposition_mode}; filename="{_safe_filename(source_path)}"',
    }


def _document_content_type(source_path: str) -> tuple[str, str]:
    lower = source_path.lower()
    if lower.endswith((".html", ".htm", ".md", ".markdown")):
        return "text/plain; charset=utf-8", "inline"
    guessed, _ = mimetypes.guess_type(source_path)
    if lower.endswith(".pdf"):
        return "application/pdf", "inline"
    if guessed and guessed.startswith("image/"):
        return guessed, "inline"
    if guessed and (
        guessed.startswith("text/")
        or guessed in {"application/json", "application/xml", "text/csv"}
    ):
        return guessed, "inline"
    if lower.endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp")):
        return guessed or "application/octet-stream", "attachment"
    return guessed or "application/octet-stream", "inline"


def _json_error_bytes(message: str) -> bytes:
    return json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")


def _safe_filename(path: str) -> str:
    filename = str(path or "document").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    filename = "".join(char for char in filename if char not in {'"', "\r", "\n"}).strip()
    return filename or "document"


def _search_profile_payload(profile: SearchProfile, *, permission: str | None = None) -> dict[str, Any]:
    payload = {
        "id": profile.repo_id,
        "repo_id": profile.repo_id,
        "display_name": profile.display_name,
        "kind": profile.kind,
        "ragflow_dataset_id": profile.ragflow_dataset_id,
        "status": profile.status,
    }
    if permission:
        payload["permission"] = permission
    return payload


def _log_authz_decision(
    user: UserIdentity,
    resource: AuthzResource,
    operation: str,
    decision: dict[str, Any],
) -> None:
    structlog.get_logger(__name__).info(
        "authz.decision",
        username=user.username,
        email_present=bool(user.email),
        repo_id=decision.get("repo_id") or resource.repo_id,
        ragflow_dataset_id=decision.get("ragflow_dataset_id") or resource.ragflow_dataset_id,
        operation=operation,
        decision=decision.get("decision"),
        reason=decision.get("reason"),
    )


def _one(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _int(params: dict[str, list[str]], key: str) -> int | None:
    value = _one(params, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_config(settings: Settings) -> dict[str, Any]:
    safe = {
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "log_format": settings.log_format,
        "dry_run": settings.dry_run,
        "seafile_base_url": settings.seafile_base_url,
        "seafile_public_base_url": settings.seafile_public_base_url,
        "seafile_file_url_template": settings.seafile_file_url_template,
        "seafile_skip_encrypted_libraries": settings.seafile_skip_encrypted_libraries,
        "seafile_skip_virtual_repos": settings.seafile_skip_virtual_repos,
        "ragflow_base_url": settings.ragflow_base_url,
        "ragflow_template_dataset_name": settings.ragflow_template_dataset_name,
        "ragflow_refresh_dataset_settings": settings.ragflow_refresh_dataset_settings,
        "postgres_host": settings.postgres_host,
        "postgres_port": settings.postgres_port,
        "postgres_db": settings.postgres_db,
        "redis_host": settings.redis_host,
        "redis_port": settings.redis_port,
        "redis_db": settings.redis_db,
        "allow_unknown_text_files": settings.allow_unknown_text_files,
        "deny_extensions": settings.deny_extensions,
        "text_extensions": settings.text_extensions,
        "default_text_ingestion_strategy": settings.default_text_ingestion_strategy,
        "discovery_interval_seconds": settings.discovery_interval_seconds,
        "delta_sync_interval_seconds": settings.delta_sync_interval_seconds,
        "reconcile_interval_seconds": settings.reconcile_interval_seconds,
        "delete_ragflow_docs_on_seafile_delete": settings.delete_ragflow_docs_on_seafile_delete,
        "connector_dashboard_enabled": settings.connector_dashboard_enabled,
        "connector_dashboard_control_enabled": settings.connector_dashboard_control_enabled,
        "connector_dashboard_host": settings.connector_dashboard_host,
        "connector_dashboard_port": settings.connector_dashboard_port,
        "connector_dashboard_max_log_entries": settings.connector_dashboard_max_log_entries,
        "connector_dashboard_max_event_entries": settings.connector_dashboard_max_event_entries,
        "connector_dashboard_max_sync_runs": settings.connector_dashboard_max_sync_runs,
        "connector_dashboard_log_page_size": settings.connector_dashboard_log_page_size,
        "connector_dashboard_auth_enabled": bool(
            settings.connector_dashboard_auth_username
            and settings.connector_dashboard_auth_password
        ),
        "connector_transport_status": settings.connector_transport_status,
        "openwebui_integration_enabled": settings.openwebui_integration_enabled,
        "openwebui_base_url": settings.openwebui_base_url,
        "openwebui_sync_on_startup": settings.openwebui_sync_on_startup,
        "openwebui_sync_mode": settings.openwebui_effective_sync_mode,
        "openwebui_create_tools": settings.openwebui_create_tools,
        "openwebui_create_pipes": settings.openwebui_create_pipes,
        "openwebui_request_timeout_seconds": settings.openwebui_request_timeout_seconds,
        "openwebui_verify_ssl": settings.openwebui_verify_ssl,
        "openwebui_function_namespace": settings.openwebui_function_namespace,
        "openwebui_source_preview_mode": settings.openwebui_source_preview_mode,
        "openwebui_proxy_public_base_url": settings.openwebui_proxy_public_base_url,
        "openwebui_proxy_internal_base_url": settings.openwebui_proxy_internal_base_url,
        "openwebui_sync_interval_seconds": settings.openwebui_sync_interval_seconds,
        "openwebui_dataset_allowlist": settings.openwebui_dataset_allowlist,
        "ragflow_public_base_url": settings.ragflow_public_base_url,
        "ragflow_document_url_template": settings.ragflow_document_url_template,
    }
    return dict(redact_mapping(safe))


def _handle_dead_jobs_cleanup(context: DashboardContext) -> dict[str, Any]:
    result = context.store.cleanup_dead_jobs()
    cleaned = int(result.get("cleaned_jobs") or 0)
    message = f"{cleaned} tote Jobs bereinigt." if cleaned else "Keine toten Jobs vorhanden."
    return {**result, "message": message}


def _handle_cleanup_outbox_retry(
    context: DashboardContext,
    outbox_id: int,
) -> tuple[dict[str, Any], HTTPStatus]:
    assert context.orchestrator is not None
    assert context.job_store is not None
    assert context.signal_queue is not None
    repo_id = context.orchestrator.requeue_cleanup_outbox(outbox_id)
    if repo_id is None:
        return {"outbox_id": outbox_id, "retried": False}, HTTPStatus.CONFLICT
    enqueue_result = context.job_store.enqueue_with_result(
        JobSpec(
            JobType.PROCESS_CLEANUP_OUTBOX,
            repo_id=repo_id,
            payload={"outbox_id": outbox_id},
        )
    )
    retry_payload: dict[str, Any] = {
        "outbox_id": outbox_id,
        "retried": True,
        "job_id": enqueue_result.job_id,
        "deduplicated": enqueue_result.deduplicated,
    }
    if not enqueue_result.deduplicated:
        try:
            context.signal_queue.signal(enqueue_result.job_id)
        except Exception as exc:
            signal_warning = type(exc).__name__
            retry_payload["signal_warning"] = signal_warning
            structlog.get_logger(__name__).warning(
                "dashboard.cleanup_retry_signal_failed",
                job_id=enqueue_result.job_id,
                error_type=signal_warning,
            )
    return retry_payload, HTTPStatus.ACCEPTED


def _handle_openwebui_artifact_delete(
    context: DashboardContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    target = _required_text(payload, "target").strip().lower()
    if target not in {"pipe", "chat", "dataset"}:
        raise ValueError("target muss pipe, chat oder dataset sein.")
    mapping_id = _required_int(payload, "mapping_id")
    if target == "pipe":
        return _delete_openwebui_pipe_artifact(context, mapping_id)
    if target == "chat":
        return _delete_ragflow_chat_artifact(context, mapping_id)
    return _delete_ragflow_dataset_artifact(context, mapping_id)


def _delete_openwebui_pipe_artifact(context: DashboardContext, mapping_id: int) -> dict[str, Any]:
    mapping, _library = _load_dashboard_mapping(context, mapping_id)
    pipe_id = mapping.openwebui_pipe_id
    if not pipe_id:
        return _artifact_delete_response("pipe", None, "missing", "Keine Pipe hinterlegt.")

    client = _openwebui_admin_client(context.settings)
    try:
        existing = client.get_function(pipe_id)
        if existing is not None and not _is_owned_openwebui_artifact(
            existing,
            expected_kind="pipe",
            dataset_id=mapping.ragflow_dataset_id,
        ):
            raise ValueError("OpenWebUI-Pipe ist nicht vom Connector erzeugt.")
        deleted = client.delete_function(pipe_id) if existing is not None else False
    finally:
        client.close()

    with context.store.session_factory() as session:
        stored = session.get(OpenWebUIDatasetMapping, mapping_id)
        if stored:
            stored.openwebui_pipe_id = None
            stored.openwebui_model_name = None
            stored.pipe_definition_hash = None
            stored.openwebui_pipe_payload = {}
            stored.sync_status = "pending"
            stored.last_error = None
            session.commit()
    _record_dashboard_artifact_delete(
        context,
        target="pipe",
        artifact_id=pipe_id,
        mapping=mapping,
        status="deleted" if deleted else "missing",
    )
    return _artifact_delete_response(
        "pipe",
        pipe_id,
        "deleted" if deleted else "missing",
        "Pipe gelöscht; die Seafile-Bibliothek bleibt bestehen.",
    )


def _delete_ragflow_chat_artifact(context: DashboardContext, mapping_id: int) -> dict[str, Any]:
    mapping, _library = _load_dashboard_mapping(context, mapping_id)
    chat_id = mapping.ragflow_chat_id
    if not chat_id:
        return _artifact_delete_response("chat", None, "missing", "Kein RAGFlow-Chat hinterlegt.")

    ragflow = _ragflow_client(context.settings)
    try:
        ragflow.delete_chats([chat_id])
    finally:
        ragflow.close()

    with context.store.session_factory() as session:
        stored = session.get(OpenWebUIDatasetMapping, mapping_id)
        if stored:
            stored.ragflow_chat_id = None
            stored.pipe_definition_hash = None
            stored.sync_status = "pending"
            stored.last_error = None
            session.commit()
    _record_dashboard_artifact_delete(
        context,
        target="chat",
        artifact_id=chat_id,
        mapping=mapping,
        status="deleted",
    )
    return _artifact_delete_response(
        "chat",
        chat_id,
        "deleted",
        "RAGFlow-Chat gelöscht; die Seafile-Bibliothek bleibt bestehen.",
    )


def _delete_ragflow_dataset_artifact(context: DashboardContext, mapping_id: int) -> dict[str, Any]:
    mapping, library = _load_dashboard_mapping(context, mapping_id)
    dataset_id = mapping.ragflow_dataset_id
    ragflow = _ragflow_client(context.settings)
    try:
        ragflow.delete_datasets([dataset_id])
    finally:
        ragflow.close()

    with context.store.session_factory() as session:
        stored_library = session.get(Library, library.repo_id)
        if stored_library and stored_library.ragflow_dataset_id == dataset_id:
            stored_library.ragflow_dataset_id = None
            stored_library.ragflow_dataset_name = None
            stored_library.template_hash = None
            stored_library.last_synced_commit_id = None
            stored_library.last_error = None
        stored_mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
        if stored_mapping:
            stored_mapping.sync_status = "dataset_deleted"
            stored_mapping.last_error = None
        session.commit()
    _record_dashboard_artifact_delete(
        context,
        target="dataset",
        artifact_id=dataset_id,
        mapping=mapping,
        status="deleted",
    )
    return _artifact_delete_response(
        "dataset",
        dataset_id,
        "deleted",
        "RAGFlow-Dataset gelöscht; die Seafile-Bibliothek bleibt bestehen.",
    )


WORKFLOW_GLOBAL_ACTIONS = ["start", "deactivate", "pause", "resume", "stop"]
WORKFLOW_LIBRARY_ACTIONS = ["enable", "disable", "pause", "resume"]
WORKFLOW_RUN_ACTIONS = ["pause", "resume", "stop", "cancel", "retry"]
WORKFLOW_RUN_ACTIONS_BY_STATUS: dict[str, list[str]] = {
    "queued": ["pause", "stop", "cancel"],
    "retrying": ["pause", "stop", "cancel"],
    "running": ["pause", "stop", "cancel"],
    "paused": ["resume", "stop", "cancel"],
    "failed": ["retry"],
    "cancelled": ["retry"],
    "stopped": ["retry"],
    "succeeded": [],
}


def _admin_control_store(context: DashboardContext) -> AdminControlStore:
    if context.control_store is not None:
        return cast(AdminControlStore, context.control_store)
    session_factory = (
        context.job_store.session_factory
        if context.job_store is not None
        else context.store.session_factory
    )
    return AdminControlStore(session_factory)


def _workflow_control_available(context: DashboardContext) -> bool:
    return bool(
        context.settings.connector_dashboard_enabled
        and context.settings.connector_dashboard_control_enabled
        and context.orchestrator is not None
        and context.job_store is not None
        and context.signal_queue is not None
    )


def _workflow_active_counts(context: DashboardContext) -> dict[str, int]:
    raw = context.job_store.active_counts() if context.job_store is not None else {}
    return {
        "queued": int(raw.get(JobStatus.QUEUED.value, 0)),
        "retrying": int(raw.get(JobStatus.RETRYING.value, 0)),
        "running": int(raw.get(JobStatus.RUNNING.value, 0)),
        "paused": int(raw.get("paused", 0)),
    }


def _workflow_capabilities(enabled: bool, *, state: str | None = None) -> dict[str, list[str]]:
    global_actions_by_state = {
        "running": ["deactivate", "pause", "stop"],
        "paused": ["start", "deactivate", "resume", "stop"],
        "deactivated": ["start", "pause", "stop"],
        "stopped": ["start", "resume", "stop"],
    }
    return {
        "global_actions": (
            list(global_actions_by_state.get(str(state), WORKFLOW_GLOBAL_ACTIONS))
            if enabled
            else []
        ),
        "library_actions": list(WORKFLOW_LIBRARY_ACTIONS) if enabled else [],
        "run_actions": list(WORKFLOW_RUN_ACTIONS) if enabled else [],
    }


def _workflow_run_actions(status: str, *, enabled: bool = True) -> list[str]:
    if not enabled:
        return []
    return list(WORKFLOW_RUN_ACTIONS_BY_STATUS.get(status, []))


def _handle_workflow_control(context: DashboardContext) -> dict[str, Any]:
    snapshot = _admin_control_store(context).workflow().to_payload()
    control_enabled = _workflow_control_available(context)
    return {
        "control_enabled": control_enabled,
        **snapshot,
        "active_jobs": _workflow_active_counts(context),
        "capabilities": _workflow_capabilities(
            control_enabled,
            state=str(snapshot["state"]),
        ),
    }


def _handle_workflow_control_action(
    context: DashboardContext,
    action: str,
    payload: dict[str, Any],
    *,
    actor: str | None,
) -> tuple[dict[str, Any], HTTPStatus]:
    resolved_actor = actor or "unknown"
    target = "workflow"
    if action not in WORKFLOW_GLOBAL_ACTIONS:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action or "unknown",
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.NOT_FOUND,
        )
        return {"error": "not found"}, HTTPStatus.NOT_FOUND
    if not _workflow_control_available(context):
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
        return (
            {
                "error": "control unavailable",
                "message": "Dashboard-Steuerung benötigt Controller, Job-Queue und Signalweg.",
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    assert context.orchestrator is not None
    assert context.job_store is not None
    assert context.signal_queue is not None
    if action == "stop" and payload.get("confirm") != "STOP":
        before = _admin_control_store(context).workflow().to_payload()
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=before,
            result="failed",
            status=HTTPStatus.BAD_REQUEST,
        )
        return (
            {
                "error": "confirmation required",
                "message": "Stop erfordert confirm=STOP.",
            },
            HTTPStatus.BAD_REQUEST,
        )
    updates: dict[str, tuple[bool | None, bool | None]] = {
        "start": (True, False),
        "deactivate": (False, None),
        "pause": (None, True),
        "resume": (None, False),
        "stop": (False, True),
    }
    automation_enabled, queue_paused = updates[action]
    control_store = _admin_control_store(context)
    before = control_store.workflow().to_payload()
    try:
        locked_before, after = control_store.update_workflow(
            updated_by=resolved_actor,
            automation_enabled=automation_enabled,
            queue_paused=queue_paused,
            audit_writer=_control_audit_writer(
                context,
                actor=resolved_actor,
                action=action,
                target=target,
            ),
        )
        before = locked_before.to_payload()
        response: dict[str, Any] = {
            "control_enabled": True,
            **after.to_payload(),
            "action": action,
        }
        changed_job_ids: list[int] = []
        signal_warnings: list[int] = []
        if action in {"start", "resume"}:
            changed_job_ids = context.job_store.resume_global_pause()
            for job_id in changed_job_ids:
                try:
                    context.signal_queue.signal(job_id)
                except Exception as exc:
                    signal_warnings.append(job_id)
                    structlog.get_logger(__name__).warning(
                        "dashboard.workflow_resume_signal_failed",
                        job_id=job_id,
                        error_type=type(exc).__name__,
                    )
        if action == "start":
            spec = JobSpec(
                JobType.DISCOVER_LIBRARIES,
                payload={"trigger": "admin_start"},
            )
            enqueue_result = context.job_store.enqueue_with_result(spec)
            enqueued = [
                {
                    "job_id": enqueue_result.job_id,
                    "job_type": spec.job_type.value,
                    "repo_id": spec.repo_id,
                    "deduplicated": enqueue_result.deduplicated,
                }
            ]
            if not enqueue_result.deduplicated:
                try:
                    context.signal_queue.signal(enqueue_result.job_id)
                except Exception as exc:
                    signal_warnings.append(enqueue_result.job_id)
                    structlog.get_logger(__name__).warning(
                        "dashboard.workflow_start_signal_failed",
                        job_id=enqueue_result.job_id,
                        error_type=type(exc).__name__,
                    )
            response["jobs"] = enqueued
        elif action == "pause":
            changed_job_ids = context.job_store.request_pause_all()
        elif action == "stop":
            changed_job_ids = context.job_store.request_cancel_all()
            response["cancel_requested_job_ids"] = changed_job_ids
        response["changed_job_ids"] = changed_job_ids
        if signal_warnings:
            response["signal_warning_job_ids"] = signal_warnings
        response["active_jobs"] = _workflow_active_counts(context)
        response["capabilities"] = _workflow_capabilities(
            True,
            state=str(after.state),
        )
        audit_after = {
            **after.to_payload(),
            "changed_job_ids": changed_job_ids,
            "signal_warning_job_ids": signal_warnings,
        }
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=audit_after,
            result="success",
            status=HTTPStatus.ACCEPTED,
        )
        return response, HTTPStatus.ACCEPTED
    except Exception as exc:
        try:
            actual_after = control_store.workflow().to_payload()
        except Exception:
            actual_after = before
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=actual_after,
            result="partial" if actual_after != before else "failed",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_type=type(exc).__name__,
        )
        raise


def _handle_workflow_libraries(context: DashboardContext) -> dict[str, Any]:
    if context.orchestrator is None or context.job_store is None or context.signal_queue is None:
        return {
            "enabled": False,
            "message": "Dashboard-Steuerung ist nur mit laufendem Controller und Job-Queue verfügbar.",
            "libraries": [],
            "summary": {"visible": 0, "selectable": 0, "with_dataset": 0},
            "options": _workflow_options(context),
        }
    libraries = _visible_workflow_libraries(context)
    return {
        "enabled": True,
        "libraries": libraries,
        "summary": {
            "visible": len(libraries),
            "selectable": sum(1 for item in libraries if item["selectable"]),
            "with_dataset": sum(1 for item in libraries if item["ragflow_dataset_id"]),
        },
        "options": _workflow_options(context),
    }


def _known_workflow_repo_ids(context: DashboardContext) -> set[str]:
    stored_libraries, _ = _stored_workflow_state(context)
    known = set(stored_libraries)
    if context.orchestrator is not None:
        known.update(str(item["repo_id"]) for item in _visible_workflow_libraries(context))
    return known


def _handle_workflow_library_action(
    context: DashboardContext,
    repo_id: str,
    action: str,
    *,
    actor: str | None,
) -> tuple[dict[str, Any], HTTPStatus]:
    resolved_actor = actor or "unknown"
    normalized_repo_id = repo_id.strip()
    target = f"library:{normalized_repo_id or repo_id}"
    if action not in WORKFLOW_LIBRARY_ACTIONS:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action or "unknown",
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.NOT_FOUND,
        )
        return {"error": "not found"}, HTTPStatus.NOT_FOUND
    if context.job_store is None or context.orchestrator is None or context.signal_queue is None:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
        return {"error": "control unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    if not normalized_repo_id or normalized_repo_id not in _known_workflow_repo_ids(context):
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.NOT_FOUND,
        )
        return {"error": "library not found"}, HTTPStatus.NOT_FOUND
    updates: dict[str, tuple[bool | None, bool | None]] = {
        "enable": (True, False),
        "disable": (False, None),
        "pause": (None, True),
        "resume": (None, False),
    }
    enabled, paused = updates[action]
    control_store = _admin_control_store(context)
    before_snapshot = control_store.libraries([normalized_repo_id])[normalized_repo_id]
    before = before_snapshot.to_payload()
    try:
        locked_before, after = control_store.update_library(
            normalized_repo_id,
            updated_by=resolved_actor,
            enabled=enabled,
            paused=paused,
            audit_writer=_control_audit_writer(
                context,
                actor=resolved_actor,
                action=action,
                target=target,
            ),
        )
        before = locked_before.to_payload()
        if action in {"disable", "pause"}:
            changed_job_ids = context.job_store.request_repo_pause(normalized_repo_id)
        elif after.runnable:
            changed_job_ids = context.job_store.resume_repo(normalized_repo_id)
            for job_id in changed_job_ids:
                try:
                    context.signal_queue.signal(job_id)
                except Exception as exc:
                    structlog.get_logger(__name__).warning(
                        "dashboard.library_resume_signal_failed",
                        repo_id=normalized_repo_id,
                        job_id=job_id,
                        error_type=type(exc).__name__,
                    )
        else:
            changed_job_ids = []
        control_payload = after.to_payload()
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after={**control_payload, "changed_job_ids": changed_job_ids},
            result="success",
            status=HTTPStatus.ACCEPTED,
        )
        return (
            {
                "repo_id": normalized_repo_id,
                "action": action,
                "admin_state": control_payload["state"],
                "admin_enabled": control_payload["enabled"],
                "admin_paused": control_payload["paused"],
                "admin_control": control_payload,
                "changed_job_ids": changed_job_ids,
            },
            HTTPStatus.ACCEPTED,
        )
    except Exception as exc:
        try:
            actual_after = control_store.libraries([normalized_repo_id])[
                normalized_repo_id
            ].to_payload()
        except Exception:
            actual_after = before
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=actual_after,
            result="partial" if actual_after != before else "failed",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_type=type(exc).__name__,
        )
        raise


def _handle_workflow_run(
    context: DashboardContext,
    payload: dict[str, Any],
    *,
    actor: str | None,
) -> tuple[dict[str, Any], HTTPStatus]:
    resolved_actor = actor or "unknown"
    try:
        result, status = _handle_workflow_run_impl(
            context,
            payload,
            actor=resolved_actor,
        )
    except Exception as exc:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action="start",
            target="workflow:new",
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.BAD_REQUEST if isinstance(exc, ValueError) else HTTPStatus.INTERNAL_SERVER_ERROR,
            error_type=type(exc).__name__,
        )
        raise
    if status.value >= 400:
        failed_run_id = str(result.get("run_id") or "").strip()
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action="start",
            target=(f"workflow:{failed_run_id}" if failed_run_id else "workflow:new"),
            before=None,
            after={
                "run_id": failed_run_id or None,
                "status": result.get("status"),
                "scheduled_jobs": len(result.get("jobs") or []),
            },
            result="failed",
            status=status,
        )
    return result, status


def _handle_workflow_run_impl(
    context: DashboardContext,
    payload: dict[str, Any],
    *,
    actor: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    if (
        context.orchestrator is None
        or context.job_store is None
        or context.signal_queue is None
    ):
        return (
            {
                "status": "unavailable",
                "message": "Dashboard-Steuerung ist nur mit laufendem Controller und Job-Queue verfügbar.",
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    workflow_control = _admin_control_store(context).workflow()
    if workflow_control.queue_paused:
        return (
            {
                "error": "queue paused",
                "message": "Manuelle Läufe sind bei pausierter Queue nicht erlaubt.",
            },
            HTTPStatus.CONFLICT,
        )
    repo_ids = _workflow_repo_ids(payload)
    create_dataset = _workflow_bool(payload, "create_dataset", default=True)
    sync_openwebui = _workflow_bool(payload, "sync_openwebui", default=True)
    if not create_dataset and not sync_openwebui:
        raise ValueError("Mindestens RAGFlow-Dataset oder OpenWebUI-Sync muss ausgewählt sein.")
    scope = _workflow_scope(payload)
    mode = _workflow_mode(payload)
    visible = _visible_workflow_libraries(context)
    visible_by_repo = {str(item["repo_id"]): item for item in visible}
    missing = [repo_id for repo_id in repo_ids if repo_id not in visible_by_repo]
    if missing:
        raise ValueError(
            "Nicht mit dem aktuellen Seafile-API-Key sichtbar: " + ", ".join(missing)
        )
    skipped = [
        repo_id
        for repo_id in repo_ids
        if not bool(visible_by_repo[repo_id].get("selectable"))
    ]
    if skipped:
        raise ValueError("Nicht auswählbare Bibliotheken: " + ", ".join(skipped))
    library_controls = _admin_control_store(context).libraries(repo_ids)
    blocked = [repo_id for repo_id in repo_ids if not library_controls[repo_id].runnable]
    if blocked:
        return (
            {
                "error": "library blocked",
                "message": "Deaktivierte oder pausierte Bibliotheken: " + ", ".join(blocked),
                "repo_ids": blocked,
            },
            HTTPStatus.CONFLICT,
        )

    workflow_run_id = new_sync_id("workflow")
    _record_admin_audit(
        context,
        actor=actor,
        action="start",
        target=f"workflow:{workflow_run_id}",
        before={"exists": False},
        after={
            "exists": True,
            "status": "queued",
            "repo_ids": repo_ids,
            "mode": mode,
            "scope": scope,
            "trigger": "manual",
        },
        result="attempted",
        status=HTTPStatus.ACCEPTED,
    )
    sync_state_store = SyncStateStore(context.job_store.session_factory)
    sync_state_store.create_run(
        run_id=workflow_run_id,
        repo_id=None,
        mode="workflow",
        scope=scope,
        status="queued",
        progress={"selected_repositories": len(repo_ids)},
    )
    details = {
        "kind": "workflow_parent",
        "mode": mode,
        "scope": scope,
        "repo_ids": repo_ids,
        "job_ids": [],
        "create_dataset": create_dataset,
        "sync_openwebui": sync_openwebui,
        "trigger": "manual",
        "actor": actor,
    }
    context.store.create_sync_run(
        sync_id=workflow_run_id,
        source="dashboard",
        target="job-queue",
        status="queued",
        summary="Workflow wird eingeplant",
        details=details,
    )
    jobs: list[dict[str, Any]] = []
    signal_job_ids: list[int] = []
    created_job_ids: list[int] = []
    try:
        for repo_id in repo_ids:
            if create_dataset:
                job_type = {
                    "delta": JobType.SYNC_LIBRARY_DELTA,
                    "full": JobType.SYNC_LIBRARY_FULL,
                    "reconcile": JobType.RECONCILE_LIBRARY,
                }[mode]
                spec = JobSpec(
                    job_type,
                    repo_id=repo_id,
                    payload={
                        "scope": scope,
                        "workflow_run_id": workflow_run_id,
                        "sync_openwebui": sync_openwebui,
                        "trigger": "manual",
                    },
                )
            else:
                spec = JobSpec(
                    JobType.SYNC_OPENWEBUI,
                    repo_id=repo_id,
                    payload={
                        "repo_ids": [repo_id],
                        "workflow_run_id": workflow_run_id,
                        "trigger": "manual",
                    },
                )
            enqueue_result = context.job_store.enqueue_with_result(spec)
            jobs.append(
                {
                    "job_id": enqueue_result.job_id,
                    "repo_id": repo_id,
                    "job_type": spec.job_type.value,
                    "deduplicated": enqueue_result.deduplicated,
                }
            )
            if not enqueue_result.deduplicated:
                created_job_ids.append(enqueue_result.job_id)
            context.job_store.subscribe_workflow(
                workflow_run_id,
                enqueue_result.job_id,
                is_root=True,
                owns_job=not enqueue_result.deduplicated,
            )
            if not enqueue_result.deduplicated:
                context.job_store.bind_run(enqueue_result.job_id, workflow_run_id)
                signal_job_ids.append(enqueue_result.job_id)
    except Exception as exc:
        aborted_job_ids: list[int] = []
        try:
            aborted_job_ids.extend(
                context.job_store.cancel_workflow_subscription(workflow_run_id)
            )
        except Exception as abort_exc:
            structlog.get_logger(__name__).warning(
                "dashboard.workflow_abort_failed",
                workflow_run_id=workflow_run_id,
                error_type=type(abort_exc).__name__,
            )
        for job_id in created_job_ids:
            try:
                if context.job_store.request_cancel(job_id):
                    aborted_job_ids.append(job_id)
            except Exception as abort_exc:
                structlog.get_logger(__name__).warning(
                    "dashboard.workflow_job_abort_failed",
                    workflow_run_id=workflow_run_id,
                    job_id=job_id,
                    error_type=type(abort_exc).__name__,
                )
        failed_details = {
            **details,
            "job_ids": [item["job_id"] for item in jobs],
            "scheduling_failed": True,
            "scheduling_error_type": type(exc).__name__,
            "aborted_job_ids": sorted(set(aborted_job_ids)),
        }
        sync_state_store.update_run(
            workflow_run_id,
            status="failed",
            progress={
                "selected_repositories": len(repo_ids),
                "scheduled_repositories": len(jobs),
                "scheduling_failed": True,
            },
            error_message="workflow scheduling failed",
            finished=True,
        )
        context.store.finish_sync_run(
            sync_id=workflow_run_id,
            status="failed",
            objects_checked=len(jobs),
            objects_created=0,
            objects_updated=0,
            objects_deleted=0,
            objects_skipped=max(0, len(repo_ids) - len(jobs)),
            errors_count=1,
            summary=(
                f"Workflow-Einplanung fehlgeschlagen: {len(jobs)}/{len(repo_ids)} Jobs erstellt"
            ),
            details=failed_details,
        )
        return (
            {
                "error": "workflow scheduling failed",
                "message": "Der Lauf wurde dauerhaft als fehlgeschlagen erfasst; bereits eingeplante Jobs wurden abgebrochen.",
                "status": "failed",
                "run_id": workflow_run_id,
                "status_url": f"/api/workflow/runs/{workflow_run_id}",
                "jobs": jobs,
                "aborted_job_ids": sorted(set(aborted_job_ids)),
            },
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    details = {**details, "job_ids": [item["job_id"] for item in jobs]}
    context.store.finish_sync_run(
        sync_id=workflow_run_id,
        status="queued",
        objects_checked=len(jobs),
        objects_created=0,
        objects_updated=0,
        objects_deleted=0,
        objects_skipped=0,
        summary=f"{len(jobs)} Workflow-Jobs eingeplant",
        details=details,
        terminal=False,
    )
    for job_id in signal_job_ids:
        try:
            context.signal_queue.signal(job_id)
        except Exception as exc:
            structlog.get_logger(__name__).warning(
                "dashboard.workflow_signal_failed",
                job_id=job_id,
                error=str(exc),
            )
    _record_admin_audit(
        context,
        actor=actor,
        action="start",
        target=f"workflow:{workflow_run_id}",
        before={"exists": False},
        after={
            "exists": True,
            "status": "queued",
            "repo_ids": repo_ids,
            "mode": mode,
            "scope": scope,
            "trigger": "manual",
            "job_ids": [item["job_id"] for item in jobs],
        },
        result="success",
        status=HTTPStatus.ACCEPTED,
    )
    return (
        {
            "status": "queued",
            "run_id": workflow_run_id,
            "status_url": f"/api/workflow/runs/{workflow_run_id}",
            "scope": scope,
            "mode": mode,
            "selected_repo_ids": repo_ids,
            "create_dataset": create_dataset,
            "sync_openwebui": sync_openwebui,
            "trigger": "manual",
            "jobs": jobs,
        },
        HTTPStatus.ACCEPTED,
    )


def _handle_workflow_run_status(
    context: DashboardContext,
    workflow_run_id: str,
) -> tuple[dict[str, Any], HTTPStatus]:
    parent = context.store.get_sync_run(workflow_run_id)
    if parent is None or (parent.get("details") or {}).get("kind") != "workflow_parent":
        return {"error": "workflow run not found"}, HTTPStatus.NOT_FOUND
    if context.job_store is None:
        return {"error": "job store unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    details = dict(parent.get("details") or {})
    root_jobs = [
        job
        for job_id in details.get("job_ids") or []
        if (job := context.job_store.get(int(job_id))) is not None
    ]
    correlation_run_ids = {workflow_run_id}
    correlation_run_ids.update(
        str(job.run_id) for job in root_jobs if str(job.run_id or "").strip()
    )
    subscribed_jobs = context.job_store.workflow_jobs(workflow_run_id)
    jobs = subscribed_jobs or root_jobs

    sync_state_store = SyncStateStore(context.job_store.session_factory)
    child_runs_by_id: dict[str, Any] = {}
    for run_id in correlation_run_ids:
        for child_run in sync_state_store.list_runs(parent_run_id=run_id, limit=1000):
            child_runs_by_id[str(child_run.id)] = child_run
    child_runs = list(child_runs_by_id.values())
    cleanup_rows = context.job_store.workflow_cleanup_rows(workflow_run_id)

    statuses = [str(job.status) for job in jobs]
    statuses.extend(_workflow_cleanup_status(row.status) for row in cleanup_rows)
    scheduling_failed = bool(details.get("scheduling_failed"))
    if scheduling_failed:
        status = str(parent.get("status") or "failed")
        refreshed_parent = parent
    else:
        status = context.job_store.refresh_workflow_parent(workflow_run_id)
        refreshed_parent = context.store.get_sync_run(workflow_run_id) or parent
    refreshed_details = dict(refreshed_parent.get("details") or {})
    details = refreshed_details
    admin_paused = bool(refreshed_details.get("admin_paused"))
    completed = sum(
        value in {JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value, JobStatus.DEAD.value}
        for value in statuses
    )
    total = len(statuses)
    partial_jobs = 0.0
    for repo_id in details.get("repo_ids") or []:
        repo_jobs = [job for job in jobs if str(job.repo_id or "") == str(repo_id)]
        active_file_job = any(
            str(job.status) not in WORKFLOW_TERMINAL_JOB_STATUSES
            and _workflow_job_phase(str(job.job_type)) == "files"
            for job in repo_jobs
        )
        if not active_file_job:
            continue
        child_progress = _workflow_child_run_progress(
            [run for run in child_runs if str(run.repo_id or "") == str(repo_id)]
        )
        if child_progress is not None:
            partial_jobs += float(child_progress["percent"]) / 100.0
    progress = {
        "completed": completed,
        "total": total,
        "percent": round(min(float(total), completed + partial_jobs) * 100 / total, 2)
        if total
        else 0.0,
    }
    job_payloads = [_workflow_job_payload(job) for job in jobs]
    phases = _workflow_phases(jobs, cleanup_rows)
    phase = _current_workflow_phase(phases)
    libraries = _workflow_run_libraries(
        context,
        details.get("repo_ids") or [],
        jobs,
        child_runs,
        run_paused=admin_paused,
    )
    payload = {
        "run_id": workflow_run_id,
        "status": status,
        "progress": progress,
        "phase": phase,
        "phases": phases,
        "libraries": libraries,
        "paused": status == "paused",
        "mode": details.get("mode"),
        "scope": details.get("scope"),
        "trigger": details.get("trigger"),
        "selected_repo_ids": details.get("repo_ids") or [],
        "jobs": job_payloads,
        "sync_runs": [
            {
                "run_id": run.id,
                "repo_id": run.repo_id,
                "mode": run.mode,
                "status": run.status,
                "progress": dict(run.progress or {}),
                "error_message": run.error_message,
            }
            for run in child_runs
        ],
        "cleanup_outbox": [
            {
                "id": int(row.id),
                "repo_id": row.repo_id,
                "target_type": row.target_type,
                "status": row.status,
                "attempts": int(row.attempts),
                "error_message": row.error_message,
            }
            for row in cleanup_rows
        ],
        "started_at": parent.get("started_at"),
        "finished_at": refreshed_parent.get("ended_at"),
        "capabilities": {
            "run_actions": (
                []
                if scheduling_failed
                else _workflow_run_actions(
                    status,
                    enabled=_workflow_control_available(context),
                )
            )
        },
    }
    terminal_statuses = {"succeeded", "failed", "cancelled", "stopped"}
    if status in terminal_statuses and parent.get("status") != status:
        context.store.finish_sync_run(
            sync_id=workflow_run_id,
            status=status,
            objects_checked=len(jobs),
            objects_created=0,
            objects_updated=0,
            objects_deleted=0,
            objects_skipped=0,
            errors_count=sum(str(job.status) == JobStatus.DEAD.value for job in jobs),
            summary=f"Workflow {status}: {completed}/{len(jobs)} Jobs abgeschlossen",
            details=details,
        )
        refreshed = context.store.get_sync_run(workflow_run_id)
        payload["finished_at"] = refreshed.get("ended_at") if refreshed is not None else None
    return payload, HTTPStatus.OK


def _handle_workflow_run_action(
    context: DashboardContext,
    workflow_run_id: str,
    action: str,
    payload: dict[str, Any],
    *,
    actor: str | None,
) -> tuple[dict[str, Any], HTTPStatus]:
    resolved_actor = actor or "unknown"
    target = f"workflow:{workflow_run_id}"
    if action not in WORKFLOW_RUN_ACTIONS:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action or "unknown",
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.NOT_FOUND,
        )
        return {"error": "not found"}, HTTPStatus.NOT_FOUND
    parent = context.store.get_sync_run(workflow_run_id)
    if parent is None or (parent.get("details") or {}).get("kind") != "workflow_parent":
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=None,
            after=None,
            result="failed",
            status=HTTPStatus.NOT_FOUND,
        )
        return {"error": "workflow run not found"}, HTTPStatus.NOT_FOUND
    if context.job_store is None or context.signal_queue is None:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before={"status": parent.get("status")},
            after={"status": parent.get("status")},
            result="failed",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
        return {"error": "job queue unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE
    before = {
        "status": parent.get("status"),
        "details": dict(parent.get("details") or {}),
    }
    current_payload, _ = _handle_workflow_run_status(context, workflow_run_id)
    current_status = str(current_payload.get("status") or parent.get("status") or "")
    before["status"] = current_status
    allowed_actions = _workflow_run_actions(current_status)
    if action not in allowed_actions:
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=before,
            result="failed",
            status=HTTPStatus.CONFLICT,
        )
        return (
            {
                "error": "invalid workflow transition",
                "message": (
                    f"Aktion {action} ist für Workflow-Status {current_status} nicht zulässig."
                ),
                "status": current_status,
                "allowed_actions": allowed_actions,
            },
            HTTPStatus.CONFLICT,
        )
    if action in {"stop", "cancel"} and payload.get("confirm") != "STOP":
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=before,
            result="failed",
            status=HTTPStatus.BAD_REQUEST,
        )
        return (
            {
                "error": "confirmation required",
                "message": "Stop oder Abbruch erfordert confirm=STOP.",
            },
            HTTPStatus.BAD_REQUEST,
        )
    intended_status = {
        "pause": "paused",
        "resume": "queued",
        "stop": "stopped",
        "cancel": "cancelled",
        "retry": "queued",
    }[action]
    _record_admin_audit(
        context,
        actor=resolved_actor,
        action=action,
        target=target,
        before=before,
        after={"status": intended_status},
        result="attempted",
        status=HTTPStatus.ACCEPTED,
    )
    changed: list[int] = []
    signal_warnings: list[int] = []
    try:
        if action == "pause":
            changed = context.job_store.request_workflow_pause(workflow_run_id)
        elif action == "resume":
            changed = context.job_store.resume_workflow_pause(workflow_run_id)
        elif action in {"stop", "cancel"}:
            changed = (
                context.job_store.stop_workflow_subscription(workflow_run_id)
                if action == "stop"
                else context.job_store.cancel_workflow_subscription(workflow_run_id)
            )
        else:
            for job_id in context.job_store.resume_workflow_subscription(workflow_run_id):
                retried = context.job_store.retry(job_id)
                job = context.job_store.get(job_id)
                if retried or (
                    job is not None
                    and str(job.status)
                    in {JobStatus.QUEUED.value, JobStatus.RETRYING.value}
                ):
                    changed.append(job_id)
            context.job_store.refresh_workflow_parent(workflow_run_id)
        if action in {"resume", "retry"}:
            for job_id in changed:
                try:
                    context.signal_queue.signal(job_id)
                except Exception as exc:
                    signal_warnings.append(job_id)
                    structlog.get_logger(__name__).warning(
                        "dashboard.workflow_signal_failed",
                        job_id=job_id,
                        error_type=type(exc).__name__,
                    )
        after_parent = context.store.get_sync_run(workflow_run_id) or {}
        after = {
            "status": after_parent.get("status", intended_status),
            "changed_job_ids": changed,
            "signal_warning_job_ids": signal_warnings,
        }
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=after,
            result="success",
            status=HTTPStatus.ACCEPTED,
        )
        response: dict[str, Any] = {
            "run_id": workflow_run_id,
            "action": action,
            "status": after["status"],
            "changed_job_ids": changed,
        }
        if action in {"stop", "cancel"}:
            response["detached"] = True
        if signal_warnings:
            response["signal_warning_job_ids"] = signal_warnings
        return response, HTTPStatus.ACCEPTED
    except Exception as exc:
        after_parent = context.store.get_sync_run(workflow_run_id) or {}
        actual_after = {"status": after_parent.get("status")}
        _record_admin_audit(
            context,
            actor=resolved_actor,
            action=action,
            target=target,
            before=before,
            after=actual_after,
            result="partial" if actual_after.get("status") != before.get("status") else "failed",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_type=type(exc).__name__,
        )
        raise


def _aggregate_workflow_status(statuses: list[str]) -> str:
    if not statuses:
        return "queued"
    if any(status == JobStatus.RUNNING.value for status in statuses):
        return "running"
    if any(status == JobStatus.RETRYING.value for status in statuses):
        return "retrying"
    if any(status == JobStatus.QUEUED.value for status in statuses):
        return "queued"
    if any(status == JobStatus.DEAD.value for status in statuses):
        return "failed"
    if all(status == JobStatus.CANCELLED.value for status in statuses):
        return "cancelled"
    if all(status in {JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value} for status in statuses):
        return "succeeded"
    return "queued"


def _workflow_sync_run_status(status: str) -> str:
    if status == "failed":
        return JobStatus.DEAD.value
    if status == "cancelled":
        return JobStatus.CANCELLED.value
    if status == "succeeded":
        return JobStatus.SUCCEEDED.value
    if status == "retrying":
        return JobStatus.RETRYING.value
    return JobStatus.RUNNING.value


def _workflow_cleanup_status(status: str) -> str:
    if status == "dead":
        return JobStatus.DEAD.value
    if status in {"completed", "cancelled", "superseded"}:
        return JobStatus.SUCCEEDED.value
    return JobStatus.RETRYING.value


def _cleanup_outbox_payload(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "repo_id": row.repo_id,
        "run_id": row.run_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "dataset_id": row.dataset_id,
        "action": row.action,
        "status": row.status,
        "attempts": int(row.attempts),
        "run_after": row.run_after.isoformat() if row.run_after is not None else None,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at is not None else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at is not None else None,
    }


WORKFLOW_PHASE_DEFINITIONS: list[tuple[str, str]] = [
    ("discovery", "Bibliotheken erkennen"),
    ("dataset", "RAGFlow-Dataset vorbereiten"),
    ("files", "Dateien synchronisieren"),
    ("parsing", "Dokumente parsen"),
    ("cleanup", "Bereinigung"),
    ("openwebui", "OpenWebUI synchronisieren"),
]

WORKFLOW_JOB_PHASES = {
    JobType.DISCOVER_LIBRARIES.value: "discovery",
    JobType.ENSURE_RAGFLOW_DATASET.value: "dataset",
    JobType.REFRESH_DATASET_SETTINGS.value: "dataset",
    JobType.SYNC_LIBRARY_FULL.value: "files",
    JobType.SYNC_LIBRARY_DELTA.value: "files",
    JobType.CLASSIFY_FILE.value: "files",
    JobType.PREPARE_INGESTION_ARTIFACT.value: "files",
    JobType.UPLOAD_FILE.value: "files",
    JobType.DELETE_FILE.value: "files",
    JobType.RECONCILE_LIBRARY.value: "files",
    JobType.RECONCILE_RAGFLOW_DATASET.value: "files",
    JobType.PARSE_DOCUMENTS.value: "parsing",
    JobType.REPARSE_DOCUMENTS.value: "parsing",
    JobType.CHECK_PARSE_STATUS.value: "parsing",
    JobType.PROCESS_CLEANUP_OUTBOX.value: "cleanup",
    JobType.SYNC_OPENWEBUI.value: "openwebui",
}

WORKFLOW_TERMINAL_JOB_STATUSES = {
    JobStatus.SUCCEEDED.value,
    JobStatus.CANCELLED.value,
    JobStatus.DEAD.value,
}


def _workflow_job_phase(job_type: str) -> str:
    return WORKFLOW_JOB_PHASES.get(str(job_type), "files")


def _workflow_phases(jobs: list[Any], cleanup_rows: list[Any]) -> list[dict[str, Any]]:
    jobs_by_phase: dict[str, list[Any]] = {}
    for job in jobs:
        jobs_by_phase.setdefault(_workflow_job_phase(str(job.job_type)), []).append(job)
    cleanup_statuses = [_workflow_cleanup_status(str(row.status)) for row in cleanup_rows]
    phases: list[dict[str, Any]] = []
    for name, label in WORKFLOW_PHASE_DEFINITIONS:
        phase_jobs = jobs_by_phase.get(name, [])
        statuses = [str(job.status) for job in phase_jobs]
        if name == "cleanup":
            statuses.extend(cleanup_statuses)
        if not statuses:
            continue
        completed = sum(status in WORKFLOW_TERMINAL_JOB_STATUSES for status in statuses)
        total = len(statuses)
        paused = bool(phase_jobs) and all(
            (
                str(job.status) in WORKFLOW_TERMINAL_JOB_STATUSES
                or (
                    job.pause_requested_at is not None
                    and job.cancel_requested_at is None
                )
            )
            for job in phase_jobs
        ) and any(
            job.pause_requested_at is not None and job.cancel_requested_at is None
            for job in phase_jobs
        )
        phases.append(
            {
                "name": name,
                "label": label,
                "status": _workflow_phase_status(statuses, paused=paused),
                "percent": round(completed * 100 / total, 2) if total else 0.0,
                "completed": completed,
                "total": total,
            }
        )
    return phases


def _workflow_phase_status(statuses: list[str], *, paused: bool) -> str:
    if paused:
        return "paused"
    if any(status == JobStatus.RUNNING.value for status in statuses):
        return "running"
    if any(status == JobStatus.RETRYING.value for status in statuses):
        return "retrying"
    if any(status == JobStatus.QUEUED.value for status in statuses):
        return "queued"
    if any(status == JobStatus.DEAD.value for status in statuses):
        return "failed"
    if all(status == JobStatus.CANCELLED.value for status in statuses):
        return "cancelled"
    return "succeeded"


def _current_workflow_phase(phases: list[dict[str, Any]]) -> str | None:
    for phase in phases:
        if phase["status"] in {"running", "retrying", "queued", "paused"}:
            return str(phase["name"])
    for phase in phases:
        if phase["status"] == "failed":
            return str(phase["name"])
    return str(phases[-1]["name"]) if phases else None


def _workflow_run_libraries(
    context: DashboardContext,
    repo_ids: list[str],
    jobs: list[Any],
    child_runs: list[Any],
    *,
    run_paused: bool,
) -> list[dict[str, Any]]:
    normalized_repo_ids = list(
        dict.fromkeys(str(repo_id) for repo_id in repo_ids if str(repo_id))
    )
    with context.store.session_factory() as session:
        names = {
            str(row.repo_id): str(row.name)
            for row in session.scalars(
                select(Library).where(Library.repo_id.in_(normalized_repo_ids))
            ).all()
        }
    parsing_by_repo = _workflow_parsing_by_repo(context, normalized_repo_ids)
    rows: list[dict[str, Any]] = []
    for repo_id in normalized_repo_ids:
        repo_jobs = [job for job in jobs if str(job.repo_id or "") == repo_id]
        statuses = [str(job.status) for job in repo_jobs]
        completed = sum(status in WORKFLOW_TERMINAL_JOB_STATUSES for status in statuses)
        total = len(statuses)
        job_progress = {
            "completed": completed,
            "total": total,
            "percent": round(completed * 100 / total, 2) if total else 0.0,
        }
        paused = run_paused or any(
            job.pause_requested_at is not None and job.cancel_requested_at is None
            for job in repo_jobs
        )
        repo_child_runs = [run for run in child_runs if str(run.repo_id or "") == repo_id]
        child_progress = _workflow_child_run_progress(repo_child_runs)
        paused = paused or any(
            bool((run.progress or {}).get("admin_paused")) for run in repo_child_runs
        )
        if statuses:
            status = "paused" if paused else _aggregate_workflow_status(statuses)
        elif repo_child_runs:
            status = str(repo_child_runs[0].status)
        else:
            status = "queued"
        phase = next(
            (
                _workflow_job_phase(str(job.job_type))
                for job in repo_jobs
                if str(job.status) not in WORKFLOW_TERMINAL_JOB_STATUSES
            ),
            None,
        )
        if phase is None:
            phase = next(
                (
                    str((run.progress or {}).get("phase"))
                    for run in repo_child_runs
                    if (run.progress or {}).get("phase")
                ),
                _workflow_job_phase(str(repo_jobs[-1].job_type)) if repo_jobs else None,
            )
        active_file_job = any(
            str(job.status) not in WORKFLOW_TERMINAL_JOB_STATUSES
            and _workflow_job_phase(str(job.job_type)) == "files"
            for job in repo_jobs
        )
        displayed_progress = (
            child_progress if active_file_job and child_progress is not None else job_progress
        )
        rows.append(
            {
                "repo_id": repo_id,
                "name": names.get(repo_id, repo_id),
                "status": status,
                "paused": paused,
                "phase": phase,
                "progress": displayed_progress,
                "job_progress": job_progress,
                "file_progress": child_progress,
                "parsing": parsing_by_repo.get(repo_id, _empty_parsing_progress()),
            }
        )
    return rows


def _workflow_child_run_progress(child_runs: list[Any]) -> dict[str, int | float] | None:
    active_candidates = [
        run
        for run in child_runs
        if str(run.status) not in {"succeeded", "failed", "cancelled", "stopped"}
        and _workflow_run_has_file_progress(run)
    ]
    terminal_candidates = [
        run
        for run in child_runs
        if str(run.status) in {"succeeded", "failed", "cancelled", "stopped"}
        and _workflow_run_has_file_progress(run)
    ]
    candidates = active_candidates or terminal_candidates
    if not candidates:
        return None
    run = max(
        candidates,
        key=lambda item: (
            item.started_at.timestamp() if getattr(item, "started_at", None) else 0.0
        ),
    )
    raw = dict(run.progress or {})
    total = max(0, int(raw.get("total", raw.get("files_total", raw.get("changes", 0))) or 0))
    completed = max(
        0,
        int(
            raw.get(
                "completed",
                raw.get("files_processed", raw.get("processed", 0)),
            )
            or 0
        ),
    )
    completed = min(completed, total) if total else completed
    raw_percent = raw.get("percent")
    try:
        percent = float(raw_percent) if raw_percent is not None else 0.0
    except (TypeError, ValueError):
        percent = 0.0
    if raw_percent is None and total:
        percent = completed * 100 / total
    return {
        "completed": completed,
        "total": total,
        "percent": round(max(0.0, min(100.0, percent)), 2),
    }


def _workflow_run_has_file_progress(run: Any) -> bool:
    progress = getattr(run, "progress", None)
    return isinstance(progress, dict) and bool(
        {"total", "files_total", "changes"}.intersection(progress)
    )


def _workflow_job_payload(job: Any) -> dict[str, Any]:
    status = str(job.status)
    paused = bool(
        job.pause_requested_at is not None
        and job.cancel_requested_at is None
        and status not in WORKFLOW_TERMINAL_JOB_STATUSES
    )
    return {
        "job_id": int(job.id),
        "job_type": str(job.job_type),
        "repo_id": job.repo_id,
        "status": status,
        "effective_status": "paused" if paused else status,
        "phase": _workflow_job_phase(str(job.job_type)),
        "percent": 100.0 if status in WORKFLOW_TERMINAL_JOB_STATUSES else 0.0,
        "paused": paused,
        "attempts": int(job.attempts),
        "max_attempts": int(job.max_attempts),
        "error": job.error_message,
        "pause_requested_at": (
            job.pause_requested_at.isoformat() if job.pause_requested_at else None
        ),
        "cancel_requested_at": (
            job.cancel_requested_at.isoformat() if job.cancel_requested_at else None
        ),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _workflow_options(context: DashboardContext) -> dict[str, Any]:
    return {
        "default_scope": "/",
        "openwebui_enabled": context.openwebui_sync_service is not None,
        "openwebui_sync_mode": context.settings.openwebui_effective_sync_mode,
        "openwebui_create_tools": context.settings.openwebui_create_tools,
        "openwebui_create_pipes": context.settings.openwebui_create_pipes,
    }


def _visible_workflow_libraries(context: DashboardContext) -> list[dict[str, Any]]:
    if context.orchestrator is None:
        return []
    stored_libraries, stored_mappings = _stored_workflow_state(context)
    rows = []
    for raw in context.orchestrator.admin_client.iter_libraries():
        library = normalize_library(raw)
        skipped, reason = should_skip_library(
            library,
            skip_encrypted=context.orchestrator.skip_encrypted_libraries,
            skip_virtual=context.orchestrator.skip_virtual_repos,
        )
        stored = stored_libraries.get(library.repo_id, {})
        mapping = stored_mappings.get(library.repo_id, {})
        rows.append(
            {
                "repo_id": library.repo_id,
                "name": library.name,
                "owner_email": library.owner_email,
                "encrypted": library.encrypted,
                "virtual": library.virtual,
                "seafile_mtime": library.seafile_mtime,
                "head_commit_id": library.head_commit_id,
                "last_synced_commit_id": stored.get("last_synced_commit_id"),
                "status": f"skipped:{reason}" if skipped else stored.get("status", "visible"),
                "selectable": not skipped,
                "skip_reason": reason,
                "ragflow_dataset_id": stored.get("ragflow_dataset_id"),
                "ragflow_dataset_name": stored.get("ragflow_dataset_name"),
                "last_error": stored.get("last_error"),
                "openwebui": {
                    "sync_status": mapping.get("sync_status", "not_created"),
                    "ragflow_chat_id": mapping.get("ragflow_chat_id"),
                    "openwebui_tool_id": mapping.get("openwebui_tool_id"),
                    "openwebui_pipe_id": mapping.get("openwebui_pipe_id"),
                    "openwebui_model_name": mapping.get("openwebui_model_name"),
                    "last_error": mapping.get("last_error"),
                },
            }
        )
    repo_ids = [str(item["repo_id"]) for item in rows]
    controls = _admin_control_store(context).libraries(repo_ids)
    parsing_by_repo = _workflow_parsing_by_repo(context, repo_ids)
    for item in rows:
        repo_id = str(item["repo_id"])
        control_payload = controls[repo_id].to_payload()
        item["admin_state"] = control_payload["state"]
        item["admin_enabled"] = control_payload["enabled"]
        item["admin_paused"] = control_payload["paused"]
        item["admin_updated_at"] = control_payload["updated_at"]
        item["admin_control"] = control_payload
        item["parsing"] = parsing_by_repo.get(repo_id, _empty_parsing_progress())
    return sorted(rows, key=lambda item: str(item["name"]).lower())


def _empty_parsing_progress() -> dict[str, int | float]:
    return {
        "tracked": 0,
        "total": 0,
        "done": 0,
        "completed": 0,
        "pending": 0,
        "running": 0,
        "failed": 0,
        "percent": 0.0,
    }


def _workflow_parsing_by_repo(
    context: DashboardContext,
    repo_ids: list[str] | set[str] | tuple[str, ...],
) -> dict[str, dict[str, int | float]]:
    normalized = list(dict.fromkeys(str(value) for value in repo_ids if str(value)))
    if not normalized:
        return {}
    with context.store.session_factory() as session:
        rows = session.execute(
            select(
                FileDocumentVersion.repo_id,
                FileDocumentVersion.file_id,
                FileDocumentVersion.id,
                FileDocumentVersion.state,
            )
            .where(FileDocumentVersion.repo_id.in_(normalized))
            .order_by(
                FileDocumentVersion.repo_id,
                FileDocumentVersion.file_id,
                FileDocumentVersion.id.desc(),
            )
        ).all()
    latest: dict[tuple[str, int], str] = {}
    for repo_id, file_id, _version_id, state in rows:
        latest.setdefault((str(repo_id), int(file_id)), str(state or "unknown"))
    result = {repo_id: _empty_parsing_progress() for repo_id in normalized}
    for (repo_id, _file_id), state in latest.items():
        counters = result.setdefault(repo_id, _empty_parsing_progress())
        counters["tracked"] += 1
        counters["total"] += 1
        if state in {"current", "superseded"}:
            counters["done"] += 1
            counters["completed"] += 1
        elif state == "dead":
            counters["failed"] += 1
        else:
            counters["pending"] += 1
            if state in {"uploaded", "parsing", "retryable_failed"}:
                counters["running"] += 1
    for counters in result.values():
        total = int(counters["total"])
        counters["percent"] = round(int(counters["done"]) * 100 / total, 2) if total else 0.0
    return result


def _stored_workflow_state(
    context: DashboardContext,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    with context.store.session_factory() as session:
        libraries = {
            row.repo_id: {
                "status": row.status,
                "last_synced_commit_id": row.last_synced_commit_id,
                "ragflow_dataset_id": row.ragflow_dataset_id,
                "ragflow_dataset_name": row.ragflow_dataset_name,
                "last_error": row.last_error,
            }
            for row in session.scalars(select(Library)).all()
        }
        mappings = {
            row.repo_id: {
                "sync_status": row.sync_status,
                "ragflow_chat_id": row.ragflow_chat_id,
                "openwebui_tool_id": row.openwebui_tool_id,
                "openwebui_pipe_id": row.openwebui_pipe_id,
                "openwebui_model_name": row.openwebui_model_name,
                "last_error": row.last_error,
            }
            for row in session.scalars(select(OpenWebUIDatasetMapping)).all()
        }
    return libraries, mappings


def _workflow_repo_ids(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("repo_ids")
    if not isinstance(raw, list):
        raise ValueError("repo_ids muss eine Liste sein.")
    repo_ids: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in repo_ids:
            repo_ids.append(text)
    if not repo_ids:
        raise ValueError("Mindestens eine Bibliothek muss ausgewählt sein.")
    if len(repo_ids) > 200:
        raise ValueError("Maximal 200 Bibliotheken pro Dashboard-Lauf.")
    return repo_ids


def _workflow_bool(payload: dict[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on"}
    return bool(value)


def _workflow_scope(payload: dict[str, Any]) -> str:
    scope = str(payload.get("scope") or "/").strip() or "/"
    if len(scope) > 512:
        raise ValueError("scope ist zu lang.")
    if not scope.startswith("/"):
        raise ValueError("scope muss mit / beginnen.")
    return scope


def _workflow_mode(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode") or "delta").strip().lower()
    if mode not in {"delta", "full", "reconcile"}:
        raise ValueError("mode muss delta, full oder reconcile sein.")
    return mode


def _repo_ids_with_dataset(context: DashboardContext, repo_ids: list[str]) -> set[str]:
    with context.store.session_factory() as session:
        rows = session.scalars(
            select(Library)
            .where(Library.repo_id.in_(repo_ids))
            .where(Library.status == "active")
            .where(Library.ragflow_dataset_id.is_not(None))
        ).all()
        return {row.repo_id for row in rows}


def _summary_payload(summary: Any) -> dict[str, Any]:
    raw = getattr(summary, "__dict__", {})
    return {str(key): value for key, value in raw.items()}


def _workflow_result_status(
    results: list[dict[str, Any]],
    openwebui_result: dict[str, Any] | None,
) -> str:
    failed = sum(1 for item in results if item.get("status") == "failed")
    openwebui_failed = bool(openwebui_result and openwebui_result.get("status") == "failed")
    if failed and failed < len(results):
        return "partial"
    if failed or openwebui_failed:
        return "failed"
    return "succeeded"


def _handle_openwebui_query(
    context: DashboardContext,
    payload: dict[str, Any],
    authorization: str | None,
) -> dict[str, Any]:
    _require_proxy_secret(context.settings, authorization)
    artifact_id = _required_text(payload, "artifact_id")
    dataset_id = _required_text(payload, "dataset_id")
    question = _required_text(payload, "question")
    top_k = _bounded_top_k(payload.get("top_k"))
    mapping = _load_mapping(context.store, dataset_id=dataset_id, tool_id=artifact_id)
    _require_openwebui_dataset_access(context, payload, mapping, dataset_id)
    ragflow = RAGFlowClient(
        context.settings.ragflow_internal_url or context.settings.ragflow_base_url,
        context.settings.ragflow_api_key,
        timeout=context.settings.openwebui_request_timeout_seconds,
        verify=context.settings.ragflow_httpx_verify,
    )
    try:
        search_template = resolve_search_template(ragflow, config_from_settings(context.settings))
        result = ragflow.retrieve_chunks(
            dataset_id=dataset_id,
            question=question,
            retrieval_options=search_template.settings.to_retrieval_options(
                requested_results=top_k,
            ),
        )
    finally:
        ragflow.close()
    sources = normalize_sources(
        result,
        settings=context.settings,
        dataset_id=dataset_id,
        dataset_name=mapping.ragflow_dataset_name,
        files_by_document_id=_files_by_document_id(context.store, mapping.repo_id),
        question=question,
        answer="",
    )
    return {
        "answer": _sources_markdown(sources, context.settings),
        "sources": sources,
        "source_markdown": _sources_markdown(sources, context.settings),
        "retrieval_only": True,
        "citations_emitted": True,
        "diagnostics": {
            "answer_path": "",
            "reference_path": "retrieval.chunks",
            "provider": "ragflow",
            "source_count_after_dedup": len(sources),
            "top_k": top_k,
            **search_template.diagnostics(),
        },
    }


def _handle_openwebui_chat(
    context: DashboardContext,
    payload: dict[str, Any],
    authorization: str | None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    _require_proxy_secret(context.settings, authorization)
    artifact_id = _required_text(payload, "artifact_id")
    dataset_id = _required_text(payload, "dataset_id")
    chat_id = _required_text(payload, "chat_id")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")
    top_k = _bounded_top_k(payload.get("top_k"))
    mapping = _load_mapping(
        context.store,
        dataset_id=dataset_id,
        chat_id=chat_id,
        pipe_id=artifact_id,
    )
    _require_openwebui_dataset_access(context, payload, mapping, dataset_id)
    ragflow = RAGFlowClient(
        context.settings.ragflow_internal_url or context.settings.ragflow_base_url,
        context.settings.ragflow_api_key,
        timeout=context.settings.openwebui_request_timeout_seconds,
        verify=context.settings.ragflow_httpx_verify,
    )
    try:
        files_by_document_id = _files_by_document_id(context.store, mapping.repo_id)
        question = _last_user_message(messages)
        search_template = resolve_search_template(ragflow, config_from_settings(context.settings))
        try:
            result = ragflow.chat_completion(
                chat_id=chat_id,
                messages=messages,
                model=str(payload.get("model") or "model"),
                stream=True,
            )
        except (ApiError, httpx.RequestError) as exc:
            if not question:
                raise
            diagnostics = _chat_completion_fallback_diagnostics(
                exc,
                dataset_id=dataset_id,
                chat_id=chat_id,
                question=question,
                top_k=top_k,
                started_at=started_at,
            )
            structlog.get_logger(__name__).warning(
                "openwebui.chat_completion_failed_fallback_retrieval",
                **diagnostics,
            )
            sources = _retrieve_openwebui_sources(
                ragflow,
                context=context,
                mapping=mapping,
                dataset_id=dataset_id,
                question=question,
                top_k=top_k,
                files_by_document_id=files_by_document_id,
                search_template=search_template,
            )
            diagnostics["reference_path"] = "retrieval.chunks" if sources else ""
            diagnostics["reference_path_detected"] = "retrieval.chunks" if sources else None
            diagnostics["source_count_after_dedup"] = len(sources)
            diagnostics["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
            diagnostics.update(search_template.diagnostics())
            return {
                "answer": "",
                "sources": sources,
                "source_markdown": _sources_markdown(sources, context.settings),
                "retrieval_only": True,
                "citations_emitted": False,
                "diagnostics": diagnostics,
            }
        answer_result = extract_answer_result(result)
        sources = normalize_sources(
            result,
            settings=context.settings,
            dataset_id=dataset_id,
            dataset_name=mapping.ragflow_dataset_name,
            files_by_document_id=files_by_document_id,
            question=question,
            answer=answer_result.answer,
        )
        if question:
            try:
                retrieval_sources = _retrieve_openwebui_sources(
                    ragflow,
                    context=context,
                    mapping=mapping,
                    dataset_id=dataset_id,
                    question=question,
                    top_k=top_k,
                    files_by_document_id=files_by_document_id,
                    search_template=search_template,
                )
            except ApiError as exc:
                structlog.get_logger(__name__).warning(
                    "openwebui.retrieval_source_enrichment_failed",
                    dataset_id=dataset_id,
                    chat_id=chat_id,
                    error=str(exc),
                )
            else:
                sources = _merge_sources(sources, retrieval_sources)
                sources = _filter_sources_for_requested_document(sources, question)
                sources = audit_rank_sources(
                    sources,
                    question=question,
                    answer=answer_result.answer,
                )
                sources = curate_sources_for_answer(sources, answer=answer_result.answer)
    finally:
        ragflow.close()
    l10n = localizer_for(context.settings)
    answer = annotate_answer_citations(_clean_answer_text(answer_result.answer), sources, language=l10n.language)
    diagnostics = _openwebui_audit_diagnostics(
        question=question,
        top_k=top_k,
        answer=answer,
        answer_origin=answer_result.origin if answer else "retrieval_only",
        answer_path=answer_result.path,
        reference_path=_reference_path_detected(result),
        sources=sources,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
    )
    diagnostics.update(search_template.diagnostics())
    return {
        "answer": answer,
        "sources": sources,
        "source_markdown": _sources_markdown(sources, context.settings),
        "retrieval_only": not bool(answer.strip()),
        "citations_emitted": False,
        "diagnostics": diagnostics,
    }


def _require_openwebui_dataset_access(
    context: DashboardContext,
    payload: dict[str, Any],
    mapping: OpenWebUIDatasetMapping,
    dataset_id: str,
) -> None:
    if not context.settings.openwebui_authz_enabled:
        return
    service = _access_control_service(context)
    if service is None:
        if context.settings.openwebui_authz_fail_closed:
            raise AuthzDeniedError("authz unavailable")
        return
    user = _user_identity_from_payload(payload.get("user"))
    decision = service.check_access(
        user,
        AuthzResource(repo_id=mapping.repo_id, ragflow_dataset_id=dataset_id),
        "search",
    )
    _log_authz_decision(
        user,
        AuthzResource(repo_id=mapping.repo_id, ragflow_dataset_id=dataset_id),
        "search",
        decision.to_payload(),
    )
    if decision.decision == "deny":
        raise AuthzDeniedError(decision.reason)


def _proxy_error_response(
    settings: Settings,
    path: str,
    exc: Exception,
) -> tuple[dict[str, str], HTTPStatus]:
    route = "Connector Proxy -> RAGFlow"
    target = safe_url_for_logs(settings.ragflow_internal_url or settings.ragflow_base_url)
    error_type = _proxy_error_type(exc)
    status = HTTPStatus.BAD_GATEWAY
    l10n = localizer_for(settings)
    message = l10n.text("openwebui_artifact.query_failed_return")
    if isinstance(exc, httpx.TimeoutException):
        message = l10n.text("openwebui_artifact.ragflow_timeout_return")
        status = HTTPStatus.GATEWAY_TIMEOUT
    elif isinstance(exc, ApiError):
        message = l10n.text("openwebui_artifact.proxy_http", status=exc.status_code or "API")
    elif isinstance(exc, httpx.ConnectError | httpx.RequestError):
        message = l10n.text("openwebui_artifact.proxy_unreachable_return")

    structlog.get_logger(__name__).warning(
        "openwebui.proxy_upstream_failed",
        path=path,
        route=route,
        target=target,
        error_type=error_type,
        hint="RAGFLOW_CA_BUNDLE prüfen, wenn dies ein TLS- oder Zertifikatsfehler ist.",
    )
    return {"error": "proxy request failed", "message": message}, status


def _reference_path_detected(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    for container_prefix, container in (("", result), ("data.", result.get("data"))):
        if not isinstance(container, dict):
            continue
        choices = container.get("choices")
        if isinstance(choices, list):
            for index, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict) and "reference" in message:
                    return f"{container_prefix}choices[{index}].message.reference"
                delta = choice.get("delta")
                if isinstance(delta, dict) and "reference" in delta:
                    return f"{container_prefix}choices[{index}].delta.reference"
        for key in ("reference", "references", "sources", "source_documents", "citations"):
            if key in container:
                return f"{container_prefix}{key}"
    return ""


def _proxy_error_type(exc: Exception) -> str:
    if isinstance(exc, ApiError):
        return f"HTTP_{exc.status_code or 'API_ERROR'}"
    return classify_httpx_error(exc)


def _chat_completion_fallback_diagnostics(
    exc: Exception,
    *,
    dataset_id: str,
    chat_id: str,
    question: str | None,
    top_k: int,
    started_at: float,
) -> dict[str, Any]:
    http_status = exc.status_code if isinstance(exc, ApiError) else None
    return {
        "query_id": _query_id(question),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "ragflow",
        "endpoint": "/api/v1/openai/{chat_id}/chat/completions",
        "http_status": http_status,
        "error_class": exc.__class__.__name__,
        "fallback": "retrieval",
        "fallback_reason": "chat_completion_failed",
        "chat_id_present": bool(chat_id),
        "dataset_id_present": bool(dataset_id),
        "answer_path": "",
        "reference_path": "",
        "answer_path_detected": None,
        "reference_path_detected": None,
        "retrieval_mode": "chat_failed_retrieval_fallback",
        "top_k": top_k,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "redacted_response_hint": _redacted_error_hint(exc),
    }


def _redacted_error_hint(exc: Exception) -> str:
    payload = exc.payload if isinstance(exc, ApiError) else None
    if isinstance(payload, dict):
        safe = {
            key: value
            for key, value in payload.items()
            if key in {"code", "message", "error", "detail", "status", "reason"}
            and isinstance(value, (str, int, float, bool))
        }
        if safe:
            return json.dumps(redact_mapping(safe), ensure_ascii=False)[:300]
    if isinstance(payload, str):
        parsed = _json_loads(payload)
        if isinstance(parsed, dict):
            status_code = exc.status_code if isinstance(exc, ApiError) else None
            return _redacted_error_hint(
                ApiError(str(exc), status_code=status_code, payload=parsed)
            )
        clean = " ".join(payload.split())
        if clean and len(clean) <= 180:
            return clean
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    if isinstance(exc, httpx.RequestError):
        return classify_httpx_error(exc)
    return ""


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except ValueError:
        return None


def _require_proxy_secret(settings: Settings, authorization: str | None) -> None:
    if not settings.openwebui_proxy_shared_secret:
        raise PermissionError("proxy secret is not configured")
    expected = f"Bearer {settings.openwebui_proxy_shared_secret}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise PermissionError("invalid proxy authorization")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value in (None, ""):
        raise ValueError(f"{key} is required")
    return str(value)


def _required_int(payload: dict[str, Any], key: str) -> int:
    raw = payload.get(key)
    if raw is None:
        raise ValueError(f"{key} is required")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} is required") from exc
    if value <= 0:
        raise ValueError(f"{key} is required")
    return value


def _last_user_message(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            text = "\n".join(part.strip() for part in parts if part.strip())
            if text:
                return text
    return None


def _bounded_top_k(value: Any, *, default: int = 8, maximum: int = 20) -> int:
    try:
        top_k = int(value or default)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, top_k))


def _retrieve_openwebui_sources(
    ragflow: RAGFlowClient,
    *,
    context: DashboardContext,
    mapping: OpenWebUIDatasetMapping,
    dataset_id: str,
    question: str,
    top_k: int,
    files_by_document_id: dict[str, dict[str, Any]],
    search_template: ResolvedSearchTemplate | None = None,
) -> list[dict[str, Any]]:
    resolved = search_template or resolve_search_template(
        ragflow,
        config_from_settings(context.settings),
    )
    retrieval_result = ragflow.retrieve_chunks(
        dataset_id=dataset_id,
        question=question,
        retrieval_options=resolved.settings.to_retrieval_options(
            requested_results=top_k,
        ),
    )
    return normalize_sources(
        retrieval_result,
        settings=context.settings,
        dataset_id=dataset_id,
        dataset_name=mapping.ragflow_dataset_name,
        files_by_document_id=files_by_document_id,
        question=question,
        answer="",
    )


def _merge_sources(
    primary: list[dict[str, Any]],
    additional: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in [*primary, *additional]:
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


def _source_key(source: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = source.get("source_metadata")
    if not isinstance(metadata, dict):
        metadata_items = source.get("metadata")
        metadata = metadata_items[0] if isinstance(metadata_items, list) and metadata_items else {}
    snippet = str(source.get("snippet") or source.get("text") or "")
    return (
        str(metadata.get("document_id") or source.get("name") or ""),
        str(metadata.get("chunk_id") or ""),
        str(metadata.get("page") or ""),
        " ".join(snippet.split())[:160],
    )


def _load_mapping(
    store: DashboardEventStore,
    *,
    dataset_id: str,
    chat_id: str | None = None,
    tool_id: str | None = None,
    pipe_id: str | None = None,
) -> OpenWebUIDatasetMapping:
    with store.session_factory() as session:
        mapping = session.query(OpenWebUIDatasetMapping).filter_by(ragflow_dataset_id=dataset_id).one_or_none()
        if mapping is None:
            raise ValueError("unknown dataset")
        library = session.get(Library, mapping.repo_id)
        if library is None or library.status != "active":
            raise ValueError("dataset is no longer active")
        if chat_id and mapping.ragflow_chat_id != chat_id:
            raise ValueError("chat is not assigned to dataset")
        if tool_id and mapping.openwebui_tool_id != tool_id:
            raise ValueError("tool is not assigned to dataset")
        if pipe_id and mapping.openwebui_pipe_id != pipe_id:
            raise ValueError("pipe is not assigned to dataset")
        session.expunge(mapping)
        return mapping


def _load_dashboard_mapping(
    context: DashboardContext,
    mapping_id: int,
) -> tuple[OpenWebUIDatasetMapping, Library]:
    with context.store.session_factory() as session:
        mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
        if mapping is None:
            raise ValueError("OpenWebUI-Zuordnung nicht gefunden.")
        library = session.get(Library, mapping.repo_id)
        if library is None or library.status != "active":
            raise ValueError("Seafile-Bibliothek ist nicht aktiv.")
        session.expunge(mapping)
        session.expunge(library)
        return mapping, library


def _openwebui_admin_client(settings: Settings) -> OpenWebUIClient:
    if not settings.openwebui_admin_api_key:
        raise ValueError("OpenWebUI Admin-API-Key fehlt.")
    return OpenWebUIClient(
        settings.openwebui_base_url,
        settings.openwebui_admin_api_key,
        timeout=settings.openwebui_request_timeout_seconds,
        verify=settings.openwebui_httpx_verify,
    )


def _ragflow_client(settings: Settings) -> RAGFlowClient:
    return RAGFlowClient(
        settings.ragflow_internal_url or settings.ragflow_base_url,
        settings.ragflow_api_key,
        timeout=settings.openwebui_request_timeout_seconds,
        verify=settings.ragflow_httpx_verify,
    )


def _is_owned_openwebui_artifact(
    artifact: dict[str, Any],
    *,
    expected_kind: str,
    dataset_id: str,
) -> bool:
    meta = artifact.get("meta")
    manifest_value = meta.get("manifest") if isinstance(meta, dict) else None
    manifest = manifest_value if isinstance(manifest_value, dict) else {}
    content = str(artifact.get("content") or "")
    owner_matches = (
        manifest.get("owner") == "seafile-ragflow-connector"
        or "owner: seafile-ragflow-connector" in content
        or "author: Seafile RAGFlow Connector" in content
    )
    if not owner_matches:
        return False
    artifact_id = str(artifact.get("id") or "").lower()
    artifact_type = str(artifact.get("type") or "").lower()
    manifest_kind = str(manifest.get("kind") or "").lower()
    kind_matches = (
        manifest_kind == expected_kind
        or artifact_type == expected_kind
        or f"_{expected_kind}_" in artifact_id
    )
    if not kind_matches:
        return False
    manifest_dataset_id = str(manifest.get("ragflow_dataset_id") or "")
    if manifest_dataset_id:
        return manifest_dataset_id == dataset_id
    if dataset_id and dataset_id in content:
        return True
    short_id = _openwebui_dataset_short_id(dataset_id)
    return bool(short_id and artifact_id.endswith(short_id) and f"_{expected_kind}_" in artifact_id)


def _openwebui_dataset_short_id(dataset_id: str) -> str:
    clean = "".join(
        char
        for char in dataset_id.lower()
        if ("a" <= char <= "z") or ("0" <= char <= "9") or char == "_"
    )
    if len(clean) >= 8:
        return clean[:12]
    return sha256(dataset_id.encode("utf-8")).hexdigest()[:12]


def _record_dashboard_artifact_delete(
    context: DashboardContext,
    *,
    target: str,
    artifact_id: str,
    mapping: OpenWebUIDatasetMapping,
    status: str,
) -> None:
    context.store.record_change(
        sync_id=None,
        action=f"dashboard.openwebui.{target}.delete",
        change_type=f"openwebui_{target}",
        status=status,
        object_name=artifact_id,
        source_path=f"dashboard:{mapping.repo_id}",
        target_path=f"{'openwebui' if target == 'pipe' else 'ragflow'}:{artifact_id}",
        source_system="dashboard",
        target_system="openwebui" if target == "pipe" else "ragflow",
        details={
            "mapping_id": mapping.id,
            "repo_id": mapping.repo_id,
            "ragflow_dataset_id": mapping.ragflow_dataset_id,
            "target": target,
        },
    )


def _artifact_delete_response(
    target: str,
    artifact_id: str | None,
    status: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "target": target,
        "artifact_id": artifact_id,
        "library_deleted": False,
        "message": message,
    }


def _files_by_document_id(store: DashboardEventStore, repo_id: str) -> dict[str, dict[str, Any]]:
    with store.session_factory() as session:
        rows = session.query(File).filter_by(repo_id=repo_id).all()
        return {
            str(row.ragflow_document_id): {
                "repo_id": row.repo_id,
                "path": row.path,
                "ragflow_document_name": row.ragflow_document_name,
                "detected_mime": row.detected_mime,
                "ingested_mime": row.ingested_mime,
            }
            for row in rows
            if row.ragflow_document_id
        }


def _openwebui_audit_diagnostics(
    *,
    question: str | None,
    top_k: int,
    answer: str,
    answer_origin: str,
    answer_path: str,
    reference_path: str,
    sources: list[dict[str, Any]],
    latency_ms: int,
) -> dict[str, Any]:
    selected_sources = [_audit_source_summary(source) for source in sources[:10]]
    used_sources = [
        item
        for item in selected_sources
        if item.get("used_in_answer") or f"[{item.get('source_id')}]" in answer
    ]
    coverage = _openwebui_claim_coverage(answer, sources)
    supported_claims = coverage.get("supported_claims")
    total_claims = coverage.get("total_claims")
    unsupported_claims = (
        max(0, total_claims - supported_claims)
        if isinstance(total_claims, int) and isinstance(supported_claims, int)
        else 0
    )
    return {
        "query_id": _query_id(question),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "ragflow",
        "retrieval_mode": "chat+reference+audit_rerank",
        "top_k": top_k,
        "answer_origin": answer_origin,
        "answer_path": answer_path,
        "reference_path": reference_path,
        "source_count_before_dedup": len(sources),
        "source_count_after_dedup": len(sources),
        "selected_sources": selected_sources,
        "used_sources": used_sources,
        "claim_coverage": coverage,
        "unsupported_claims": unsupported_claims,
        "latency_ms": latency_ms,
    }


def _query_id(question: str | None) -> str:
    clean = " ".join(str(question or "").split())
    if not clean:
        return ""
    return sha256(clean.encode("utf-8")).hexdigest()[:16]


def _audit_source_summary(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("source_metadata")
    if not isinstance(metadata, dict):
        metadata_items = source.get("metadata")
        metadata = metadata_items[0] if isinstance(metadata_items, list) and metadata_items else {}
    return {
        key: value
        for key, value in {
            "source_id": source.get("source_id") or metadata.get("source_id"),
            "title": source.get("name") or metadata.get("document_name"),
            "document_id": metadata.get("document_id"),
            "chunk_id": metadata.get("chunk_id"),
            "role": metadata.get("source_role") or metadata.get("role"),
            "match_type": metadata.get("match_type"),
            "audit_score": source.get("audit_score") or metadata.get("audit_score"),
            "used_in_answer": bool(metadata.get("used_in_answer") or source.get("used_in_answer")),
            "claim_ids": metadata.get("claim_ids") or source.get("claim_ids"),
        }.items()
        if value not in (None, "", [], {})
    }


def _openwebui_claim_coverage(answer: str, sources: list[dict[str, Any]]) -> dict[str, int | str]:
    claims = [
        part.strip()
        for part in str(answer or "").replace("?", ".").replace("!", ".").split(".")
        if len(part.strip()) >= 12
    ]
    if not claims:
        return {"supported_claims": 0, "total_claims": 0, "status": "retrieval-only"}
    source_ids = {
        str(source.get("source_id") or (source.get("source_metadata") or {}).get("source_id"))
        for source in sources
    }
    supported = 0
    for claim in claims:
        if any(f"[{source_id}]" in claim for source_id in source_ids if source_id):
            supported += 1
    status = (
        "vollständig belegt"
        if supported == len(claims)
        else "teilweise belegt"
        if supported
        else "nicht ausreichend belegt"
    )
    return {"supported_claims": supported, "total_claims": len(claims), "status": status}


def _sources_markdown(sources: list[dict[str, Any]], settings: Settings) -> str:
    return render_sources_markdown(
        sources,
        show_scores=False,
        show_debug=False,
        mode="audit",
        language=localizer_for(settings).language,
    )


def _source_document_markdown(name: str, url: Any, original_url: Any, settings: Settings) -> str:
    title = _markdown_plain(name)
    links = f"[{title}]({url})" if url else title
    if original_url and original_url != url:
        links = (
            f"{links} - "
            f"[{localizer_for(settings).text('sources.open_original')}]({original_url})"
        )
    return links


def _filter_sources_for_requested_document(
    sources: list[dict[str, Any]], question: str | None
) -> list[dict[str, Any]]:
    if not question:
        return sources
    question_lower = question.lower()
    requested = [
        source
        for source in sources
        if str(source.get("name") or "").lower() in question_lower
    ]
    return requested or sources


def _format_score(score: Any) -> str:
    if score in (None, ""):
        return ""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return str(score)
    if 0 <= value <= 1:
        return f"{value:.0%}"
    return f"{value:.3g}"


def _compact_markdown_text(text: str, limit: int) -> str:
    clean = "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _clean_source_snippet(text: Any) -> str:
    parser = _SnippetHTMLTextExtractor()
    parser.feed(str(text or ""))
    parser.close()
    clean = parser.text
    clean = "\n".join(" ".join(line.split()) for line in clean.splitlines())
    return "\n".join(line for line in clean.splitlines() if line).strip()


class _SnippetHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if name == "br":
            self._parts.append("\n")
        elif name == "tr":
            self._append_line_break()
        elif name in {"td", "th"}:
            self._append_table_cell_separator()

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if name == "tr":
            self._append_line_break()

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def _append_line_break(self) -> None:
        if self._parts and self._parts[-1] != "\n":
            self._parts.append("\n")

    def _append_table_cell_separator(self) -> None:
        if not self._parts:
            return
        current = "".join(self._parts).rstrip()
        if current and not current.endswith(("\n", "|")):
            self._parts.append(" | ")


def _clean_answer_text(text: str) -> str:
    if not text:
        return ""
    if "<" not in text and "&" not in text:
        return text
    return _clean_source_snippet(text)


def _markdown_plain(text: str) -> str:
    return " ".join(text.split()).replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def _markdown_cell(text: str) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def _blockquote(text: str) -> str:
    lines = str(text or "").splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _preview_payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value in (None, ""):
        return ""
    return str(value).strip()


def _preview_join(parts: list[str], *, separator: str = " · ") -> str:
    return separator.join(part for part in parts if part)


def _preview_line_range(start: str, end: str) -> str:
    if not start and not end:
        return ""
    if not end or end == start:
        return start
    if not start:
        return end
    return f"{start}-{end}"


def _preview_definition_list(rows: list[tuple[str, str]]) -> str:
    """Render rows whose values are already escaped or intentionally safe HTML."""
    return "".join(
        f"<div><dt>{escape(label)}</dt><dd>{value}</dd></div>" for label, value in rows if value
    )


def _preview_metric_card(label: str, value_html: str, hint_html: str = "") -> str:
    hint = f"<small>{hint_html}</small>" if hint_html else ""
    return f'<article class="metric"><span>{escape(label)}</span><strong>{value_html}</strong>{hint}</article>'


def _preview_is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _preview_is_connector_link(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or ""
    return (
        path.startswith("/api/openwebui/sources/preview")
        or path.startswith("/api/sources/preview")
        or path == "/api/openwebui/proxy"
        or path.startswith("/api/openwebui/proxy/")
    )


def _preview_relevance_hint(score: Any, settings: Settings) -> str:
    l10n = localizer_for(settings)
    if score in (None, ""):
        return l10n.text("preview.no_score")
    try:
        value = float(score)
    except (TypeError, ValueError):
        return l10n.text("preview.score_non_numeric")
    if 0 <= value <= 1:
        if value >= 0.8:
            level = l10n.text("sources.high")
        elif value >= 0.5:
            level = l10n.text("sources.medium")
        else:
            level = l10n.text("sources.low")
        return f"{l10n.text('preview.score_relative')} · {level}"
    return l10n.text("preview.score_non_normalized")


def _preview_html(settings: Settings, token: str | None) -> str:
    l10n = localizer_for(settings)
    if not token or not settings.openwebui_proxy_shared_secret:
        return _preview_unavailable_html(l10n.language)
    try:
        payload = verify_preview_token(
            token,
            settings.openwebui_proxy_shared_secret,
            expected_purpose=SOURCE_PREVIEW_PURPOSE,
            expected_audience=OPENWEBUI_PREVIEW_AUDIENCE,
        )
    except ValueError:
        return _preview_unavailable_html(l10n.language)

    unknown = escape(l10n.text("sources.unknown"))
    title = escape(_preview_payload_text(payload, "document_name") or l10n.text("sources.source"))
    dataset_raw = _preview_payload_text(payload, "dataset_name") or _preview_payload_text(
        payload, "dataset_id"
    )
    dataset = escape(dataset_raw) if dataset_raw else unknown
    dataset_id = escape(_preview_payload_text(payload, "dataset_id"))
    document_id = escape(_preview_payload_text(payload, "document_id"))
    chunk = escape(_preview_payload_text(payload, "chunk_id"))
    citation = escape(_preview_payload_text(payload, "citation_label") or l10n.text("sources.source"))
    page_raw = _preview_payload_text(payload, "page")
    section_raw = _preview_payload_text(payload, "section")
    line_raw = _preview_payload_text(payload, "line")
    line_start_raw = _preview_payload_text(payload, "line_start")
    line_end_raw = _preview_payload_text(payload, "line_end")
    locator_quality_raw = _preview_payload_text(payload, "locator_quality")
    line_display = _preview_line_range(line_start_raw or line_raw, line_end_raw)
    page_label = escape(l10n.text("sources.page", value=page_raw)) if page_raw else ""
    section_label = escape(l10n.text("sources.section", value=section_raw)) if section_raw else ""
    line_label = escape(l10n.text("sources.line", value=line_display)) if line_display else ""
    repo_id = escape(_preview_payload_text(payload, "repo_id"))
    source_path = escape(_preview_payload_text(payload, "source_path"))
    file_type_raw = _preview_payload_text(payload, "file_type")
    file_type = escape(file_type_raw.upper()) if file_type_raw else ""
    mime_type = escape(_preview_payload_text(payload, "mime_type"))
    score = _format_score(payload.get("score"))
    score_text = escape(score or l10n.text("sources.unknown"))
    score_hint = escape(_preview_relevance_hint(payload.get("score"), settings))
    snippet_text = _clean_source_snippet(payload.get("snippet") or "")
    snippet = escape(snippet_text)
    empty_snippet = escape(l10n.text("preview.no_snippet"))
    snippet_html = f"<mark>{snippet}</mark>" if snippet else f'<span class="empty-state">{empty_snippet}</span>'

    original_url = _preview_payload_text(payload, "original_url")
    original_is_connector = _preview_is_connector_link(original_url) if original_url else False
    original_is_safe_http = _preview_is_http_url(original_url) if original_url else False
    has_original_url = bool(original_url and original_is_safe_http and not original_is_connector)
    original_href = escape(original_url, quote=True)
    original_visible = escape(original_url)
    original_label = escape(l10n.text("preview.original"))
    if has_original_url:
        original_action = (
            f'<a class="button primary original-action" href="{original_href}" target="_blank" '
            f'rel="noreferrer noopener" data-original-link="true">{original_label}</a>'
        )
        original_row = (
            f'<a class="text-link" href="{original_href}" target="_blank" '
            f'rel="noreferrer noopener">{original_visible}</a>'
        )
        original_status = escape(l10n.text("preview.original_external_hint"))
    else:
        if original_url and original_is_connector:
            missing_reason = l10n.text("preview.original_connector_link_error")
        elif original_url and not original_is_safe_http:
            missing_reason = l10n.text("preview.original_invalid_url_error")
        else:
            missing_reason = l10n.text("preview.original_missing_hint")
        original_action = (
            f'<span class="original-missing" role="status"><strong>{escape(l10n.text("preview.original_missing"))}</strong>'
            f"<span>{escape(missing_reason)}</span></span>"
        )
        original_row = (
            escape(original_url) if original_url else escape(l10n.text("preview.original_missing_hint"))
        )
        original_status = escape(l10n.text("preview.original_link_config_hint"))

    position_raw = payload.get("position")
    position_json = json.dumps(position_raw, ensure_ascii=False, default=str)
    position = escape(position_json)
    has_position = position_raw not in (None, "", [], {}) and position_json not in ("null", '""')
    position_state = escape(
        l10n.text("preview.coordinates_available")
        if has_position
        else l10n.text("preview.coordinates_missing")
    )
    location_summary = _preview_join([page_label, section_label, line_label]) or unknown
    path_or_citation = source_path or citation
    file_summary = file_type or escape(l10n.text("preview.source"))
    mime_summary = mime_type or escape(l10n.text("preview.mime_unknown"))
    debug_payload = dict(payload)
    debug_payload["snippet"] = snippet_text
    raw_json = escape(json.dumps(debug_payload, ensure_ascii=False, indent=2, default=str))

    metrics = "".join(
        [
            _preview_metric_card(
                "Dataset",
                dataset,
                escape(l10n.text("preview.dataset_hint")),
            ),
            _preview_metric_card(
                l10n.text("preview.location"),
                location_summary,
                escape(l10n.text("preview.location_summary_hint")),
            ),
            _preview_metric_card(
                l10n.text("sources.relevance", value="").strip(),
                score_text,
                score_hint,
            ),
            _preview_metric_card(
                l10n.text("preview.file"),
                file_summary,
                mime_summary,
            ),
        ]
    )

    location_details = _preview_definition_list(
        [
            (l10n.text("preview.citation_label"), citation),
            (l10n.text("sources.page", value="").strip(), escape(page_raw) if page_raw else unknown),
            (
                l10n.text("sources.section", value="").strip(),
                escape(section_raw) if section_raw else unknown,
            ),
            (
                l10n.text("sources.line", value="").strip(),
                escape(line_display) if line_display else unknown,
            ),
            (
                l10n.text("preview.locator_quality"),
                escape(locator_quality_raw) if locator_quality_raw else unknown,
            ),
            (l10n.text("preview.position_bbox"), position_state),
            (l10n.text("preview.chunk_id"), chunk or unknown),
        ]
    )
    origin_details = _preview_definition_list(
        [
            (l10n.text("preview.original_document"), original_row),
            (l10n.text("preview.note"), original_status),
            (l10n.text("preview.seafile_repo"), repo_id or unknown),
            (l10n.text("preview.source_path"), source_path or unknown),
            (l10n.text("preview.file_type"), file_type or unknown),
            ("MIME-Type", mime_type or unknown),
        ]
    )
    technical_details = _preview_definition_list(
        [
            ("Dataset-ID", dataset_id or unknown),
            (l10n.text("preview.document_id"), document_id or unknown),
            (l10n.text("preview.chunk_id"), chunk or unknown),
            (
                l10n.text("preview.raw_position"),
                f"<code>{position}</code>" if has_position else unknown,
            ),
        ]
    )

    copy_snippet_label = escape(l10n.text("preview.copy_snippet"), quote=True)
    copy_link_label = escape(l10n.text("preview.copy_link"), quote=True)
    copy_metadata_label = escape(l10n.text("preview.copy_metadata"), quote=True)
    copied_js = json.dumps(l10n.text("preview.copied"))
    error_js = json.dumps(l10n.text("preview.copy_error"))

    return (
        f"<!doctype html><html lang=\"{l10n.language}\" dir=\"{'rtl' if l10n.language == 'ar' else 'ltr'}\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>"
        ":root{color-scheme:light dark;--bg:#f5f7fb;--panel:#fff;--panel-2:#f8fafc;--panel-3:#eef3f8;--text:#111827;--muted:#64748b;--border:#d8e1ec;--accent:#0f766e;--accent-strong:#0d9488;--accent-soft:#e6fffb;--code:#eef2f7;--mark:#fff4b8;--warn:#8a3a12;--warn-bg:#fff7ed;--shadow:0 18px 50px rgba(15,23,42,.09)}"
        "@media(prefers-color-scheme:dark){:root{--bg:#0a0f18;--panel:#121a28;--panel-2:#101827;--panel-3:#182335;--text:#f8fafc;--muted:#94a3b8;--border:#2c3a4e;--accent:#2dd4bf;--accent-strong:#14b8a6;--accent-soft:#123f3b;--code:#0b1220;--mark:#5b4b15;--warn:#fdba74;--warn-bg:#2b1708;--shadow:0 26px 76px rgba(0,0,0,.34)}}"
        "[data-theme=light]{color-scheme:light;--bg:#f5f7fb;--panel:#fff;--panel-2:#f8fafc;--panel-3:#eef3f8;--text:#111827;--muted:#64748b;--border:#d8e1ec;--accent:#0f766e;--accent-strong:#0d9488;--accent-soft:#e6fffb;--code:#eef2f7;--mark:#fff4b8;--warn:#8a3a12;--warn-bg:#fff7ed;--shadow:0 18px 50px rgba(15,23,42,.09)}"
        "[data-theme=dark]{color-scheme:dark;--bg:#0a0f18;--panel:#121a28;--panel-2:#101827;--panel-3:#182335;--text:#f8fafc;--muted:#94a3b8;--border:#2c3a4e;--accent:#2dd4bf;--accent-strong:#14b8a6;--accent-soft:#123f3b;--code:#0b1220;--mark:#5b4b15;--warn:#fdba74;--warn-bg:#2b1708;--shadow:0 26px 76px rgba(0,0,0,.34)}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.55;letter-spacing:0}body:before{content:\"\";position:fixed;inset:0 0 auto;height:5px;background:var(--accent);z-index:2}"
        "main{max-width:1160px;margin:0 auto;padding:30px 18px 46px}.viewer{display:grid;gap:16px}.hero,.panel,.metric{border:1px solid var(--border);background:var(--panel);box-shadow:var(--shadow)}"
        ".hero{display:grid;gap:20px;padding:24px;border-radius:8px;position:relative;overflow:hidden}.hero:before{content:\"\";position:absolute;inset:0 auto 0 0;width:5px;background:var(--accent)}.hero>*{position:relative}.topbar{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.eyebrow{margin:0;color:var(--accent);font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em}.theme-note{margin:.2rem 0 0;color:var(--muted);font-size:.92rem}"
        ".hero-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,340px);gap:18px;align-items:start}h1{margin:0;font-size:clamp(1.45rem,3vw,2.35rem);line-height:1.12;overflow-wrap:anywhere}.path{margin:.65rem 0 0;color:var(--muted);overflow-wrap:anywhere}.actions{display:flex;flex-wrap:wrap;gap:9px}.hero-actions{justify-content:flex-end}.button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;border:1px solid var(--border);border-radius:8px;padding:9px 13px;background:var(--panel);color:var(--text);font:inherit;font-weight:700;text-decoration:none;cursor:pointer}.button.primary{background:var(--accent);border-color:var(--accent);color:#fff;min-width:190px}.button:hover{border-color:var(--accent);transform:translateY(-1px)}.button.primary:hover{background:var(--accent-strong)}.button:focus-visible,summary:focus-visible,a:focus-visible{outline:0;box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 32%,transparent)}"
        ".original-missing{display:flex;flex-direction:column;gap:3px;border:1px solid color-mix(in srgb,var(--warn) 34%,var(--border));border-radius:8px;padding:10px 12px;background:var(--warn-bg);color:var(--warn);overflow-wrap:anywhere}.original-missing strong{font-size:.96rem}.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{border-radius:8px;padding:14px;box-shadow:none}.metric span{display:block;color:var(--muted);font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.metric strong{display:block;margin-top:5px;font-size:1.05rem;overflow-wrap:anywhere}.metric small{display:block;margin-top:3px;color:var(--muted);font-size:.82rem;overflow-wrap:anywhere}"
        ".panel{border-radius:8px;overflow:hidden}.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:15px 18px;border-bottom:1px solid var(--border);background:var(--panel-3)}.panel-head h2{margin:0;font-size:1.02rem}.panel-head p{margin:.25rem 0 0;color:var(--muted);font-size:.9rem}.snippet{margin:0;padding:24px;background:var(--panel-2);white-space:pre-wrap;overflow:auto;overflow-wrap:anywhere;max-height:48vh;font-size:1.04rem;line-height:1.78}.snippet mark{background:var(--mark);color:var(--text);padding:2px 3px;border-radius:4px;box-decoration-break:clone;-webkit-box-decoration-break:clone}.empty-state{color:var(--muted);font-style:italic}"
        ".info-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card-body{padding:4px 18px 14px}dl{margin:0}dl div{display:grid;grid-template-columns:150px minmax(0,1fr);gap:14px;padding:10px 0;border-bottom:1px solid var(--border)}dl div:last-child{border-bottom:0}dt{color:var(--muted);font-size:.82rem}dd{margin:0;font-weight:650;overflow-wrap:anywhere}.text-link{color:var(--accent);font-weight:750;text-decoration-thickness:.08em;text-underline-offset:3px;overflow-wrap:anywhere}code,pre.raw{background:var(--code);border-radius:7px}code{padding:2px 5px}details.panel summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 18px;background:var(--panel-3);cursor:pointer;font-weight:800}details.panel summary::-webkit-details-marker{display:none}details.panel summary:after{content:\"+\";color:var(--muted)}details.panel[open] summary:after{content:\"−\"}.raw{margin:0;padding:16px;white-space:pre-wrap;overflow:auto;max-height:360px;font-size:.86rem}.debug-actions{padding:0 18px 18px}"
        "@media(max-width:900px){.hero-grid,.info-grid{grid-template-columns:1fr}.hero-actions{justify-content:flex-start}.summary{grid-template-columns:repeat(2,minmax(0,1fr))}}"
        "@media(max-width:620px){main{padding:14px 10px 30px}.hero{padding:18px}.topbar{display:grid;grid-template-columns:1fr}.summary{grid-template-columns:1fr}.actions .button,.button.primary{width:100%;min-width:0}.panel-head{display:grid}.snippet{padding:18px;font-size:1rem;max-height:54vh}dl div{grid-template-columns:1fr;gap:3px}.card-body{padding:2px 14px 12px}}"
        "</style></head><body><main><div class=\"viewer\">"
        "<section class=\"hero source-card\">"
        f"<div class=\"topbar\"><div><p class=\"eyebrow\">{escape(l10n.text('preview.evidence_label'))}</p><p class=\"theme-note\">{escape(l10n.text('preview.evidence_subtitle'))}</p></div><button class=\"button\" id=\"theme-toggle\" type=\"button\">{escape(l10n.text('preview.theme'))}</button></div>"
        f"<div class=\"hero-grid\"><div><h1>{title}</h1><p class=\"path\">{path_or_citation}</p></div><div class=\"actions hero-actions\">{original_action}<button class=\"button\" type=\"button\" data-copy-url data-reset=\"{copy_link_label}\">{escape(l10n.text('preview.copy_link'))}</button></div></div>"
        "</section>"
        f"<section class=\"summary\" aria-label=\"{escape(l10n.text('preview.evidence_summary'), quote=True)}\">{metrics}</section>"
        "<section class=\"panel\">"
        f"<div class=\"panel-head\"><div><h2>{escape(l10n.text('preview.used_context'))}</h2><p>{escape(l10n.text('preview.used_context_hint'))}</p></div><div class=\"actions\"><button class=\"button\" type=\"button\" data-copy-target=\"evidence-snippet\" data-reset=\"{copy_snippet_label}\">{escape(l10n.text('preview.copy_snippet'))}</button></div></div>"
        f"<pre class=\"snippet\" id=\"evidence-snippet\">{snippet_html}</pre>"
        "</section>"
        "<section class=\"info-grid\">"
        f"<article class=\"panel\"><div class=\"panel-head\"><div><h2>{escape(l10n.text('preview.location'))}</h2><p>{escape(l10n.text('preview.location_hint'))}</p></div></div><div class=\"card-body\"><dl>{location_details}</dl></div></article>"
        f"<article class=\"panel\"><div class=\"panel-head\"><div><h2>{escape(l10n.text('preview.origin'))}</h2><p>{escape(l10n.text('preview.origin_hint'))}</p></div></div><div class=\"card-body\"><dl>{origin_details}</dl></div></article>"
        "</section>"
        "<details class=\"panel\">"
        f"<summary>{escape(l10n.text('preview.technical_details'))}</summary>"
        f"<div class=\"card-body\"><dl>{technical_details}</dl></div>"
        f"<pre class=\"raw\" id=\"raw-payload\">{raw_json}</pre><div class=\"actions debug-actions\"><button class=\"button\" type=\"button\" data-copy-target=\"raw-payload\" data-reset=\"{copy_metadata_label}\">{escape(l10n.text('preview.copy_metadata'))}</button></div>"
        "</details>"
        "</div><script>"
        "const root=document.documentElement;const saved=localStorage.getItem('source-preview-theme');if(saved){root.dataset.theme=saved;}"
        "const themeToggle=document.getElementById('theme-toggle');if(themeToggle){themeToggle.addEventListener('click',()=>{const next=root.dataset.theme==='dark'?'light':'dark';root.dataset.theme=next;localStorage.setItem('source-preview-theme',next);});}"
        f"async function copyText(btn,text){{const reset=btn.dataset.reset||btn.textContent;try{{await navigator.clipboard.writeText(text);btn.textContent={copied_js};}}catch(err){{btn.textContent={error_js};}}setTimeout(()=>{{btn.textContent=reset;}},1400);}}"
        "document.querySelectorAll('[data-copy-target]').forEach(btn=>btn.addEventListener('click',()=>{const target=document.getElementById(btn.dataset.copyTarget||'');copyText(btn,target?target.textContent||'':'');}));"
        "document.querySelectorAll('[data-copy-url]').forEach(btn=>btn.addEventListener('click',()=>copyText(btn,location.href)));"
        "</script></main></body></html>"
    )


def _preview_unavailable_html(language: str = "de") -> str:
    l10n = localizer_for(type("_Settings", (), {"connector_language": language})())
    title = escape(l10n.text("preview.title"))
    message = escape(l10n.text("preview.invalid_token"))
    detail = escape(l10n.text("preview.invalid_token_detail"))
    return (
        f"<!doctype html><html lang=\"{l10n.language}\" dir=\"{'rtl' if l10n.language == 'ar' else 'ltr'}\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>"
        ":root{color-scheme:light dark;--bg:#f5f7fb;--panel:#fff;--text:#111827;--muted:#64748b;--border:#d8e1ec;--accent:#0f766e;--shadow:0 18px 50px rgba(15,23,42,.09)}"
        "@media(prefers-color-scheme:dark){:root{--bg:#0a0f18;--panel:#121a28;--text:#f8fafc;--muted:#94a3b8;--border:#2c3a4e;--accent:#2dd4bf;--shadow:0 26px 76px rgba(0,0,0,.34)}}"
        "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:18px;background:var(--bg);color:var(--text);font-family:Segoe UI,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.55;letter-spacing:0}"
        "main{max-width:620px;border:1px solid var(--border);border-radius:8px;background:var(--panel);box-shadow:var(--shadow);padding:28px;position:relative;overflow:hidden}main:before{content:\"\";position:absolute;inset:0 auto 0 0;width:5px;background:var(--accent)}.eyebrow{margin:0;color:var(--accent);font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em}h1{margin:.35rem 0 .65rem;font-size:clamp(1.45rem,4vw,2rem);line-height:1.15}p{margin:.5rem 0;color:var(--muted);overflow-wrap:anywhere}"
        "</style></head><body><main>"
        f"<p class=\"eyebrow\">{escape(l10n.text('preview.evidence_label'))}</p><h1>{title}</h1><p>{message}</p><p>{detail}</p>"
        "</main></body></html>"
    )
