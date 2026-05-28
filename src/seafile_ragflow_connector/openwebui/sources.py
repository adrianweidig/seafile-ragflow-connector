from __future__ import annotations

import base64
import hmac
import json
import re
import zlib
from dataclasses import dataclass, field
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from seafile_ragflow_connector.i18n import Localizer, localizer_for

if TYPE_CHECKING:
    from seafile_ragflow_connector.config.settings import Settings

_RAGFLOW_INLINE_CITATION_RE = re.compile(r"\[ID:(\d+)\]")
_PREVIEW_SNIPPET_MAX_CHARS = 120
_SOURCE_SNIPPET_MAX_CHARS = 420
_TEXT_PROJECTION_WRAPPER_RE = re.compile(
    r"(?is)^\s*Source path:.*?----- BEGIN SOURCE CONTENT -----\s*(?P<content>.*?)"
    r"\s*----- END SOURCE CONTENT -----\s*$"
)


@dataclass(frozen=True)
class SourceHit:
    rank: int
    title: str
    snippet: str = ""
    source_id: str | None = None
    document_name: str | None = None
    path: str | None = None
    page: Any = None
    line: Any = None
    line_start: Any = None
    line_end: Any = None
    section: Any = None
    chunk_id: str | None = None
    score: Any = None
    preview_url: str | None = None
    original_url: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    document_id: str | None = None
    repo_id: str | None = None
    file_id: str | None = None
    seafile_library_id: str | None = None
    seafile_library_name: str | None = None
    file_type: str | None = None
    mime_type: str | None = None
    position: Any = None
    locator_quality: str = "unknown"
    citation_label: str | None = None
    language: str = "de"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def l10n(self) -> Localizer:
        return Localizer(self.language)

    @property
    def relevance(self) -> str:
        value = _score_float(self.score)
        if value is None:
            return self.l10n.text("sources.unknown")
        if value >= 0.8:
            return self.l10n.text("sources.high")
        if value >= 0.55:
            return self.l10n.text("sources.medium")
        return self.l10n.text("sources.low")

    @property
    def display_location(self) -> str:
        parts = []
        if self.page not in (None, ""):
            parts.append(self.l10n.text("sources.page", value=self.page))
        if self.section not in (None, ""):
            parts.append(self.l10n.text("sources.section", value=self.section))
        line_range = _line_range(self.line_start or self.line, self.line_end)
        if line_range:
            parts.append(self.l10n.text("sources.line", value=line_range))
        return " · ".join(parts) or self.l10n.text("sources.missing_location")

    def metadata(self) -> dict[str, Any]:
        values = {
            "rank": self.rank,
            "source_id": self.source_id or f"S{self.rank}",
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "chunk_id": self.chunk_id,
            "citation_id": self.rank - 1,
            "citation_marker": f"[ID:{self.rank - 1}]",
            "citation_label": self.citation_label,
            "page": self.page,
            "section": self.section,
            "line": self.line,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "position": self.position,
            "locator_quality": self.locator_quality,
            "score": self.score,
            "relevance": self.relevance,
            "relevance_label": self.relevance,
            "path": self.path,
            "repo_id": self.repo_id,
            "file_id": self.file_id,
            "seafile_library_id": self.seafile_library_id,
            "seafile_library_name": self.seafile_library_name,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "original_url": self.original_url,
            "preview_url": self.preview_url,
        }
        return {key: value for key, value in values.items() if value not in (None, "")}

    def to_openwebui_source(self) -> dict[str, Any]:
        metadata = self.metadata()
        title = (
            self.title
            or self.document_name
            or f"{self.l10n.text('sources.source')} {self.rank}"
        )
        location = self.display_location
        citation_title = title
        if location and location != self.l10n.text("sources.missing_location"):
            citation_title = f"{title} · {location}"
        return {
            "name": title,
            "source_id": self.source_id or f"S{self.rank}",
            "document": [self.snippet or title],
            "metadata": [metadata],
            "source_metadata": metadata,
            "source": {"name": citation_title, "url": self.preview_url},
            "url": self.preview_url,
            "preview_url": self.preview_url,
            "original_url": self.original_url,
            "citation": {
                "id": self.rank - 1,
                "marker": f"[ID:{self.rank - 1}]",
                "label": self.citation_label,
            },
            "citation_label": self.citation_label,
            "text": self.snippet,
            "snippet": self.snippet,
            "rank": self.rank,
            "score": self.score,
            "relevance": self.relevance,
        }


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
    l10n = localizer_for(settings)
    sources = []
    for index, raw in enumerate(extract_references(payload), start=1):
        source = _normalize_reference(
            raw,
            index=index,
            settings=settings,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            files_by_document_id=files_by_document_id or {},
            l10n=l10n,
        )
        sources.append(source.to_openwebui_source())
    return sources


def annotate_answer_citations(
    answer: str,
    sources: list[dict[str, Any]],
    *,
    language: str = "de",
) -> str:
    if not answer or not sources:
        return answer

    def replace(match: re.Match[str]) -> str:
        citation_id = int(match.group(1))
        if citation_id < 0 or citation_id >= len(sources):
            return match.group(0)
        source = sources[citation_id]
        l10n = Localizer(language)
        label = str(
            source.get("citation_label")
            or f"{l10n.text('sources.source')} {citation_id + 1}"
        )
        url = source.get("url") or source.get("preview_url")
        if url:
            return f"[{label}]({url})"
        return f"[{label}]"

    return _RAGFLOW_INLINE_CITATION_RE.sub(replace, answer)


def render_sources_markdown(
    sources: list[dict[str, Any]],
    *,
    show_scores: bool = True,
    show_debug: bool = False,
    max_documents: int = 6,
    language: str = "de",
    mode: str = "compact",
) -> str:
    l10n = Localizer(language)
    if _source_markdown_mode(mode) == "audit":
        return _render_sources_audit_markdown(
            sources,
            show_scores=show_scores,
            show_debug=show_debug,
            max_sources=max_documents,
            l10n=l10n,
        )
    if not sources:
        return l10n.text("sources.no_sources")
    groups = _group_sources_by_document(sources, language=l10n.language)
    lines = [
        f"## {l10n.text('sources.heading')}",
        "",
        _source_basis_line(groups, sources, l10n),
        "",
    ]
    for display_index, group in enumerate(groups[:max_documents], start=1):
        best = group[0]
        metadata = _source_metadata(best)
        name = _markdown_plain(str(best.get("name") or l10n.text("sources.source")))
        location = _source_location(metadata, l10n)
        relevance = _relevance_label(metadata, best, l10n) if show_scores else ""
        hit_word = l10n.text("sources.hit_one" if len(group) == 1 else "sources.hit_other")
        hit_count = "" if len(group) == 1 else f" · {len(group)} {hit_word}"
        summary_parts = [part for part in (location, relevance) if part]
        lines.append(f"### {display_index}. {name}")
        if summary_parts or hit_count:
            evidence = l10n.text("sources.evidence")
            lines.append(f"**{evidence}:** {' · '.join(summary_parts)}{hit_count}")
        actions = _source_actions(best, l10n)
        if actions:
            lines.append(f"**{l10n.text('sources.actions')}:** {actions}")
        snippet = _clean_reference_text(str(best.get("snippet") or best.get("text") or "")) or ""
        if snippet:
            lines.append("")
            lines.extend(_blockquote(_compact_markdown_text(snippet, _SOURCE_SNIPPET_MAX_CHARS)))
        other_locations = [
            _source_location(_source_metadata(item), l10n)
            for item in group[1:4]
            if _source_location(_source_metadata(item), l10n) != location
        ]
        if other_locations:
            lines.append("")
            lines.append(l10n.text("sources.other_locations", locations=", ".join(other_locations)))
        if show_debug:
            debug_parts = _debug_parts(metadata)
            if debug_parts:
                lines.append("")
                lines.append(f"Debug: {' · '.join(debug_parts)}")
        lines.append("")
    if len(groups) > max_documents:
        lines.append(l10n.text("sources.more_documents", count=len(groups) - max_documents))
    return "\n".join(lines).rstrip()


def _source_markdown_mode(value: str) -> str:
    mode = str(value or "compact").strip().lower()
    if mode in {"off", "disabled"}:
        return "none"
    if mode in {"none", "compact", "detailed", "audit"}:
        return mode
    return "compact"


def _render_sources_audit_markdown(
    sources: list[dict[str, Any]],
    *,
    show_scores: bool,
    show_debug: bool,
    max_sources: int,
    l10n: Localizer,
) -> str:
    lines = [f"## {l10n.text('sources.audit_heading')}", ""]
    if not sources:
        lines.extend(
            [
                l10n.text("sources.audit_no_sources"),
                "",
                f"**{l10n.text('sources.audit_quality_label')}:** "
                f"{l10n.text('sources.audit_quality_none')}",
            ]
        )
        return "\n".join(lines).rstrip()

    lines.append(_audit_quality_sentence(sources, l10n))
    lines.append("")
    lines.append("| ID | Gestützte Aussage | Dokument | Fundstelle | Relevanz | Öffnen |")
    lines.append("|---|---|---|---|---|---|")

    for source in sources[:max_sources]:
        metadata = _source_metadata(source)
        source_id = _source_id(source, metadata)
        claim = _audit_claim(source, metadata, l10n)
        document = _audit_document(source, metadata)
        location = _source_location(metadata, l10n)
        if metadata.get("locator_quality") in {"unknown", "snippet_only", "document", "chunk"}:
            location = f"{location} ({l10n.text('sources.locator_coarse')})"
        relevance = _audit_relevance(source, metadata, show_scores, l10n)
        actions = _source_actions(source, l10n) or l10n.text("sources.no_direct_link")
        lines.append(
            "| "
            + " | ".join(
                _escape_table_cell(value)
                for value in (source_id, claim, document, location, relevance, actions)
            )
            + " |"
        )

    if len(sources) > max_sources:
        remaining_text = l10n.text("sources.more_documents", count=len(sources) - max_sources)
        lines.append(
            "|  | "
            + _escape_table_cell(remaining_text)
            + " |  |  |  |  |"
        )

    if show_debug:
        debug_lines = []
        for source in sources[:max_sources]:
            metadata = _source_metadata(source)
            debug_parts = _debug_parts(metadata)
            if debug_parts:
                debug_lines.append(f"- {_source_id(source, metadata)}: {' · '.join(debug_parts)}")
        if debug_lines:
            lines.extend(["", "**Debug:**", *debug_lines])

    return "\n".join(lines).rstrip()


def _audit_quality_sentence(sources: list[dict[str, Any]], l10n: Localizer) -> str:
    quality = _audit_quality(sources)
    precise = 0
    linked = 0
    for source in sources:
        metadata = _source_metadata(source)
        if metadata.get("locator_quality") in {"line", "page", "section", "position"}:
            precise += 1
        if source.get("preview_url") or source.get("url") or source.get("original_url"):
            linked += 1
    return l10n.text(
        f"sources.audit_quality_{quality}",
        sources=len(sources),
        precise=precise,
        linked=linked,
    )


def _audit_quality(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "none"
    precise = 0
    linked = 0
    for source in sources:
        metadata = _source_metadata(source)
        if metadata.get("locator_quality") in {"line", "page", "section", "position"}:
            precise += 1
        if source.get("preview_url") or source.get("url") or source.get("original_url"):
            linked += 1
    if len(sources) >= 2 and precise >= 2 and linked >= 1:
        return "strong"
    if precise >= 1 or linked >= 1:
        return "medium"
    return "weak"


def _audit_claim(source: dict[str, Any], metadata: dict[str, Any], l10n: Localizer) -> str:
    claim = (
        metadata.get("claim")
        or metadata.get("supported_claim")
        or source.get("claim")
        or source.get("supported_claim")
    )
    if claim not in (None, ""):
        return _compact_markdown_text(str(claim), 120)
    snippet = _clean_reference_text(str(source.get("snippet") or source.get("text") or "")) or ""
    if snippet:
        return _compact_markdown_text(snippet, 120)
    return l10n.text("sources.audit_claim_unknown")


def _audit_document(source: dict[str, Any], metadata: dict[str, Any]) -> str:
    name = str(
        source.get("name")
        or metadata.get("document_name")
        or metadata.get("doc_name")
        or "Quelle"
    )
    path = metadata.get("path")
    dataset = metadata.get("dataset_name")
    parts = [name]
    if path and str(path) != name:
        parts.append(str(path))
    if dataset:
        parts.append(str(dataset))
    return " · ".join(parts)


def _audit_relevance(
    source: dict[str, Any],
    metadata: dict[str, Any],
    show_scores: bool,
    l10n: Localizer,
) -> str:
    relevance = str(metadata.get("relevance_label") or metadata.get("relevance") or "")
    if not relevance:
        value = _score_float(source.get("score") or metadata.get("score"))
        if value is None:
            relevance = l10n.text("sources.unknown")
        elif value >= 0.8:
            relevance = l10n.text("sources.high")
        elif value >= 0.55:
            relevance = l10n.text("sources.medium")
        else:
            relevance = l10n.text("sources.low")
    if show_scores:
        return _relevance_label(metadata, source, l10n)
    return relevance or l10n.text("sources.unknown")


def _source_basis_line(
    groups: list[list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    l10n: Localizer,
) -> str:
    documents = len(groups)
    hits = len(sources)
    document_word = l10n.text(
        "sources.document_one" if documents == 1 else "sources.document_other"
    )
    hit_word = l10n.text("sources.hit_one" if hits == 1 else "sources.hit_other")
    return l10n.text(
        "sources.basis",
        documents=documents,
        document_word=document_word,
        hits=hits,
        hit_word=hit_word,
    )


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
    l10n: Localizer,
) -> SourceHit:
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
    page = (
        raw.get("page")
        or raw.get("page_num")
        or raw.get("page_number")
        or raw.get("page_idx")
        or _first_page(position)
    )
    line = raw.get("line") or raw.get("line_number")
    line_start = raw.get("line_start") or raw.get("start_line") or line
    line_end = raw.get("line_end") or raw.get("end_line")
    section = raw.get("section") or raw.get("section_title") or raw.get("heading")
    file_row = files_by_document_id.get(document_id or "")
    if file_row:
        document_name = _safe_document_name_from_file_row(file_row) or document_name
    source_path = _source_path(raw, file_row)
    repo_id = _repo_id(raw, file_row)
    file_id = _first_text(raw, "file_id", "seafile_file_id", "seafile_obj_id", "obj_id")
    seafile_library_name = _first_text(raw, "seafile_library_name", "library_name")
    file_type = _file_type(document_name or source_path)
    mime_type = _first_text(raw, "mime_type", "mime", "content_type")
    if not mime_type and file_row:
        mime_type = (
            str(file_row.get("ingested_mime") or file_row.get("detected_mime") or "")
            or None
        )
    locator_quality = _locator_quality(
        page=page,
        section=section,
        line_start=line_start,
        line_end=line_end,
        position=position,
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=document_name,
        path=source_path,
        snippet=snippet,
    )
    original_url = _original_source_url(
        settings,
        repo_id=repo_id,
        source_path=source_path,
        document_id=document_id,
        chunk_id=chunk_id,
        page=page,
    )
    citation_label = _citation_label(index=index, page=page, chunk_id=chunk_id, l10n=l10n)
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
        section=section,
        line=line,
        line_start=line_start,
        line_end=line_end,
        position=position,
        locator_quality=locator_quality,
        repo_id=repo_id,
        file_id=file_id,
        seafile_library_id=repo_id,
        seafile_library_name=seafile_library_name,
        source_path=source_path,
        original_url=original_url,
        score=score,
        file_type=file_type,
        mime_type=mime_type,
    )
    title = document_name or f"{l10n.text('sources.source')} {index}"
    return SourceHit(
        rank=index,
        title=title,
        document_name=document_name,
        path=source_path,
        page=page,
        line=line,
        line_start=line_start,
        line_end=line_end,
        section=section,
        chunk_id=chunk_id,
        score=score,
        snippet=snippet or "",
        preview_url=preview_url,
        original_url=original_url,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        document_id=document_id,
        repo_id=repo_id,
        file_id=file_id,
        seafile_library_id=repo_id,
        seafile_library_name=seafile_library_name,
        file_type=file_type,
        mime_type=mime_type,
        position=position,
        locator_quality=locator_quality,
        citation_label=citation_label,
        language=l10n.language,
        raw=raw,
    )


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
    line_start: Any,
    line_end: Any,
    position: Any,
    locator_quality: str,
    repo_id: str | None,
    file_id: str | None,
    seafile_library_id: str | None,
    seafile_library_name: str | None,
    source_path: str | None,
    original_url: str | None,
    score: Any,
    file_type: str | None,
    mime_type: str | None,
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
            "line_start": line_start,
            "line_end": line_end,
            "position": position,
            "locator_quality": locator_quality,
            "snippet": _preview_snippet(snippet),
            "repo_id": repo_id,
            "file_id": file_id,
            "seafile_library_id": seafile_library_id,
            "seafile_library_name": seafile_library_name,
            "source_path": source_path,
            "original_url": original_url,
            "score": score,
            "file_type": file_type,
            "mime_type": mime_type,
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
    template = settings.effective_seafile_file_url_template
    if not template or not repo_id or not source_path:
        return None
    clean_path = str(source_path)
    path_for_file_url = clean_path if clean_path.startswith("/") else f"/{clean_path}"
    page_text = "" if page in (None, "") else str(page)
    base_url = settings.effective_seafile_public_base_url or ""
    values = {
        "base": base_url,
        "repo_id": repo_id,
        "repo_id_quoted": quote(repo_id, safe=""),
        "path": clean_path,
        "path_quoted": quote(path_for_file_url, safe="/"),
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


def _citation_label(*, index: int, page: Any, chunk_id: str | None, l10n: Localizer) -> str:
    _ = (page, chunk_id, l10n)
    return f"S{index}"


def _line_range(start: Any, end: Any) -> str:
    if start in (None, "") and end in (None, ""):
        return ""
    if end in (None, "") or str(end) == str(start):
        return str(start)
    if start in (None, ""):
        return str(end)
    return f"{start}-{end}"


def _locator_quality(
    *,
    page: Any,
    section: Any,
    line_start: Any,
    line_end: Any,
    position: Any,
    chunk_id: str | None,
    document_id: str | None,
    document_name: str | None,
    path: str | None,
    snippet: str | None,
) -> str:
    if line_start not in (None, "") or line_end not in (None, ""):
        return "line"
    if page not in (None, ""):
        return "page"
    if section not in (None, ""):
        return "section"
    if position not in (None, "", [], {}):
        return "position"
    if chunk_id:
        return "chunk"
    if document_id or document_name or path:
        return "document"
    if snippet:
        return "snippet_only"
    return "unknown"


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
    clean = _html_to_text(str(value))
    clean = unescape(clean)
    match = _TEXT_PROJECTION_WRAPPER_RE.match(clean)
    if match:
        clean = match.group("content")
    clean = "\n".join(" ".join(line.split()) for line in clean.splitlines())
    return "\n".join(line for line in clean.splitlines() if line).strip()


class _HTMLToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._last_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"br", "p", "div", "li", "tr", "table", "thead", "tbody", "h1", "h2", "h3"}:
            self._append("\n")
            self._last_cell = False
        if tag in {"td", "th"}:
            if self._last_cell:
                self._append(" | ")
            self._last_cell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "div", "li", "tr", "table", "h1", "h2", "h3"}:
            self._append("\n")
            self._last_cell = False

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._append(data)

    def _append(self, value: str) -> None:
        if value:
            self.parts.append(value)


def _html_to_text(value: str) -> str:
    if "<" not in value and "&" not in value:
        return value
    parser = _HTMLToTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    return "".join(parser.parts)


def _file_type(path: str | None) -> str | None:
    if not path:
        return None
    suffix = PurePosixPath(str(path)).suffix.lower().lstrip(".")
    return suffix or None


def _score_float(score: Any) -> float | None:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, value))


def _format_score(score: Any) -> str | None:
    value = _score_float(score)
    if value is None:
        return None
    return f"{value:.0%}"


def _group_sources_by_document(
    sources: list[dict[str, Any]],
    *,
    language: str = "de",
) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        metadata = _source_metadata(source)
        key = str(
            metadata.get("path")
            or metadata.get("document_id")
            or metadata.get("document_name")
            or source.get("name")
            or source.get("title")
            or Localizer(language).text("sources.source")
        )
        grouped.setdefault(key, []).append(source)
    groups = list(grouped.values())
    for group in groups:
        group.sort(key=lambda item: (_sort_score(item), _source_rank(item)))
    groups.sort(key=lambda group: (_sort_score(group[0]), _source_rank(group[0])))
    return groups


def _sort_score(source: dict[str, Any]) -> float:
    value = _score_float(source.get("score") or _source_metadata(source).get("score"))
    return -1.0 if value is None else -value


def _source_rank(source: dict[str, Any]) -> int:
    rank = source.get("rank") or _source_metadata(source).get("rank")
    if rank is None:
        return 9999
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 9999


def _source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("source_metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata_items = source.get("metadata")
    if isinstance(metadata_items, list) and metadata_items and isinstance(metadata_items[0], dict):
        return metadata_items[0]
    return {}


def _source_id(source: dict[str, Any], metadata: dict[str, Any]) -> str:
    value = source.get("source_id") or metadata.get("source_id")
    if value not in (None, ""):
        return str(value)
    rank = source.get("rank") or metadata.get("rank") or 1
    try:
        return f"S{int(rank)}"
    except (TypeError, ValueError):
        return "S?"


def _source_location(metadata: dict[str, Any], l10n: Localizer | None = None) -> str:
    l10n = l10n or Localizer()
    parts = []
    if metadata.get("page") not in (None, ""):
        parts.append(l10n.text("sources.page", value=metadata.get("page")))
    if metadata.get("section") not in (None, ""):
        parts.append(l10n.text("sources.section", value=metadata.get("section")))
    line_range = _line_range(
        metadata.get("line_start") or metadata.get("line"),
        metadata.get("line_end"),
    )
    if line_range:
        parts.append(l10n.text("sources.line", value=line_range))
    if not parts and metadata.get("locator_quality") == "position":
        parts.append(l10n.text("sources.position_available"))
    if not parts and metadata.get("locator_quality") == "chunk":
        parts.append(l10n.text("sources.chunk_available"))
    return " · ".join(parts) or l10n.text("sources.missing_location")


def _relevance_label(metadata: dict[str, Any], source: dict[str, Any], l10n: Localizer) -> str:
    score = source.get("score") or metadata.get("score")
    formatted = _format_score(score)
    relevance = metadata.get("relevance_label") or metadata.get("relevance")
    if not relevance:
        value = _score_float(score)
        if value is None:
            relevance = l10n.text("sources.unknown")
        elif value >= 0.8:
            relevance = l10n.text("sources.high")
        elif value >= 0.55:
            relevance = l10n.text("sources.medium")
        else:
            relevance = l10n.text("sources.low")
    if formatted:
        return l10n.text("sources.relevance_score", value=relevance, score=formatted)
    return l10n.text("sources.relevance", value=relevance)


def _source_actions(source: dict[str, Any], l10n: Localizer | None = None) -> str:
    l10n = l10n or Localizer()
    preview_url = source.get("preview_url") or source.get("url")
    original_url = source.get("original_url") or _source_metadata(source).get("original_url")
    links = []
    if preview_url:
        links.append(f"[{l10n.text('sources.open_preview')}]({preview_url})")
    if original_url:
        links.append(f"[{l10n.text('sources.open_original')}]({original_url})")
    return " · ".join(links)


def _debug_parts(metadata: dict[str, Any]) -> list[str]:
    parts = []
    if metadata.get("chunk_id"):
        parts.append(f"Chunk `{_markdown_plain(str(metadata['chunk_id'])[:12])}`")
    if metadata.get("document_id"):
        parts.append(f"Dokument `{_markdown_plain(str(metadata['document_id'])[:12])}`")
    if metadata.get("dataset_id"):
        parts.append(f"Dataset `{_markdown_plain(str(metadata['dataset_id'])[:12])}`")
    if metadata.get("repo_id"):
        parts.append(f"Repo `{_markdown_plain(str(metadata['repo_id'])[:12])}`")
    return parts


def _compact_markdown_text(text: str, limit: int) -> str:
    clean = "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _blockquote(text: str) -> list[str]:
    lines = str(text or "").splitlines() or [""]
    return [f"> {_markdown_plain(line)}" if line else ">" for line in lines]


def _markdown_plain(text: str) -> str:
    replacements = {
        "\\": "\\\\",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "#": "\\#",
        "|": "\\|",
        "<": "&lt;",
        ">": "&gt;",
    }
    return "".join(replacements.get(char, char) for char in str(text or ""))


def _escape_table_cell(text: Any) -> str:
    replacements = {
        "\\": "\\\\",
        "`": "\\`",
        "|": "\\|",
        "<": "&lt;",
        ">": "&gt;",
    }
    return "".join(replacements.get(char, char) for char in str(text or "")).replace(
        "\n",
        " ",
    )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    return _b64decode_bytes(value).decode("utf-8")


def _b64decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
