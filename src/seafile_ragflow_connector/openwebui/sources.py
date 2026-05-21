from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from seafile_ragflow_connector.config.settings import Settings

SOURCE_TOKEN_TTL_SECONDS = 900


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


def sign_preview_payload(payload: dict[str, Any], secret: str, *, now: int | None = None) -> str:
    body = dict(payload)
    body["exp"] = int(now or time.time()) + SOURCE_TOKEN_TTL_SECONDS
    encoded = _b64encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
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
    payload = json.loads(_b64decode(encoded))
    if not isinstance(payload, dict):
        raise ValueError("invalid preview token payload")
    if int(payload.get("exp") or 0) < int(now or time.time()):
        raise ValueError("preview token expired")
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
    snippet = _first_text(raw, "content", "text", "snippet", "content_with_weight")
    score = raw.get("score") or raw.get("similarity") or raw.get("vector_similarity")
    file_row = files_by_document_id.get(document_id or "")
    if not document_name and file_row:
        document_name = _safe_document_name_from_file_row(file_row)
    preview_url = _preview_url(
        raw,
        settings=settings,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        document_id=document_id,
        document_name=document_name,
        chunk_id=chunk_id,
        snippet=snippet,
    )
    metadata = {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "document_id": document_id,
        "document_name": document_name,
        "chunk_id": chunk_id,
        "page": raw.get("page") or raw.get("page_num") or raw.get("page_number"),
        "section": raw.get("section"),
        "line": raw.get("line") or raw.get("line_number"),
        "position": raw.get("position") or raw.get("positions"),
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
            "snippet": snippet,
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


def _safe_document_name_from_file_row(file_row: dict[str, Any]) -> str:
    ragflow_name = file_row.get("ragflow_document_name")
    if ragflow_name:
        return str(ragflow_name)
    path = str(file_row.get("path") or "")
    if not path:
        return ""
    return PurePosixPath(path).name or path.rsplit("/", 1)[-1]


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
