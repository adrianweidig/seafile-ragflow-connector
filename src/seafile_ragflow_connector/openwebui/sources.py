from __future__ import annotations

import base64
import hmac
import json
import re
import zlib
from hashlib import sha256
from html import unescape
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from seafile_ragflow_connector.config.settings import Settings

_RAGFLOW_INLINE_CITATION_RE = re.compile(r"\[ID:(\d+)\]")
_PREVIEW_SNIPPET_MAX_CHARS = 120
_TEXT_PROJECTION_WRAPPER_RE = re.compile(
    r"(?is)^\s*Source path:.*?----- BEGIN SOURCE CONTENT -----\s*(?P<content>.*?)"
    r"\s*----- END SOURCE CONTENT -----\s*$"
)


def extract_answer(payload: Any) -> str:
    if isinstance(payload, dict):
        nested = payload.get("data")
        if isinstance(nested, dict):
            answer = extract_answer(nested)
            if answer:
                return answer
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                return str(message.get("content") or "")
        if "answer" in payload:
            return str(payload.get("answer") or "")
        if "content" in payload:
            return str(payload.get("content") or "")
    return ""


def extract_references(payload: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    _collect_references(payload, references)
    return references


def normalize_sources(
    payload: Any,
    *,
    settings: Settings,
    dataset_id: str,
    dataset_name: str,
    files_by_document_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sources = []
    for index, raw in enumerate(extract_references(payload), start=1):
        source = _normalize_reference(
            raw,
            index=index,
            settings=settings,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            files_by_document_id=files_by_document_id or {},
        )
        sources.append(source)
    return sources


def annotate_answer_citations(answer: str, sources: list[dict[str, Any]]) -> str:
    if not answer or not sources:
        return answer

    def replace(match: re.Match[str]) -> str:
        citation_id = int(match.group(1))
        if citation_id < 0 or citation_id >= len(sources):
            return match.group(0)
        source = sources[citation_id]
        label = str(source.get("citation_label") or f"Quelle {citation_id + 1}")
        url = source.get("url") or source.get("preview_url")
        if url:
            return f"[{label}]({url})"
        return f"[{label}]"

    return _RAGFLOW_INLINE_CITATION_RE.sub(replace, answer)


def sign_preview_payload(payload: dict[str, Any], secret: str, *, now: int | None = None) -> str:
    body = dict(payload)
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = "z" + _b64encode(zlib.compress(raw, level=9))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_preview_token(token: str, secret: str, *, now: int | None = None) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid preview token") from exc
    expected = _b64encode(
        hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid preview token signature")
    raw_payload = (
        _b64decode_bytes(encoded[1:])
        if encoded.startswith("z")
        else _b64decode(encoded).encode("utf-8")
    )
    if encoded.startswith("z"):
        raw_payload = zlib.decompress(raw_payload)
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("invalid preview token payload")
    return payload


def _normalize_reference(
    raw: dict[str, Any],
    *,
    index: int,
    settings: Settings,
    dataset_id: str,
    dataset_name: str,
    files_by_document_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chunk_id = _first_text(raw, "id", "chunk_id", "chunkId")
    document_id = _first_text(raw, "document_id", "doc_id", "docid", "docId")
    document_name = _first_text(
        raw,
        "document_name",
        "document_keyword",
        "doc_name",
        "docnm_kwd",
        "name",
        "title",
    )
    snippet = _clean_reference_text(
        _first_text(raw, "content", "text", "snippet", "content_with_weight")
    )
    score = raw.get("score") or raw.get("similarity") or raw.get("vector_similarity")
    position = raw.get("position") or raw.get("positions")
    page = raw.get("page") or raw.get("page_num") or raw.get("page_number") or _first_page(position)
    file_row = files_by_document_id.get(document_id or "")
    if file_row:
        document_name = _safe_document_name_from_file_row(file_row) or document_name
    source_path = _source_path(raw, file_row)
    repo_id = _repo_id(raw, file_row)
    original_url = _original_source_url(
        settings,
        repo_id=repo_id,
        source_path=source_path,
        document_id=document_id,
        chunk_id=chunk_id,
        page=page,
    )
    citation_label = _citation_label(index=index, page=page, chunk_id=chunk_id)
    preview_url = _preview_url(
        raw,
        settings=settings,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        document_id=document_id,
        document_name=document_name,
        chunk_id=chunk_id,
        snippet=snippet,
        citation_label=citation_label,
        page=page,
        section=raw.get("section"),
        line=raw.get("line") or raw.get("line_number"),
        position=position,
        repo_id=repo_id,
        source_path=source_path,
        original_url=original_url,
    )
    metadata = {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "document_id": document_id,
        "document_name": document_name,
        "chunk_id": chunk_id,
        "citation_id": index - 1,
        "citation_marker": f"[ID:{index - 1}]",
        "citation_label": citation_label,
        "page": page,
        "section": raw.get("section"),
        "line": raw.get("line") or raw.get("line_number"),
        "position": position,
        "score": score,
    }
    if file_row:
        metadata["repo_id"] = file_row.get("repo_id")
    title = document_name or f"Quelle {index}"
    return {
        "name": title,
        "document": [snippet or title],
        "metadata": [{key: value for key, value in metadata.items() if value not in (None, "")}],
        "source_metadata": {
            key: value for key, value in metadata.items() if value not in (None, "")
        },
        "source": {"name": title, "url": preview_url},
        "url": preview_url,
        "preview_url": preview_url,
        "original_url": original_url,
        "citation": {
            "id": index - 1,
            "marker": f"[ID:{index - 1}]",
            "label": citation_label,
        },
        "citation_label": citation_label,
        "text": snippet or "",
        "snippet": snippet or "",
    }


def _preview_url(
    raw: dict[str, Any],
    *,
    settings: Settings,
    dataset_id: str,
    dataset_name: str,
    document_id: str | None,
    document_name: str | None,
    chunk_id: str | None,
    snippet: str | None,
    citation_label: str | None,
    page: Any,
    section: Any,
    line: Any,
    position: Any,
    repo_id: str | None,
    source_path: str | None,
    original_url: str | None,
) -> str | None:
    if settings.openwebui_source_preview_mode == "disabled":
        return None
    if settings.openwebui_source_preview_mode == "ragflow_link":
        direct = _ragflow_link(raw, settings, dataset_id, document_id, chunk_id)
        if direct:
            return direct
    if (
        settings.openwebui_source_preview_mode in {"connector_viewer", "ragflow_link"}
        and settings.openwebui_proxy_public_base_url
        and settings.openwebui_proxy_shared_secret
    ):
        payload = {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "document_id": document_id,
            "document_name": document_name,
            "chunk_id": chunk_id,
            "citation_label": citation_label,
            "page": page,
            "section": section,
            "line": line,
            "position": position,
            "snippet": _preview_snippet(snippet),
            "repo_id": repo_id,
            "source_path": source_path,
            "original_url": original_url,
        }
        token = sign_preview_payload(payload, settings.openwebui_proxy_shared_secret)
        base_url = settings.openwebui_proxy_public_base_url
        return f"{base_url}/api/openwebui/sources/preview?token={quote(token)}"
    return None


def _ragflow_link(
    raw: dict[str, Any],
    settings: Settings,
    dataset_id: str,
    document_id: str | None,
    chunk_id: str | None,
) -> str | None:
    if settings.ragflow_document_url_template:
        return settings.ragflow_document_url_template.format(
            dataset_id=quote(dataset_id or ""),
            document_id=quote(document_id or ""),
            chunk_id=quote(chunk_id or ""),
        )
    url = _first_text(raw, "url", "preview_url", "deep_link_url")
    if (
        url
        and settings.ragflow_public_base_url
        and url.startswith(settings.ragflow_public_base_url)
    ):
        return url
    return None


def _preview_snippet(snippet: str | None) -> str | None:
    if not snippet:
        return snippet
    compact = snippet.strip()
    if len(compact) <= _PREVIEW_SNIPPET_MAX_CHARS:
        return compact
    return compact[:_PREVIEW_SNIPPET_MAX_CHARS].rstrip() + "..."


def _collect_references(value: Any, references: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if _looks_like_chunk(value):
            references.append(value)
            return
        known_reference_key_found = False
        for key in ("reference", "references", "sources", "chunks"):
            if key in value:
                known_reference_key_found = True
                _collect_references(value[key], references)
        if "doc_aggs" in value:
            known_reference_key_found = True
            _collect_references(value["doc_aggs"], references)
        if not known_reference_key_found:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    _collect_references(item, references)
    elif isinstance(value, list):
        for item in value:
            _collect_references(item, references)


def _looks_like_chunk(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("chunk_id", "doc_id", "document_id", "docnm_kwd")) and any(
        key in value for key in ("content", "text", "snippet", "content_with_weight", "id")
    )


def _first_text(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return str(item)
    return None


def _first_page(position: Any) -> Any:
    if not isinstance(position, list) or not position:
        return None
    first = position[0]
    if isinstance(first, list) and first:
        return first[0]
    return None


def _source_path(raw: dict[str, Any], file_row: dict[str, Any] | None) -> str | None:
    if file_row and file_row.get("path"):
        return str(file_row["path"])
    return _first_text(raw, "source_path", "path", "file_path")


def _repo_id(raw: dict[str, Any], file_row: dict[str, Any] | None) -> str | None:
    if file_row and file_row.get("repo_id"):
        return str(file_row["repo_id"])
    return _first_text(raw, "repo_id", "library_id", "seafile_repo_id")


def _original_source_url(
    settings: Settings,
    *,
    repo_id: str | None,
    source_path: str | None,
    document_id: str | None,
    chunk_id: str | None,
    page: Any,
) -> str | None:
    template = settings.seafile_file_url_template
    if not template or not repo_id or not source_path:
        return None
    clean_path = str(source_path)
    page_text = "" if page in (None, "") else str(page)
    values = {
        "repo_id": repo_id,
        "repo_id_quoted": quote(repo_id, safe=""),
        "path": clean_path,
        "path_quoted": quote(clean_path, safe="/"),
        "path_query": quote(clean_path, safe=""),
        "path_no_leading_slash": clean_path.lstrip("/"),
        "path_no_leading_slash_quoted": quote(clean_path.lstrip("/"), safe="/"),
        "document_id": document_id or "",
        "document_id_quoted": quote(document_id or "", safe=""),
        "chunk_id": chunk_id or "",
        "chunk_id_quoted": quote(chunk_id or "", safe=""),
        "page": page_text,
        "page_fragment": f"#page={quote(page_text, safe='')}" if page_text else "",
    }
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return None


def _citation_label(*, index: int, page: Any, chunk_id: str | None) -> str:
    parts = [f"Quelle {index}"]
    if page not in (None, ""):
        parts.append(f"Seite {page}")
    if chunk_id:
        parts.append(f"Chunk {chunk_id}")
    return ", ".join(parts)


def _safe_document_name_from_file_row(file_row: dict[str, Any]) -> str:
    path = str(file_row.get("path") or "")
    if path:
        return PurePosixPath(path).name or path.rsplit("/", 1)[-1]
    ragflow_name = file_row.get("ragflow_document_name")
    if ragflow_name:
        return str(ragflow_name)
    return ""


def _clean_reference_text(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    clean = str(value)
    clean = re.sub(r"(?is)<(script|style).*?</\1>", " ", clean)
    clean = re.sub(r"(?i)</t[dh]>\s*<t[dh][^>]*>", " | ", clean)
    clean = re.sub(r"(?i)</tr>\s*<tr[^>]*>", "\n", clean)
    clean = re.sub(r"(?i)<br\s*/?>", "\n", clean)
    clean = re.sub(r"(?s)<[^>]+>", " ", clean)
    clean = unescape(clean)
    match = _TEXT_PROJECTION_WRAPPER_RE.match(clean)
    if match:
        clean = match.group("content")
    clean = "\n".join(" ".join(line.split()) for line in clean.splitlines())
    return "\n".join(line for line in clean.splitlines() if line).strip()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    return _b64decode_bytes(value).decode("utf-8")


def _b64decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
