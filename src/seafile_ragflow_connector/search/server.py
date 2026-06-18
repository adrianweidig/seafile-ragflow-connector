from __future__ import annotations

import html
import json
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx
import structlog

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import SearchServiceSettings
from seafile_ragflow_connector.openwebui.sources import extract_references, sign_preview_payload
from seafile_ragflow_connector.search.ui import SEARCH_HTML
from seafile_ragflow_connector.sources.evidence import (
    EvidenceHit,
    build_text_fragment_url,
    locator_quality,
    open_url_kind,
    render_preview_html,
    score_value,
)

SEARCH_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "form-action 'self'"
)

SOURCE_PATH_LABEL = "Source path:"
SOURCE_PATH_HASH_LABEL = "Source path hash:"
SOURCE_BEGIN_MARKER = "----- BEGIN SOURCE CONTENT -----"
SOURCE_END_MARKER = "----- END SOURCE CONTENT -----"


class SearchBindError(RuntimeError):
    pass


class SearchPermissionError(PermissionError):
    pass


@dataclass
class SearchServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@dataclass(frozen=True)
class SearchServiceContext:
    settings: SearchServiceSettings
    started_at: datetime


@dataclass(frozen=True)
class SearchUser:
    username: str | None
    email: str | None
    display_name: str | None

    @property
    def display(self) -> str:
        return self.display_name or self.email or self.username or "Unbekannter Nutzer"


def start_search_server(
    context: SearchServiceContext | SearchServiceSettings,
    *,
    background: bool = True,
) -> SearchServerHandle:
    service_context = (
        context
        if isinstance(context, SearchServiceContext)
        else SearchServiceContext(settings=context, started_at=datetime.now(UTC))
    )
    handler_class = _build_handler(service_context)
    try:
        server = ThreadingHTTPServer(
            (
                service_context.settings.search_service_host,
                service_context.settings.search_service_port,
            ),
            handler_class,
        )
    except OSError as exc:
        raise SearchBindError(
            "search service port could not be bound: "
            f"{service_context.settings.search_service_host}:"
            f"{service_context.settings.search_service_port}: {exc}"
        ) from exc
    thread = threading.Thread(target=server.serve_forever, name="connector-search", daemon=True)
    if background:
        thread.start()
    return SearchServerHandle(server=server, thread=thread)


def serve_search_forever(context: SearchServiceContext) -> None:
    handle = start_search_server(context, background=False)
    structlog.get_logger(__name__).info(
        "search_service.started",
        host=context.settings.search_service_host,
        port=context.settings.search_service_port,
    )
    try:
        handle.server.serve_forever()
    finally:
        handle.server.server_close()


def _build_handler(context: SearchServiceContext) -> type[BaseHTTPRequestHandler]:
    class SearchRequestHandler(BaseHTTPRequestHandler):
        server_version = "SeafileRAGFlowConnectorSearch/1.0"

        def do_GET(self) -> None:  # noqa: N802
            try:
                if self.path in {"/", "/search"}:
                    self._send_html(SEARCH_HTML)
                    return
                if self.path == "/favicon.ico":
                    self.send_response(HTTPStatus.NO_CONTENT.value)
                    self._send_security_headers()
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path == "/health":
                    self._send_json(
                        {
                            "status": "ok",
                            "service": "connector-search",
                            "started_at": context.started_at.isoformat(),
                        }
                    )
                    return
                parsed = urlparse(self.path)
                if parsed.path == "/api/search/source/preview":
                    params = parse_qs(parsed.query)
                    self._send_html(
                        render_preview_html(
                            _one(params, "token"),
                            context.settings.effective_search_source_preview_secret,
                            language=context.settings.connector_language or "de",
                        )
                    )
                    return
                if self.path == "/api/search/profiles":
                    user = _user_from_headers(context.settings, self.headers)
                    self._send_json(_handle_profiles(context.settings, user))
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except SearchPermissionError as exc:
                self._send_json(
                    {"error": "forbidden", "message": str(exc) or "Kein Zugriff."},
                    status=HTTPStatus.FORBIDDEN,
                )
            except ValueError as exc:
                self._send_json(
                    {"error": "bad request", "message": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except Exception as exc:
                structlog.get_logger(__name__).warning("search.request_failed", error=str(exc))
                self._send_json(
                    {"error": "search failed", "message": "Die Suche konnte nicht geladen werden."},
                    status=HTTPStatus.BAD_GATEWAY,
                )

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path == "/api/search/query":
                    user = _user_from_headers(context.settings, self.headers)
                    self._send_json(_handle_query(context.settings, user, self._json_body()))
                    return
                if self.path == "/api/search/chat":
                    user = _user_from_headers(context.settings, self.headers)
                    self._send_json(_handle_chat(context.settings, user, self._json_body()))
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except SearchPermissionError as exc:
                self._send_json(
                    {"error": "forbidden", "message": str(exc) or "Kein Zugriff."},
                    status=HTTPStatus.FORBIDDEN,
                )
            except ValueError as exc:
                self._send_json(
                    {"error": "bad request", "message": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except (ApiError, httpx.RequestError) as exc:
                structlog.get_logger(__name__).warning(
                    "search.upstream_failed",
                    error_class=exc.__class__.__name__,
                )
                self._send_json(
                    {
                        "error": "upstream failed",
                        "message": "RAGFlow ist aktuell nicht erreichbar.",
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
            except Exception as exc:
                structlog.get_logger(__name__).warning("search.request_failed", error=str(exc))
                self._send_json(
                    {
                        "error": "search failed",
                        "message": "Die Suche konnte nicht ausgeführt werden.",
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args: Any) -> None:
            structlog.get_logger(__name__).debug("search.http_access", message=format % args)

        def _send_json(
            self,
            payload: dict[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html_text: str) -> None:
            body = html_text.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._send_security_headers(include_csp=True)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_security_headers(self, *, include_csp: bool = False) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if include_csp:
                self.send_header("Content-Security-Policy", SEARCH_CONTENT_SECURITY_POLICY)

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

    return SearchRequestHandler


def _handle_profiles(settings: SearchServiceSettings, user: SearchUser) -> dict[str, Any]:
    profiles = _authz_profiles(settings, user)
    return {"profiles": profiles, "user_display": user.display}


def _handle_query(
    settings: SearchServiceSettings,
    user: SearchUser,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not settings.search_enable_retrieval_mode:
        raise ValueError("Retrieval-Modus ist deaktiviert.")
    question = _required_text(payload, "question")
    profile_ids = _profile_ids(payload, settings)
    if not profile_ids:
        raise SearchPermissionError("Wähle mindestens eine Bibliothek aus.")
    top_k = _bounded_top_k(payload.get("top_k"), settings)
    filtered = _authz_filter_profiles(settings, user, profile_ids)
    allowed = filtered["allowed"]
    denied = filtered["denied"]
    if not allowed:
        raise SearchPermissionError("Kein Zugriff auf diese Bibliothek.")
    results = _retrieve_allowed_profiles(settings, allowed, question=question, top_k=top_k)
    return {
        "query": question,
        "results": results,
        "diagnostics": {
            "profiles_allowed": len(allowed),
            "profiles_denied": len(denied),
            "retrieval_mode": "multi_dataset" if len(allowed) > 1 else "single_dataset",
        },
    }


def _handle_chat(
    settings: SearchServiceSettings,
    user: SearchUser,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not settings.search_enable_chat_mode:
        raise ValueError("Antwortmodus ist deaktiviert.")
    response = _handle_query(settings, user, payload)
    sources = response["results"]
    answer_text = _compose_answer_from_sources(str(response["query"]), sources)
    response["answer"] = {
        "text": answer_text,
        "mode": "retrieval_summary",
        "citations": _answer_citations(sources, settings),
    }
    response["sources"] = sources
    response["diagnostics"]["retrieval_mode"] = "answer_with_sources"
    return response


def _authz_profiles(settings: SearchServiceSettings, user: SearchUser) -> list[dict[str, Any]]:
    _require_user_identity(user)
    headers = _authz_headers(settings, user)
    with httpx.Client(base_url=settings.search_authz_base_url, timeout=20.0) as client:
        response = client.get("/api/authz/profiles", headers=headers)
        if response.status_code in {401, 403}:
            raise SearchPermissionError("Kein Zugriff auf diese Bibliothek.")
        response.raise_for_status()
        data = response.json()
    profiles = data.get("profiles") if isinstance(data, dict) else None
    return list(profiles or [])


def _authz_filter_profiles(
    settings: SearchServiceSettings,
    user: SearchUser,
    profile_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    _require_user_identity(user)
    payload = {
        "user": {"username": user.username, "email": user.email},
        "profile_ids": profile_ids,
    }
    with httpx.Client(base_url=settings.search_authz_base_url, timeout=20.0) as client:
        response = client.post(
            "/api/authz/filter-profiles",
            json=payload,
            headers=_authz_headers(settings, user),
        )
        if response.status_code in {401, 403}:
            raise SearchPermissionError("Kein Zugriff auf diese Bibliothek.")
        response.raise_for_status()
        data = response.json()
    return {
        "allowed": list(data.get("allowed") or []),
        "denied": list(data.get("denied") or []),
    }


def _authz_headers(settings: SearchServiceSettings, user: SearchUser) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.search_authz_shared_secret}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if user.username:
        headers["X-Authz-Username"] = user.username
    if user.email:
        headers["X-Authz-Email"] = user.email
    return headers


def _retrieve_allowed_profiles(
    settings: SearchServiceSettings,
    allowed: list[dict[str, Any]],
    *,
    question: str,
    top_k: int,
) -> list[dict[str, Any]]:
    client = RAGFlowClient(
        settings.search_ragflow_base_url,
        settings.search_ragflow_api_key,
        verify=settings.search_ragflow_httpx_verify,
    )
    try:
        results: list[dict[str, Any]] = []
        for profile in allowed:
            dataset_id = str(profile.get("ragflow_dataset_id") or "")
            if not dataset_id:
                continue
            raw = client.retrieve_chunks(
                dataset_id=dataset_id,
                question=question,
                top_k=top_k,
                page_size=top_k,
            )
            results.extend(_search_results_from_ragflow(raw, profile, settings=settings))
    finally:
        client.close()
    return _finalize_search_results(
        _deduplicate_results(results)[:top_k],
        settings=settings,
    )


def _search_results_from_ragflow(
    payload: Any,
    profile: dict[str, Any],
    *,
    settings: SearchServiceSettings | None = None,
) -> list[dict[str, Any]]:
    dataset_name = str(profile.get("display_name") or profile.get("repo_id") or "Bibliothek")
    dataset_id = str(profile.get("ragflow_dataset_id") or "")
    repo_id = str(profile.get("repo_id") or "")
    document_names_by_id = _document_names_by_id(payload)
    items: list[dict[str, Any]] = []
    for raw in extract_references(payload):
        metadata = _metadata(raw)
        document_id = _first_text(raw, metadata, "document_id", "doc_id")
        document_name = (
            _first_text(
                raw,
                metadata,
                "document_name",
                "docnm_kwd",
                "document_keyword",
                "doc_name",
                "name",
                "title",
            )
            or document_names_by_id.get(document_id or "")
        )
        source_path = _first_text(raw, metadata, "source_path", "path", "file_path", "source")
        raw_snippet = _clean_snippet(
            _first_text(
                raw,
                metadata,
                "content",
                "text",
                "snippet",
                "content_with_weight",
                "highlight",
            )
            or ""
        )
        embedded_source_path, snippet = _extract_projected_source(raw_snippet)
        if embedded_source_path:
            source_path = embedded_source_path
        document_name = _friendly_document_name(document_name, source_path)
        if not source_path and document_name:
            source_path = f"/{dataset_name}/{document_name}"
        score = _score_value(_first_value(raw, metadata, "score", "similarity", "weight"))
        chunk_id = _first_text(raw, metadata, "id", "chunk_id", "chunkId")
        page = _first_value(raw, metadata, "page", "page_number") or _first_page(
            _first_value(raw, metadata, "positions", "position")
        )
        line = _first_value(raw, metadata, "line", "line_number")
        line_start = _first_value(raw, metadata, "line_start", "start_line") or line
        line_end = _first_value(raw, metadata, "line_end", "end_line")
        section = _first_value(raw, metadata, "section", "section_title", "heading")
        position = _first_value(raw, metadata, "positions", "position")
        open_url = _safe_http_url(
            _first_text(
                raw,
                metadata,
                "original_url",
                "url",
                "preview_url",
                "web_url",
                "seafile_url",
                "seafile_web_url",
                "source_url",
                "document_url",
            )
        )
        if open_url is None and settings is not None:
            open_url = _seafile_file_url(
                settings,
                repo_id=repo_id,
                source_path=source_path,
                page=page,
            )
        quality = locator_quality(
            page=page,
            section=section,
            line_start=line_start,
            line_end=line_end,
            position=position,
            chunk_id=chunk_id,
            document_id=document_id,
            document_name=document_name,
            source_path=source_path,
            snippet=snippet,
        )
        items.append(
            {
                "dataset_name": dataset_name,
                "repo_id": repo_id,
                "ragflow_dataset_id": dataset_id,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "document_name": document_name,
                "source_path": source_path or "",
                "snippet": snippet,
                "page": page,
                "line_start": line_start,
                "line_end": line_end,
                "section": section,
                "position": position,
                "locator_quality": quality,
                "score": score,
                "preview_url": "",
                "open_url": open_url,
            }
        )
    items.sort(key=lambda item: (item["score"] is None, -(item["score"] or 0.0)))
    return items


def _document_names_by_id(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    doc_aggs = payload.get("doc_aggs")
    if not isinstance(doc_aggs, list):
        return {}
    names: dict[str, str] = {}
    for item in doc_aggs:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("doc_id") or item.get("document_id") or item.get("id")
        doc_name = item.get("doc_name") or item.get("document_name") or item.get("name")
        if doc_id not in (None, "") and doc_name not in (None, ""):
            names[str(doc_id)] = str(doc_name)
    return names


def _deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    sorted_results = sorted(
        results,
        key=lambda item: (item["score"] is None, -(item["score"] or 0.0)),
    )
    for result in sorted_results:
        key = (
            str(result.get("ragflow_dataset_id") or ""),
            str(result.get("document_name") or ""),
            str(result.get("source_path") or ""),
            str(result.get("snippet") or "")[:180],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _finalize_search_results(
    results: list[dict[str, Any]],
    *,
    settings: SearchServiceSettings,
) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for rank, result in enumerate(results, start=1):
        source_id = f"S{rank}"
        open_url = _safe_http_url(str(result.get("open_url") or "")) or None
        text_fragment_url = None
        if result.get("page") in (None, ""):
            text_fragment_url = build_text_fragment_url(
                open_url,
                str(result.get("snippet") or ""),
                enabled=settings.search_text_fragment_links_enabled,
            )
        kind = open_url_kind(
            text_fragment_url or open_url,
            page=result.get("page"),
            text_fragment_url=text_fragment_url,
        )
        best_open_url = text_fragment_url or open_url
        hit = EvidenceHit(
            source_id=source_id,
            citation_label=source_id,
            rank=rank,
            document_name=str(result.get("document_name") or "Dokument"),
            dataset_name=str(result.get("dataset_name") or "Bibliothek"),
            repo_id=_optional_text(result.get("repo_id")),
            ragflow_dataset_id=_optional_text(result.get("ragflow_dataset_id")),
            source_path=_optional_text(result.get("source_path")),
            snippet=_compact(result.get("snippet"), settings.search_result_snippet_context_chars),
            page=result.get("page"),
            line_start=result.get("line_start"),
            line_end=result.get("line_end"),
            section=result.get("section"),
            chunk_id=_optional_text(result.get("chunk_id")),
            document_id=_optional_text(result.get("document_id")),
            score=score_value(result.get("score")),
            match_type=str(result.get("match_type") or "semantic"),
            source_role=str(result.get("source_role") or "related"),
            locator_quality=str(result.get("locator_quality") or "unknown"),
            open_url=best_open_url,
            open_url_kind=kind,
            text_fragment_url=text_fragment_url,
        )
        preview_url = _search_preview_url(hit, settings)
        hit = replace(hit, preview_url=preview_url)
        finalized.append(hit.to_search_result())
    return finalized


def _search_preview_url(hit: EvidenceHit, settings: SearchServiceSettings) -> str | None:
    if not settings.search_source_preview_enabled:
        return None
    token = sign_preview_payload(
        hit.preview_payload(),
        settings.effective_search_source_preview_secret,
    )
    return f"/api/search/source/preview?token={quote(token)}"


def _answer_citations(
    sources: list[dict[str, Any]],
    settings: SearchServiceSettings,
) -> list[dict[str, Any]]:
    citations = []
    for source in sources[: settings.search_answer_max_sources]:
        citations.append(
            {
                "label": source.get("citation_label") or source.get("source_id"),
                "source_id": source.get("source_id"),
                "document_name": source.get("document_name"),
                "dataset_name": source.get("dataset_name"),
                "location": (source.get("locator") or {}).get("label"),
                "preview_url": source.get("preview_url"),
                "open_url": source.get("open_url"),
            }
        )
    return citations


def _compose_answer_from_sources(question: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "Ich habe in den freigegebenen Bibliotheken keine belastbaren Quellen gefunden."
    count = len(sources)
    library_names = sorted({str(source.get("dataset_name") or "Bibliothek") for source in sources})
    libraries = ", ".join(library_names[:3])
    if len(library_names) > 3:
        libraries += f" und {len(library_names) - 3} weitere"
    return (
        f"Zur Frage \"{question}\" wurden {count} passende Quelle"
        f"{'' if count == 1 else 'n'} gefunden. "
        "Ich habe noch keinen separaten KI-Antworttext generiert; die belastbaren "
        "Fundstellen stehen unten als Quellenkarten und sind direkt prüfbar"
        f"{f' aus {libraries}' if libraries else ''}."
    )


def _user_from_headers(settings: SearchServiceSettings, headers: Any) -> SearchUser:
    username = _clean_header(headers.get(settings.search_trusted_username_header))
    email = _clean_header(headers.get(settings.search_trusted_email_header))
    display_name = _clean_header(headers.get(settings.search_trusted_display_name_header))
    return SearchUser(username=username, email=email, display_name=display_name)


def _require_user_identity(user: SearchUser) -> None:
    if not (user.email or user.username):
        raise SearchPermissionError("Nutzeridentität fehlt.")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value in (None, ""):
        raise ValueError(f"{key} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _profile_ids(payload: dict[str, Any], settings: SearchServiceSettings) -> list[str]:
    raw = payload.get("profile_ids")
    if not isinstance(raw, list):
        raise ValueError("profile_ids must be a list")
    profile_ids = [str(item).strip() for item in raw if str(item).strip()]
    if len(profile_ids) > settings.search_max_selected_profiles:
        raise ValueError("too many selected profiles")
    return profile_ids


def _bounded_top_k(value: Any, settings: SearchServiceSettings) -> int:
    try:
        top_k = int(value or settings.search_default_top_k)
    except (TypeError, ValueError):
        top_k = settings.search_default_top_k
    return max(1, min(settings.search_max_top_k, top_k))


def _metadata(raw: dict[str, Any]) -> dict[str, Any]:
    metadata = raw.get("source_metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata = raw.get("metadata")
    if isinstance(metadata, list) and metadata and isinstance(metadata[0], dict):
        return metadata[0]
    if isinstance(metadata, dict):
        return metadata
    return {}


def _first_text(raw: dict[str, Any], metadata: dict[str, Any], *keys: str) -> str | None:
    value = _first_value(raw, metadata, *keys)
    if value in (None, ""):
        return None
    return str(value)


def _first_value(raw: dict[str, Any], metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_page(position: Any) -> Any:
    if not isinstance(position, list) or not position:
        return None
    first = position[0]
    if isinstance(first, list) and first:
        return first[0]
    return None


def _score_value(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score = score / 100
    return max(0.0, min(1.0, score))


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return value.strip()
    return None


def _extract_projected_source(value: str) -> tuple[str | None, str]:
    body = value.strip()
    source_path = _embedded_source_path(body)

    begin = body.find(SOURCE_BEGIN_MARKER)
    if begin >= 0:
        body = body[begin + len(SOURCE_BEGIN_MARKER) :].strip()
    elif body.startswith(SOURCE_PATH_LABEL):
        lines = [
            line
            for line in body.splitlines()
            if not line.startswith(SOURCE_PATH_LABEL)
            and not line.startswith(SOURCE_PATH_HASH_LABEL)
        ]
        body = "\n".join(lines).strip()

    end = body.find(SOURCE_END_MARKER)
    if end >= 0:
        body = body[:end].strip()
    return source_path, body


def _embedded_source_path(value: str) -> str | None:
    start = value.find(SOURCE_PATH_LABEL)
    if start < 0:
        return None
    start += len(SOURCE_PATH_LABEL)
    end = len(value)
    for marker in (SOURCE_PATH_HASH_LABEL, SOURCE_BEGIN_MARKER, "\n"):
        marker_start = value.find(marker, start)
        if marker_start >= 0:
            end = min(end, marker_start)
    source_path = value[start:end].strip()
    return _normalize_source_path(source_path)


def _normalize_source_path(value: str | None) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    clean = clean.replace("\\", "/")
    return clean if clean.startswith("/") else f"/{clean}"


def _friendly_document_name(document_name: str | None, source_path: str | None) -> str:
    if source_path:
        path_name = source_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip()
        if path_name:
            return path_name
    clean = str(document_name or "").strip()
    if "__" in clean:
        clean = clean.split("__", 1)[1].strip()
    for suffix in (".md.txt", ".pdf.txt", ".docx.txt", ".xlsx.txt", ".pptx.txt", ".html.txt"):
        if clean.lower().endswith(suffix):
            return clean[: -len(".txt")]
    return clean or "Dokument"


def _seafile_file_url(
    settings: SearchServiceSettings,
    *,
    repo_id: str,
    source_path: str | None,
    page: Any,
) -> str | None:
    template = settings.effective_search_seafile_file_url_template
    if not template or not repo_id or not source_path:
        return None
    path_for_file_url = source_path if source_path.startswith("/") else f"/{source_path}"
    page_text = "" if page in (None, "") else str(page)
    values = {
        "base": (settings.search_seafile_public_base_url or "").rstrip("/"),
        "repo_id": repo_id,
        "repo_id_quoted": quote(repo_id, safe=""),
        "path": source_path,
        "path_quoted": quote(path_for_file_url, safe="/"),
        "path_query": quote(source_path, safe=""),
        "path_no_leading_slash": source_path.lstrip("/"),
        "path_no_leading_slash_quoted": quote(source_path.lstrip("/"), safe="/"),
        "page": page_text,
        "page_fragment": f"#page={quote(page_text, safe='')}" if page_text else "",
    }
    try:
        return _safe_http_url(template.format(**values))
    except (KeyError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _one(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def _clean_header(value: str | None) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def _clean_snippet(value: str) -> str:
    clean = html.unescape(value or "")
    if "<" in clean or "&" in clean:
        parser = _HTMLToTextParser()
        try:
            parser.feed(clean)
            parser.close()
        except Exception:
            return ""
        clean = html.unescape(parser.text)
    clean = "\n".join(" ".join(line.split()) for line in clean.splitlines())
    return "\n".join(line for line in clean.splitlines() if line).strip()


def _compact(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


class _HTMLToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        name = str(tag or "").lower()
        if name in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if name in {"br", "p", "div", "li", "tr"}:
            self._append_line_break()
        elif name in {"td", "th"}:
            self._append_cell_separator()

    def handle_endtag(self, tag: str) -> None:
        name = str(tag or "").lower()
        if name in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if name in {"p", "div", "li", "tr"}:
            self._append_line_break()

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def _append_line_break(self) -> None:
        if self._parts and self._parts[-1] != "\n":
            self._parts.append("\n")

    def _append_cell_separator(self) -> None:
        if not self._parts:
            return
        current = "".join(self._parts).rstrip()
        if current and not current.endswith(("\n", "|")):
            self._parts.append(" | ")
