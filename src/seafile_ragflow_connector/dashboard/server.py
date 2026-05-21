from __future__ import annotations

# ruff: noqa: E501
import hmac
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.export import audit_export_filename, build_audit_workbook
from seafile_ragflow_connector.dashboard.health import collect_dashboard_health
from seafile_ragflow_connector.dashboard.store import DashboardEventStore
from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML
from seafile_ragflow_connector.openwebui.sources import (
    extract_answer,
    normalize_sources,
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
                if parsed.path == "/api/status":
                    self._send_json(context.store.connector_status(started_at=context.started_at))
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(context.store.metrics())
                    return
                if parsed.path == "/api/systems":
                    self._send_json(context.store.systems())
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
                if parsed.path == "/api/openwebui/sources/preview":
                    params = parse_qs(parsed.query)
                    self._send_html(_preview_html(context.settings, _one(params, "token")))
                    return
                if parsed.path in {"/api/audit.xlsx", "/api/audit-export.xlsx"}:
                    snapshot = context.store.audit_snapshot(
                        started_at=context.started_at,
                        safe_config=_safe_config(context.settings),
                    )
                    self._send_xlsx(build_audit_workbook(snapshot), audit_export_filename())
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
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
            except Exception as exc:
                structlog.get_logger(__name__).warning("openwebui.proxy_failed", path=parsed.path, error=str(exc))
                self._send_json(
                    {"error": "proxy request failed", "message": "Die RAGFlow-Abfrage konnte nicht geladen werden."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

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
    top_k = int(payload.get("top_k") or 5)
    mapping = _load_mapping(context.store, dataset_id=dataset_id, tool_id=artifact_id)
    ragflow = RAGFlowClient(
        context.settings.ragflow_internal_url or context.settings.ragflow_base_url,
        context.settings.ragflow_api_key,
        timeout=context.settings.openwebui_request_timeout_seconds,
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
    return {"answer": _sources_markdown(sources), "sources": sources, "citations_emitted": True}


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
    )
    try:
        result = ragflow.chat_completion(
            chat_id=chat_id,
            messages=messages,
            model=str(payload.get("model") or "model"),
            stream=False,
        )
        files_by_document_id = _files_by_document_id(context.store, mapping.repo_id)
        sources = normalize_sources(
            result,
            settings=context.settings,
            dataset_id=dataset_id,
            dataset_name=mapping.ragflow_dataset_name,
            files_by_document_id=files_by_document_id,
        )
        if not sources:
            question = _last_user_message(messages)
            if question:
                retrieval_result = ragflow.retrieve_chunks(
                    dataset_id=dataset_id,
                    question=question,
                    top_k=5,
                    page_size=5,
                )
                sources = normalize_sources(
                    retrieval_result,
                    settings=context.settings,
                    dataset_id=dataset_id,
                    dataset_name=mapping.ragflow_dataset_name,
                    files_by_document_id=files_by_document_id,
                )
    finally:
        ragflow.close()
    return {"answer": extract_answer(result), "sources": sources, "citations_emitted": True}


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
            }
            for row in rows
            if row.ragflow_document_id
        }


def _sources_markdown(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "Keine passenden Quellen gefunden."
    lines = ["Gefundene Quellen:"]
    for index, source in enumerate(sources, start=1):
        name = source.get("name") or "Quelle"
        url = source.get("url")
        snippet = source.get("snippet") or ""
        lines.append(f"{index}. [{name}]({url})" if url else f"{index}. {name}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


def _preview_html(settings: Settings, token: str | None) -> str:
    if not token or not settings.openwebui_proxy_shared_secret:
        return "<!doctype html><html><body><h1>Quelle nicht verfügbar</h1></body></html>"
    try:
        payload = verify_preview_token(token, settings.openwebui_proxy_shared_secret)
    except ValueError:
        return "<!doctype html><html><body><h1>Quelle nicht verfügbar</h1></body></html>"
    title = escape(str(payload.get("document_name") or "Quelle"))
    snippet = escape(str(payload.get("snippet") or ""))
    dataset = escape(str(payload.get("dataset_name") or payload.get("dataset_id") or ""))
    chunk = escape(str(payload.get("chunk_id") or ""))
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem;line-height:1.5;max-width:960px}"
        "pre{white-space:pre-wrap;background:#f1f5f9;padding:1rem;border-radius:8px}</style></head><body>"
        f"<h1>{title}</h1><p>Dataset: {dataset}</p><p>Chunk: {chunk}</p><pre>{snippet}</pre></body></html>"
    )
