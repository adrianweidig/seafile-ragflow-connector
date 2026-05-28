from __future__ import annotations

# ruff: noqa: E501
import base64
import binascii
import hmac
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import structlog

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.clients.tls import classify_httpx_error, safe_url_for_logs
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.export import audit_export_filename, build_audit_workbook
from seafile_ragflow_connector.dashboard.health import collect_dashboard_health, collect_tls_health
from seafile_ragflow_connector.dashboard.store import DashboardEventStore
from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML
from seafile_ragflow_connector.i18n import localizer_for
from seafile_ragflow_connector.openwebui.sources import (
    annotate_answer_citations,
    extract_answer,
    normalize_sources,
    render_sources_markdown,
    verify_preview_token,
)
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping
from seafile_ragflow_connector.utils.redaction import redact_mapping


class DashboardBindError(RuntimeError):
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
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "SeafileRAGFlowConnectorDashboard/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/openwebui/sources/preview":
                    params = parse_qs(parsed.query)
                    self._send_html(_preview_html(context.settings, _one(params, "token")))
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
            try:
                if parsed.path == "/api/openwebui/proxy/query":
                    self._send_json(_handle_openwebui_query(context, self._json_body(), self.headers.get("Authorization")))
                    return
                if parsed.path == "/api/openwebui/proxy/chat":
                    self._send_json(_handle_openwebui_chat(context, self._json_body(), self.headers.get("Authorization")))
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
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
                payload, status = _proxy_error_response(context.settings, parsed.path, exc)
                self._send_json(payload, status=status)

        def log_message(self, format: str, *args: Any) -> None:
            structlog.get_logger(__name__).debug("dashboard.http_access", message=format % args)

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    ragflow = RAGFlowClient(
        context.settings.ragflow_internal_url or context.settings.ragflow_base_url,
        context.settings.ragflow_api_key,
        timeout=context.settings.openwebui_request_timeout_seconds,
        verify=context.settings.ragflow_httpx_verify,
    )
    try:
        result = ragflow.retrieve_chunks(dataset_id=dataset_id, question=question, top_k=top_k, page_size=top_k)
    finally:
        ragflow.close()
    sources = normalize_sources(
        result,
        settings=context.settings,
        dataset_id=dataset_id,
        dataset_name=mapping.ragflow_dataset_name,
        files_by_document_id=_files_by_document_id(context.store, mapping.repo_id),
    )
    return {
        "answer": _sources_markdown(sources, context.settings),
        "sources": sources,
        "source_markdown": _sources_markdown(sources, context.settings),
        "retrieval_only": True,
        "citations_emitted": True,
    }


def _handle_openwebui_chat(
    context: DashboardContext,
    payload: dict[str, Any],
    authorization: str | None,
) -> dict[str, Any]:
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
    ragflow = RAGFlowClient(
        context.settings.ragflow_internal_url or context.settings.ragflow_base_url,
        context.settings.ragflow_api_key,
        timeout=context.settings.openwebui_request_timeout_seconds,
        verify=context.settings.ragflow_httpx_verify,
    )
    try:
        files_by_document_id = _files_by_document_id(context.store, mapping.repo_id)
        question = _last_user_message(messages)
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
            structlog.get_logger(__name__).warning(
                "openwebui.chat_completion_failed_fallback_retrieval",
                dataset_id=dataset_id,
                chat_id=chat_id,
                error=str(exc),
            )
            sources = _retrieve_openwebui_sources(
                ragflow,
                context=context,
                mapping=mapping,
                dataset_id=dataset_id,
                question=question,
                top_k=top_k,
                files_by_document_id=files_by_document_id,
            )
            return {
                "answer": "",
                "sources": sources,
                "source_markdown": _sources_markdown(sources, context.settings),
                "retrieval_only": True,
                "citations_emitted": False,
            }
        sources = normalize_sources(
            result,
            settings=context.settings,
            dataset_id=dataset_id,
            dataset_name=mapping.ragflow_dataset_name,
            files_by_document_id=files_by_document_id,
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
    finally:
        ragflow.close()
    l10n = localizer_for(context.settings)
    answer = annotate_answer_citations(
        _clean_answer_text(extract_answer(result)),
        sources,
        language=l10n.language,
    )
    return {
        "answer": answer,
        "sources": sources,
        "source_markdown": _sources_markdown(sources, context.settings),
        "retrieval_only": not bool(answer.strip()),
        "citations_emitted": False,
    }


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


def _proxy_error_type(exc: Exception) -> str:
    if isinstance(exc, ApiError):
        return f"HTTP_{exc.status_code or 'API_ERROR'}"
    return classify_httpx_error(exc)


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
) -> list[dict[str, Any]]:
    retrieval_result = ragflow.retrieve_chunks(
        dataset_id=dataset_id,
        question=question,
        top_k=top_k,
        page_size=top_k,
    )
    return normalize_sources(
        retrieval_result,
        settings=context.settings,
        dataset_id=dataset_id,
        dataset_name=mapping.ragflow_dataset_name,
        files_by_document_id=files_by_document_id,
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
        payload = verify_preview_token(token, settings.openwebui_proxy_shared_secret)
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
