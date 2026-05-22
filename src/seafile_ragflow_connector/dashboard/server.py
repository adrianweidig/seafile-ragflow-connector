from __future__ import annotations

# ruff: noqa: E501
import hmac
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from html import escape, unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.export import audit_export_filename, build_audit_workbook
from seafile_ragflow_connector.dashboard.health import collect_dashboard_health
from seafile_ragflow_connector.dashboard.store import DashboardEventStore
from seafile_ragflow_connector.dashboard.ui import DASHBOARD_HTML
from seafile_ragflow_connector.openwebui.sources import (
    annotate_answer_citations,
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
                model="model",
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
    answer = annotate_answer_citations(extract_answer(result), sources)
    if sources and "## Gefundene Quellen" not in answer:
        answer = (answer.strip() + "\n\n" if answer.strip() else "") + _sources_markdown(sources)
    return {"answer": answer, "sources": sources, "citations_emitted": True}


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
    if not sources:
        return "Keine passenden Quellen gefunden."
    lines = ["## Gefundene Quellen", ""]
    for index, source in enumerate(sources, start=1):
        name = source.get("name") or "Quelle"
        snippet = _clean_source_snippet(source.get("snippet") or "")
        locator = _source_locator(source)
        line = f"{index}. **{_markdown_plain(str(name))}**"
        if locator != "-":
            line += f" - {_markdown_plain(locator)}"
        lines.append(line)
        if not snippet:
            continue
        lines.append(f"   > {_compact_markdown_text(snippet, 360)}")
    return "\n".join(lines)


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
    clean = str(text or "")
    clean = re.sub(r"(?is)<(script|style).*?</\1>", " ", clean)
    clean = re.sub(r"(?i)</t[dh]>\s*<t[dh][^>]*>", " | ", clean)
    clean = re.sub(r"(?i)</tr>\s*<tr[^>]*>", "\n", clean)
    clean = re.sub(r"(?i)<br\s*/?>", "\n", clean)
    clean = re.sub(r"(?s)<[^>]+>", " ", clean)
    clean = unescape(clean)
    clean = "\n".join(" ".join(line.split()) for line in clean.splitlines())
    return "\n".join(line for line in clean.splitlines() if line).strip()


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
    snippet_text = str(payload.get("snippet") or "").strip()
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
    original_url = str(payload.get("original_url") or "")
    original_link = (
        f'<a class="button primary" href="{escape(original_url, quote=True)}" target="_blank" rel="noreferrer">Original öffnen</a>'
        if original_url
        else ""
    )
    position_json = json.dumps(payload.get("position"), ensure_ascii=False, default=str)
    position = escape(position_json)
    chips = [f"<span>{citation}</span>"]
    if page:
        chips.append(f"<span>Seite {page}</span>")
    if chunk:
        chips.append(f"<span>Chunk {chunk[:12]}</span>")
    details = [
        ("Dataset", dataset),
        ("Dokument-ID", document_id),
        ("Seafile-Repo", repo_id),
        ("Quellpfad", source_path),
        ("Abschnitt", section),
        ("Zeile", line),
        ("Position", f"<code>{position}</code>" if position not in ("null", '""') else ""),
    ]
    details_html = "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in details if value
    )
    if not snippet:
        snippet = "Kein Textauszug in der RAGFlow-Referenz vorhanden."
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>"
        ":root{color-scheme:light dark;--bg:#f7f8fb;--panel:#ffffff;--text:#172033;--muted:#5d687a;--line:#d9e0ea;--accent:#0f766e;--accent-2:#2563eb;--code:#eef3f8}"
        "@media(prefers-color-scheme:dark){:root{--bg:#111827;--panel:#172033;--text:#f8fafc;--muted:#b6c0ce;--line:#2c3748;--accent:#2dd4bf;--accent-2:#93c5fd;--code:#0f172a}}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.55}"
        "main{max-width:1180px;margin:0 auto;padding:32px 22px 48px}.hero{display:grid;gap:18px;padding:26px 28px;border:1px solid var(--line);border-radius:8px;background:var(--panel);box-shadow:0 12px 28px rgba(15,23,42,.08)}"
        ".eyebrow{margin:0;color:var(--accent);font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase}h1{margin:0;font-size:clamp(1.55rem,3vw,2.4rem);line-height:1.14;letter-spacing:0;overflow-wrap:anywhere}"
        ".chips{display:flex;flex-wrap:wrap;gap:8px}.chips span{border:1px solid var(--line);border-radius:999px;padding:5px 10px;color:var(--muted);font-size:.86rem;background:color-mix(in srgb,var(--panel),var(--bg) 42%)}"
        ".actions{display:flex;flex-wrap:wrap;gap:10px}.button{display:inline-flex;align-items:center;min-height:38px;border:1px solid var(--line);border-radius:7px;padding:8px 12px;color:var(--text);text-decoration:none;font-weight:650}.button.primary{background:var(--accent);border-color:var(--accent);color:white}"
        ".grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;margin-top:18px}.card{border:1px solid var(--line);border-radius:8px;background:var(--panel);overflow:hidden}.card h2{margin:0;padding:16px 18px;border-bottom:1px solid var(--line);font-size:1rem}"
        "pre{margin:0;padding:20px 22px;white-space:pre-wrap;overflow:auto;background:var(--code);font-family:ui-monospace,SFMono-Regular,Consolas,Menlo,monospace;font-size:.94rem;line-height:1.65}"
        "dl{margin:0;padding:12px 18px}dl div{display:grid;grid-template-columns:108px minmax(0,1fr);gap:12px;padding:9px 0;border-bottom:1px solid var(--line)}dl div:last-child{border-bottom:0}dt{color:var(--muted);font-size:.82rem}dd{margin:0;overflow-wrap:anywhere;font-weight:600}code{background:var(--code);padding:2px 5px;border-radius:5px}"
        ".empty{padding:20px 22px;color:var(--muted)}@media(max-width:820px){main{padding:18px 12px 34px}.hero{padding:20px}.grid{grid-template-columns:1fr}dl div{grid-template-columns:1fr;gap:2px}}"
        "</style></head><body><main>"
        f"<section class=\"hero\"><p class=\"eyebrow\">RAGFlow Quellenvorschau</p><h1>{title}</h1><div class=\"chips\">{''.join(chips)}</div><div class=\"actions\">{original_link}</div></section>"
        "<section class=\"grid\">"
        f"<article class=\"card\"><h2>Fundstelle</h2><pre>{snippet}</pre></article>"
        f"<aside class=\"card\"><h2>Metadaten</h2><dl>{details_html}</dl></aside>"
        "</section></main></body></html>"
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
