from __future__ import annotations

# ruff: noqa: E501
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
        except ApiError as exc:
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
                "answer": _sources_markdown(sources),
                "sources": sources,
                "citations_emitted": True,
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
    answer = annotate_answer_citations(_clean_answer_text(extract_answer(result)), sources)
    if sources and "## Gefundene Quellen" not in answer:
        answer = (answer.strip() + "\n\n" if answer.strip() else "") + _sources_markdown(sources)
    return {"answer": answer, "sources": sources, "citations_emitted": True}


def _proxy_error_response(
    settings: Settings,
    path: str,
    exc: Exception,
) -> tuple[dict[str, str], HTTPStatus]:
    route = "Connector Proxy -> RAGFlow"
    target = safe_url_for_logs(settings.ragflow_internal_url or settings.ragflow_base_url)
    error_type = _proxy_error_type(exc)
    status = HTTPStatus.BAD_GATEWAY
    message = "Die RAGFlow-Abfrage konnte nicht geladen werden."
    if isinstance(exc, httpx.TimeoutException):
        message = "RAGFlow hat nicht rechtzeitig geantwortet."
        status = HTTPStatus.GATEWAY_TIMEOUT
    elif isinstance(exc, ApiError):
        message = "RAGFlow antwortete mit einem Fehlerstatus."
    elif isinstance(exc, httpx.ConnectError | httpx.RequestError):
        message = "RAGFlow war über den Connector-Proxy nicht erreichbar."

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
            }
            for row in rows
            if row.ragflow_document_id
        }


def _sources_markdown(sources: list[dict[str, Any]]) -> str:
    return render_sources_markdown(sources, show_scores=True, show_debug=False)


def _source_document_markdown(name: str, url: Any, original_url: Any) -> str:
    title = _markdown_plain(name)
    links = f"[{title}]({url})" if url else title
    if original_url and original_url != url:
        links = f"{links} - [Original öffnen]({original_url})"
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


def _source_locator(source: dict[str, Any]) -> str:
    metadata = source.get("source_metadata")
    if not isinstance(metadata, dict):
        metadata_items = source.get("metadata")
        metadata = metadata_items[0] if isinstance(metadata_items, list) and metadata_items else {}
    parts = []
    page = metadata.get("page")
    if page not in (None, ""):
        parts.append(f"Seite {page}")
    section = metadata.get("section")
    if section not in (None, ""):
        parts.append(f"Abschnitt {section}")
    line = metadata.get("line")
    if line not in (None, ""):
        parts.append(f"Zeile {line}")
    chunk_id = metadata.get("chunk_id")
    if chunk_id not in (None, ""):
        chunk = str(chunk_id)
        parts.append(f"Chunk `{chunk[:12]}`")
    score = metadata.get("score")
    if score not in (None, ""):
        parts.append(f"Score {_format_score(score)}")
    return ", ".join(parts) or "-"


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


def _preview_html(settings: Settings, token: str | None) -> str:
    if not token or not settings.openwebui_proxy_shared_secret:
        return _preview_unavailable_html()
    try:
        payload = verify_preview_token(token, settings.openwebui_proxy_shared_secret)
    except ValueError:
        return _preview_unavailable_html()
    title = escape(str(payload.get("document_name") or "Quelle"))
    snippet_text = _clean_source_snippet(payload.get("snippet") or "")
    snippet = escape(snippet_text)
    dataset = escape(str(payload.get("dataset_name") or payload.get("dataset_id") or ""))
    document_id = escape(str(payload.get("document_id") or ""))
    chunk = escape(str(payload.get("chunk_id") or ""))
    citation = escape(str(payload.get("citation_label") or "Quelle"))
    page = escape(str(payload.get("page") or ""))
    section = escape(str(payload.get("section") or ""))
    line = escape(str(payload.get("line") or ""))
    repo_id = escape(str(payload.get("repo_id") or ""))
    source_path = escape(str(payload.get("source_path") or ""))
    file_type = escape(str(payload.get("file_type") or ""))
    mime_type = escape(str(payload.get("mime_type") or ""))
    score = _format_score(payload.get("score"))
    score_text = escape(score or "nicht angegeben")
    original_url = str(payload.get("original_url") or "")
    original_link = (
        f'<a class="button primary" href="{escape(original_url, quote=True)}" target="_blank" rel="noreferrer">Original öffnen</a>'
        if original_url
        else ""
    )
    position_json = json.dumps(payload.get("position"), ensure_ascii=False, default=str)
    position = escape(position_json)
    debug_payload = dict(payload)
    debug_payload["snippet"] = snippet_text
    raw_json = escape(json.dumps(debug_payload, ensure_ascii=False, indent=2, default=str))
    copy_snippet = escape(snippet_text, quote=True)
    chips = [f"<span>{citation}</span>"]
    if page:
        chips.append(f"<span>Seite {page}</span>")
    if score:
        chips.append(f"<span>Relevanz {score_text}</span>")
    if file_type:
        chips.append(f"<span>{file_type.upper()}</span>")
    details = [
        ("Quellpfad", source_path),
        ("Dateityp", file_type),
        ("MIME-Type", mime_type),
        ("Fundstelle", " · ".join(part for part in (f"Seite {page}" if page else "", f"Abschnitt {section}" if section else "", f"Zeile {line}" if line else "") if part)),
        ("Relevanz", score_text),
    ]
    debug_details = [
        ("Dataset", dataset),
        ("Dokument-ID", document_id),
        ("Seafile-Repo", repo_id),
        ("Chunk-ID", chunk),
        ("Abschnitt", section),
        ("Zeile", line),
        ("Position", f"<code>{position}</code>" if position not in ("null", '""') else ""),
    ]
    details_html = "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in details if value
    )
    debug_html = "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in debug_details if value
    )
    if not snippet:
        snippet = "Kein Textauszug in der RAGFlow-Referenz vorhanden."
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>"
        ":root{color-scheme:light dark;--bg:#f8fafc;--panel:#ffffff;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;--accent:#0f766e;--accent-strong:#0d9488;--soft:#f1f5f9;--code:#eef2f7;--mark:#fff2a8}"
        "@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--panel:#111827;--text:#f8fafc;--muted:#94a3b8;--border:#334155;--accent:#2dd4bf;--accent-strong:#14b8a6;--soft:#1e293b;--code:#0b1220;--mark:#5b4b15}}"
        "[data-theme=light]{color-scheme:light;--bg:#f8fafc;--panel:#ffffff;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;--accent:#0f766e;--accent-strong:#0d9488;--soft:#f1f5f9;--code:#eef2f7;--mark:#fff2a8}"
        "[data-theme=dark]{color-scheme:dark;--bg:#0f172a;--panel:#111827;--text:#f8fafc;--muted:#94a3b8;--border:#334155;--accent:#2dd4bf;--accent-strong:#14b8a6;--soft:#1e293b;--code:#0b1220;--mark:#5b4b15}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.55}"
        "main{max-width:1120px;margin:0 auto;padding:24px 18px 42px}.hero{display:grid;gap:14px;padding:22px 24px;border:1px solid var(--border);border-radius:8px;background:var(--panel);box-shadow:0 10px 26px rgba(15,23,42,.08)}"
        ".topbar{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.eyebrow{margin:0;color:var(--accent);font-size:.78rem;font-weight:700;text-transform:uppercase}h1{margin:0;font-size:clamp(1.35rem,2.7vw,2.05rem);line-height:1.16;letter-spacing:0;overflow-wrap:anywhere}.path{margin:0;color:var(--muted);overflow-wrap:anywhere}"
        ".chips,.actions,.tabs{display:flex;flex-wrap:wrap;gap:8px}.chips span{border:1px solid var(--border);border-radius:999px;padding:5px 10px;color:var(--muted);font-size:.86rem;background:var(--soft)}"
        ".button,.tab{display:inline-flex;align-items:center;min-height:36px;border:1px solid var(--border);border-radius:7px;padding:7px 11px;background:var(--panel);color:var(--text);text-decoration:none;font-weight:650;cursor:pointer}.button.primary{background:var(--accent-strong);border-color:var(--accent-strong);color:white}.button:hover,.tab:hover{border-color:var(--accent)}"
        ".tabs{margin-top:16px}.tab[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:white}.panel{display:none;margin-top:12px;border:1px solid var(--border);border-radius:8px;background:var(--panel);overflow:hidden}.panel.active{display:block}"
        ".section-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0;padding:14px 16px;border-bottom:1px solid var(--border);font-size:1rem}.hit{margin:0;padding:20px 22px;white-space:pre-wrap;overflow:auto;background:var(--soft);font-size:1rem;line-height:1.72}.hit mark{background:var(--mark);color:var(--text);padding:1px 2px;border-radius:3px}"
        "dl{margin:0;padding:12px 18px}dl div{display:grid;grid-template-columns:132px minmax(0,1fr);gap:14px;padding:9px 0;border-bottom:1px solid var(--border)}dl div:last-child{border-bottom:0}dt{color:var(--muted);font-size:.82rem}dd{margin:0;overflow-wrap:anywhere;font-weight:600}code,pre.raw{background:var(--code);border-radius:6px}code{padding:2px 5px}pre.raw{margin:0;padding:16px;white-space:pre-wrap;overflow:auto;font-size:.85rem}"
        ".muted{padding:20px 22px;color:var(--muted)}@media(max-width:760px){main{padding:14px 10px 30px}.hero{padding:18px}.topbar{display:grid}.actions .button{flex:1 1 auto;justify-content:center}dl div{grid-template-columns:1fr;gap:2px}}"
        "</style></head><body><main>"
        "<section class=\"hero\">"
        "<div class=\"topbar\"><p class=\"eyebrow\">RAGFlow Quellenvorschau</p><button class=\"button\" id=\"theme-toggle\" type=\"button\">Theme wechseln</button></div>"
        f"<h1>{title}</h1><p class=\"path\">{source_path or citation}</p><div class=\"chips\">{''.join(chips)}</div>"
        f"<div class=\"actions\">{original_link}<button class=\"button\" type=\"button\" data-copy=\"{copy_snippet}\">Auszug kopieren</button><button class=\"button\" type=\"button\" data-copy-url>Link kopieren</button></div>"
        "</section>"
        "<nav class=\"tabs\" aria-label=\"Quellenansicht\">"
        "<button class=\"tab\" type=\"button\" data-tab=\"hit\" aria-selected=\"true\">Treffer</button>"
        "<button class=\"tab\" type=\"button\" data-tab=\"context\" aria-selected=\"false\">Kontext</button>"
        "<button class=\"tab\" type=\"button\" data-tab=\"meta\" aria-selected=\"false\">Metadaten</button>"
        "<button class=\"tab\" type=\"button\" data-tab=\"debug\" aria-selected=\"false\">Debug</button>"
        "</nav>"
        f"<section class=\"panel active\" data-panel=\"hit\"><h2 class=\"section-title\">Gefundener Auszug</h2><pre class=\"hit\"><mark>{snippet}</mark></pre></section>"
        "<section class=\"panel\" data-panel=\"context\"><h2 class=\"section-title\">Kontext</h2><p class=\"muted\">RAGFlow hat für diese Quelle keinen zusätzlichen Vorher-/Nachher-Kontext geliefert. Der Treffer selbst wird unverändert im Tab Treffer angezeigt.</p></section>"
        f"<section class=\"panel\" data-panel=\"meta\"><h2 class=\"section-title\">Nutzbare Metadaten</h2><dl>{details_html}</dl></section>"
        f"<section class=\"panel\" data-panel=\"debug\"><h2 class=\"section-title\">Technische Details</h2><dl>{debug_html}</dl><pre class=\"raw\">{raw_json}</pre></section>"
        "<script>"
        "const root=document.documentElement;const saved=localStorage.getItem('source-preview-theme');if(saved){root.dataset.theme=saved;}"
        "document.getElementById('theme-toggle').addEventListener('click',()=>{const next=root.dataset.theme==='dark'?'light':'dark';root.dataset.theme=next;localStorage.setItem('source-preview-theme',next);});"
        "document.querySelectorAll('.tab').forEach(tab=>tab.addEventListener('click',()=>{const id=tab.dataset.tab;document.querySelectorAll('.tab').forEach(item=>item.setAttribute('aria-selected',String(item===tab)));document.querySelectorAll('.panel').forEach(panel=>panel.classList.toggle('active',panel.dataset.panel===id));}));"
        "document.querySelectorAll('[data-copy]').forEach(btn=>btn.addEventListener('click',async()=>{await navigator.clipboard.writeText(btn.dataset.copy||'');btn.textContent='Kopiert';setTimeout(()=>btn.textContent='Auszug kopieren',1400);}));"
        "document.querySelectorAll('[data-copy-url]').forEach(btn=>btn.addEventListener('click',async()=>{await navigator.clipboard.writeText(location.href);btn.textContent='Kopiert';setTimeout(()=>btn.textContent='Link kopieren',1400);}));"
        "</script></main></body></html>"
    )


def _preview_unavailable_html() -> str:
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Quelle nicht verfügbar</title>"
        "<style>body{font-family:Segoe UI,system-ui,sans-serif;margin:0;display:grid;min-height:100vh;place-items:center;background:#f7f8fb;color:#172033}"
        "main{max-width:560px;padding:28px;border:1px solid #d9e0ea;border-radius:8px;background:white}h1{margin-top:0}</style>"
        "</head><body><main><h1>Quelle nicht verfügbar</h1><p>Der Quellenlink ist ungültig oder der Connector-Proxy ist nicht für Vorschauen konfiguriert.</p></main></body></html>"
    )
