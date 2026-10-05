from __future__ import annotations

import base64
import hmac
import json
import re
import time
import zlib
from dataclasses import dataclass, field, replace
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from seafile_ragflow_connector.i18n import Localizer, localizer_for
from seafile_ragflow_connector.sources.evidence import (
    SOURCE_DTO_VERSION,
    build_text_fragment_url,
    user_facing_document_name,
)
from seafile_ragflow_connector.sources.evidence import (
    locator_quality as shared_locator_quality,
)
from seafile_ragflow_connector.sources.evidence import (
    open_url_kind as shared_open_url_kind,
)

if TYPE_CHECKING:
    from seafile_ragflow_connector.config.settings import Settings

_RAGFLOW_INLINE_CITATION_RE = re.compile(r"\[\s*ID\s*:\s*(\d+)\s*\]", re.IGNORECASE)
_RAGFLOW_SOURCE_CURLY_RE = re.compile(r"\{\{\s*source\s*:\s*(\d+)\s*\}\}", re.IGNORECASE)
_RAGFLOW_SOURCE_DOLLAR_RE = re.compile(r"##(\d+)\$\$")
_SOURCE_LABEL_RE = re.compile(r"\[S(\d+)\]", re.IGNORECASE)
_EXACT_QUERY_TOKEN_RE = re.compile(
    r"\b(?:"
    r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){2,}"
    r"|[A-Fa-f0-9]{12,}"
    r"|[A-Za-z0-9_.-]+\.(?:md|txt|pdf|docx?|xlsx?|csv|json|ya?ml|py|sh|ps1)"
    r"|[A-Z]{2,}-\d{2,}"
    r")\b"
)
_PREVIEW_SNIPPET_MAX_CHARS = 120
_SOURCE_SNIPPET_MAX_CHARS = 420
PREVIEW_TOKEN_TTL_SECONDS = 15 * 60
PREVIEW_TOKEN_VERSION = 1
SOURCE_PREVIEW_PURPOSE = "source_preview"
DOCUMENT_VIEWER_PURPOSE = "document_viewer"
OPENWEBUI_PREVIEW_AUDIENCE = "openwebui_proxy"
SEARCH_PREVIEW_AUDIENCE = "search_service"
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
    text_fragment_url: str | None = None
    open_url_kind: str = "none"
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
    provider_citation_id: int | None = None
    source_role: str = "related"
    match_type: str = "semantic"
    audit_score: float | None = None
    score_components: dict[str, Any] = field(default_factory=dict)
    used_in_answer: bool = False
    claim_ids: tuple[str, ...] = ()
    support_status: str = "not_evaluated"
    language: str = "de"
    source_dto_version: str = SOURCE_DTO_VERSION
    status: str = "available"
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
            "source_dto_version": self.source_dto_version,
            "status": self.status,
            "rank": self.rank,
            "source_id": self.source_id or f"S{self.rank}",
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "chunk_id": self.chunk_id,
            "citation_id": self.rank - 1,
            "citation_marker": f"[S{self.rank}]",
            "citation_label": self.citation_label,
            "provider_citation_id": self.provider_citation_id,
            "provider_citation_marker": (
                f"[ID:{self.provider_citation_id}]"
                if self.provider_citation_id is not None
                else None
            ),
            "source_role": self.source_role,
            "role": self.source_role,
            "match_type": self.match_type,
            "audit_score": self.audit_score,
            "score_components": self.score_components or None,
            "used_in_answer": self.used_in_answer,
            "claim_ids": list(self.claim_ids) if self.claim_ids else None,
            "support_status": self.support_status,
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
            "text_fragment_url": self.text_fragment_url,
            "open_url_kind": self.open_url_kind,
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
            "source_dto_version": self.source_dto_version,
            "status": self.status,
            "name": title,
            "source_id": self.source_id or f"S{self.rank}",
            "document": [self.snippet or title],
            "metadata": [metadata],
            "source_metadata": metadata,
            "source": {"name": citation_title, "url": self.preview_url},
            "url": self.preview_url,
            "preview_url": self.preview_url,
            "original_url": self.original_url,
            "text_fragment_url": self.text_fragment_url,
            "open_url_kind": self.open_url_kind,
            "citation": {
                "id": self.rank - 1,
                "marker": f"[S{self.rank}]",
                "label": self.citation_label,
            },
            "citation_label": self.citation_label,
            "text": self.snippet,
            "snippet": self.snippet,
            "rank": self.rank,
            "score": self.score,
            "relevance": self.relevance,
            "source_role": self.source_role,
            "role": self.source_role,
            "match_type": self.match_type,
            "audit_score": self.audit_score,
            "score_components": self.score_components,
            "used_in_answer": self.used_in_answer,
            "claim_ids": list(self.claim_ids),
            "support_status": self.support_status,
        }


@dataclass(frozen=True)
class AnswerExtractionResult:
    answer: str
    origin: str
    path: str
    warnings: list[str] = field(default_factory=list)


def extract_answer(payload: Any) -> str:
    return extract_answer_result(payload).answer


def extract_answer_result(payload: Any) -> AnswerExtractionResult:
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return AnswerExtractionResult("", "none", "", warnings)

    for path, value, origin in _canonical_answer_candidates(payload):
        text = _answer_value_to_text(value)
        if not text:
            continue
        rejection = _answer_rejection_reason(text)
        if rejection:
            warnings.append(f"{path}: {rejection}")
            continue
        return AnswerExtractionResult(text.strip(), origin, path, warnings)

    origin = "retrieval_only" if extract_references(payload) else "none"
    return AnswerExtractionResult("", origin, "", warnings)


def _canonical_answer_candidates(payload: dict[str, Any]) -> list[tuple[str, Any, str]]:
    candidates: list[tuple[str, Any, str]] = []
    for key in ("answer", "final_answer", "generated_answer"):
        if key in payload:
            candidates.append((key, payload.get(key), "canonical_answer"))
    nested = payload.get("data")
    if isinstance(nested, dict) and "answer" in nested:
        candidates.append(("data.answer", nested.get("answer"), "canonical_answer"))
    candidates.extend(_openai_message_candidates(payload, prefix=""))
    if isinstance(nested, dict):
        candidates.extend(_openai_message_candidates(nested, prefix="data."))
    return candidates


def _openai_message_candidates(
    payload: dict[str, Any],
    *,
    prefix: str,
) -> list[tuple[str, Any, str]]:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return []
    candidates: list[tuple[str, Any, str]] = []
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and "content" in message:
            candidates.append(
                (
                    f"{prefix}choices[{index}].message.content",
                    message.get("content"),
                    "openai_message",
                )
            )
    return candidates


def _answer_value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _answer_rejection_reason(text: str) -> str:
    clean = _compact_plain(text)
    lower = clean.lower()
    if not clean:
        return "empty"
    if _looks_like_backend_error_answer(clean):
        return "backend error"
    if re.fullmatch(r"\d+\s+treffer\s+im\s+dokument", lower):
        return "document hit count"
    if _looks_like_filename_or_path(clean):
        return "filename or path"
    if _looks_like_markdown_source_table(text):
        return "source table"
    if len(clean) <= 64 and not re.search(r"[.!?;:]", clean) and len(clean.split()) <= 5:
        return "short title"
    return ""


def _looks_like_backend_error_answer(text: str) -> bool:
    clean = _compact_plain(text)
    return bool(
        re.fullmatch(
            r"\*{0,3}(?:error|fehler|exception)\*{0,3}\s*:\s*.{0,220}"
            r"\b(?:not\s+authorized|unauthorized|forbidden|permission\s+denied|"
            r"access\s+denied|api[- ]?key|model\(@none\))\b.*",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _compact_plain(value: Any) -> str:
    return " ".join(str(value or "").split())


def _looks_like_filename_or_path(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"[\w .@()+\-/\\]+?\.(md|txt|pdf|docx?|xlsx?|pptx?|csv|json|yaml|yml)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_markdown_source_table(text: str) -> bool:
    lines = [line.strip().lower() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) >= 2 and len(table_lines) / len(lines) >= 0.8:
        return True
    return any("nachweisqualität" in line for line in lines) and any(
        "dokument" in line and "fundstelle" in line for line in table_lines
    )


def extract_references(payload: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[int] = set()
    _collect_references(payload, references, seen=seen, root=True)
    return references


def normalize_sources(
    payload: Any,
    *,
    settings: Settings,
    dataset_id: str,
    dataset_name: str,
    files_by_document_id: dict[str, dict[str, Any]] | None = None,
    question: str | None = None,
    answer: str | None = None,
    max_sources: int | None = None,
) -> list[dict[str, Any]]:
    l10n = localizer_for(settings)
    hits: list[SourceHit] = []
    for index, raw in enumerate(extract_references(payload), start=1):
        provider_citation_id = _provider_citation_id(raw, fallback=index - 1)
        source = _normalize_reference(
            raw,
            index=index,
            provider_citation_id=provider_citation_id,
            settings=settings,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            files_by_document_id=files_by_document_id or {},
            l10n=l10n,
        )
        hits.append(source)
    return [
        source.to_openwebui_source()
        for source in _rank_hits_for_audit(
            hits,
            question=question,
            answer=answer,
            max_sources=max_sources,
        )
    ]


def audit_rank_sources(
    sources: list[dict[str, Any]],
    *,
    question: str | None = None,
    answer: str | None = None,
    max_sources: int | None = None,
) -> list[dict[str, Any]]:
    """Re-rank and re-label already normalized source dictionaries for audit output."""
    hits = [
        _source_hit_from_event(source, index=index)
        for index, source in enumerate(sources, start=1)
    ]
    return [
        hit.to_openwebui_source()
        for hit in _rank_hits_for_audit(
            hits,
            question=question,
            answer=answer,
            max_sources=max_sources,
        )
    ]


def annotate_answer_citations(
    answer: str,
    sources: list[dict[str, Any]],
    *,
    language: str = "de",
) -> str:
    if not answer or not sources:
        return answer

    by_provider_id: dict[int, dict[str, Any]] = {}
    by_current_id: dict[int, dict[str, Any]] = {}
    linked_sources: set[str] = set()
    for index, source in enumerate(sources):
        metadata = _source_metadata(source)
        provider_id = _int_or_none(metadata.get("provider_citation_id"))
        if provider_id is None:
            provider_id = _int_or_none(metadata.get("reference_id"))
        if provider_id is not None:
            by_provider_id.setdefault(provider_id, source)
        current_id = _int_or_none(metadata.get("citation_id"))
        by_current_id.setdefault(current_id if current_id is not None else index, source)

    def replace(match: re.Match[str]) -> str:
        citation_id = int(match.group(1))
        source = by_provider_id.get(citation_id) or by_current_id.get(citation_id)
        if source is None:
            return match.group(0)
        l10n = Localizer(language)
        label = str(
            source.get("source_id")
            or source.get("citation_label")
            or f"{l10n.text('sources.source')} {citation_id + 1}"
        )
        url = source.get("url") or source.get("preview_url")
        if url:
            source_key = label
            if source_key in linked_sources:
                return f"[{label}]"
            linked_sources.add(source_key)
            return f"[{label}]({url})"
        return f"[{label}]"

    text = _RAGFLOW_INLINE_CITATION_RE.sub(replace, answer)
    text = _RAGFLOW_SOURCE_CURLY_RE.sub(replace, text)
    return _RAGFLOW_SOURCE_DOLLAR_RE.sub(replace, text)


def curate_sources_for_answer(
    sources: list[dict[str, Any]],
    *,
    answer: str | None,
    max_sources: int | None = None,
) -> list[dict[str, Any]]:
    """Keep answer-cited evidence and same-document support, hiding weaker noise."""
    if not sources or not answer:
        return sources
    cited_labels = _answer_source_labels(answer)
    cited_provider_ids = _answer_provider_citation_ids(answer)
    if not cited_labels and not cited_provider_ids:
        return sources

    cited_document_keys: set[str] = set()
    for source in sources:
        metadata = _source_metadata(source)
        source_label = _source_label(source, metadata)
        provider_id = _int_or_none(metadata.get("provider_citation_id"))
        if provider_id is None:
            provider_id = _int_or_none(metadata.get("reference_id"))
        if source_label in cited_labels or (
            provider_id is not None and provider_id in cited_provider_ids
        ):
            document_key = _source_document_key(source, metadata)
            if document_key:
                cited_document_keys.add(document_key)

    if not cited_document_keys:
        return sources

    curated = [
        source
        for source in sources
        if _source_document_key(source, _source_metadata(source)) in cited_document_keys
    ]
    if not curated:
        return sources
    if max_sources is not None:
        return curated[: max(1, int(max_sources))]
    return curated


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
    lines.append(f"**Audit-Status:** {_audit_status_label(sources, l10n)}")
    lines.append(f"**Claim-Abdeckung:** {_claim_coverage_label(sources, l10n)}")
    lines.append("")

    for source in sources[:max_sources]:
        metadata = _source_metadata(source)
        source_id = _source_id(source, metadata)
        role = _source_role_label(metadata, l10n)
        claim = _audit_claim(source, metadata, l10n)
        document = _audit_document(source, metadata)
        location = _source_location(metadata, l10n)
        if metadata.get("locator_quality") in {"unknown", "snippet_only", "document", "chunk"}:
            location = f"{location} ({l10n.text('sources.locator_coarse')})"
        relevance = _audit_score_text(source, metadata, show_scores, l10n)
        match_type = str(
            metadata.get("match_type")
            or source.get("match_type")
            or l10n.text("sources.unknown")
        )
        actions = _source_actions(source, l10n) or l10n.text("sources.no_direct_link")
        lines.extend(
            [
                f"### {source_id} - {role}",
                f"- **Dokument:** {document}",
                f"- **Fundstelle:** {location}",
                f"- **Score/Match:** {relevance} / {match_type}",
                f"- **Aussage:** {claim}",
                f"- **Öffnen:** {actions}",
                "",
            ]
        )

    if len(sources) > max_sources:
        remaining_text = l10n.text("sources.more_documents", count=len(sources) - max_sources)
        lines.append(f"- {remaining_text}")

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


def _audit_status_label(sources: list[dict[str, Any]], l10n: Localizer) -> str:
    _ = l10n
    if not sources:
        return "keine belastbare Quelle"
    supported = [
        source
        for source in sources
        if bool(_source_metadata(source).get("used_in_answer"))
        or str(_source_metadata(source).get("source_role") or "") == "primary"
    ]
    if supported:
        return "belegt"
    return "retrieval-only"


def _claim_coverage_label(sources: list[dict[str, Any]], l10n: Localizer) -> str:
    _ = l10n
    if not sources:
        return "0/0 Aussagen belegt"
    supported = any(
        bool(_source_metadata(source).get("used_in_answer"))
        or str(_source_metadata(source).get("source_role") or "") == "primary"
        for source in sources
    )
    return "1/1 Aussagen belegt" if supported else "0/1 Aussagen belegt"


def _source_role_label(metadata: dict[str, Any], l10n: Localizer) -> str:
    _ = l10n
    role = str(metadata.get("source_role") or metadata.get("role") or "related")
    return {
        "primary": "Primärbeleg",
        "supporting": "stützend",
        "related": "verwandt",
        "unused": "nicht verwendet",
        "duplicate": "Dublette",
        "rejected": "verworfen",
    }.get(role, role)


def _audit_score_text(
    source: dict[str, Any],
    metadata: dict[str, Any],
    show_scores: bool,
    l10n: Localizer,
) -> str:
    audit_score = _score_float(source.get("audit_score") or metadata.get("audit_score"))
    if show_scores and audit_score is not None:
        return f"{audit_score:.2f}"
    return _audit_relevance(source, metadata, show_scores, l10n)


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


def _rank_hits_for_audit(
    hits: list[SourceHit],
    *,
    question: str | None,
    answer: str | None,
    max_sources: int | None,
) -> list[SourceHit]:
    exact_terms = _exact_query_terms(question)
    cited_provider_ids = _answer_provider_citation_ids(answer)
    cited_source_labels = _answer_source_labels(answer)
    preserve_source_labels = bool(cited_source_labels) and not cited_provider_ids
    evaluated: list[SourceHit] = []

    for hit in hits:
        components = _audit_score_components(hit, exact_terms=exact_terms)
        provider_used = (
            hit.provider_citation_id is not None
            and hit.provider_citation_id in cited_provider_ids
        )
        label_used = bool(hit.source_id and hit.source_id.upper() in cited_source_labels)
        used_in_answer = provider_used or label_used
        audit_score = _combined_audit_score(components, used_in_answer=used_in_answer)
        match_type = _match_type_from_components(components)
        role = _preliminary_source_role(
            components,
            audit_score=audit_score,
            used_in_answer=used_in_answer,
        )
        evaluated.append(
            replace(
                hit,
                source_role=role,
                match_type=match_type,
                audit_score=audit_score,
                score_components=components,
                used_in_answer=used_in_answer,
                claim_ids=("C1",) if used_in_answer or components["exact_match"] >= 1.0 else (),
                support_status=(
                    "supported"
                    if used_in_answer or components["exact_match"] >= 1.0
                    else "related"
                ),
            )
        )

    if preserve_source_labels:
        evaluated.sort(key=lambda hit: hit.rank)
    else:
        evaluated.sort(key=_audit_hit_sort_key)

    primary_assigned = False
    final_hits: list[SourceHit] = []
    for display_rank, hit in enumerate(evaluated, start=1):
        role = hit.source_role
        if role == "primary":
            if primary_assigned:
                role = "supporting"
            else:
                primary_assigned = True
        rank = hit.rank if preserve_source_labels else display_rank
        source_id = (
            hit.source_id
            if preserve_source_labels and hit.source_id
            else f"S{display_rank}"
        )
        citation_label = (
            hit.citation_label
            if preserve_source_labels and hit.citation_label
            else source_id
        )
        final_hits.append(
            replace(
                hit,
                rank=rank,
                source_id=source_id,
                citation_label=citation_label,
                source_role=role,
            )
        )

    if max_sources is not None:
        limit = max(1, int(max_sources))
        return final_hits[:limit]
    return final_hits


def _source_hit_from_event(source: dict[str, Any], *, index: int) -> SourceHit:
    metadata = _source_metadata(source)
    rank = _int_or_none(source.get("rank") or metadata.get("rank")) or index
    source_id = str(source.get("source_id") or metadata.get("source_id") or f"S{rank}")
    provider_id = _int_or_none(metadata.get("provider_citation_id"))
    if provider_id is None:
        provider_id = _int_or_none(metadata.get("reference_id"))
    title = str(
        source.get("name")
        or metadata.get("document_name")
        or metadata.get("doc_name")
        or f"Quelle {rank}"
    )
    return SourceHit(
        rank=rank,
        title=title,
        snippet=str(source.get("snippet") or source.get("text") or ""),
        source_id=source_id,
        document_name=metadata.get("document_name") or title,
        path=metadata.get("path"),
        page=metadata.get("page"),
        line=metadata.get("line"),
        line_start=metadata.get("line_start"),
        line_end=metadata.get("line_end"),
        section=metadata.get("section"),
        chunk_id=metadata.get("chunk_id"),
        score=source.get("score") or metadata.get("score"),
        preview_url=source.get("preview_url") or source.get("url") or metadata.get("preview_url"),
        original_url=source.get("original_url") or metadata.get("original_url"),
        dataset_id=metadata.get("dataset_id"),
        dataset_name=metadata.get("dataset_name"),
        document_id=metadata.get("document_id"),
        repo_id=metadata.get("repo_id"),
        file_id=metadata.get("file_id"),
        seafile_library_id=metadata.get("seafile_library_id"),
        seafile_library_name=metadata.get("seafile_library_name"),
        file_type=metadata.get("file_type"),
        mime_type=metadata.get("mime_type"),
        position=metadata.get("position") or metadata.get("positions"),
        locator_quality=str(metadata.get("locator_quality") or "unknown"),
        citation_label=str(
            source.get("citation_label")
            or metadata.get("citation_label")
            or source_id
        ),
        provider_citation_id=provider_id,
        source_role=str(
            metadata.get("source_role")
            or metadata.get("role")
            or source.get("source_role")
            or "related"
        ),
        match_type=str(metadata.get("match_type") or source.get("match_type") or "semantic"),
        audit_score=_score_float(source.get("audit_score") or metadata.get("audit_score")),
        score_components=dict(
            metadata.get("score_components") or source.get("score_components") or {}
        ),
        used_in_answer=bool(metadata.get("used_in_answer") or source.get("used_in_answer")),
        claim_ids=tuple(metadata.get("claim_ids") or source.get("claim_ids") or ()),
        support_status=str(
            metadata.get("support_status")
            or source.get("support_status")
            or "not_evaluated"
        ),
        language="de",
        source_dto_version=str(
            source.get("source_dto_version")
            or metadata.get("source_dto_version")
            or SOURCE_DTO_VERSION
        ),
        status=str(source.get("status") or metadata.get("status") or "available"),
        raw=dict(source),
    )


def _provider_citation_id(raw: dict[str, Any], *, fallback: int) -> int:
    for key in ("provider_citation_id", "citation_id", "reference_id", "ref_id"):
        value = _int_or_none(raw.get(key))
        if value is not None:
            return value
    return fallback


def _exact_query_terms(question: str | None) -> tuple[str, ...]:
    text = str(question or "")
    terms: list[str] = []
    terms.extend(match.group(0) for match in _EXACT_QUERY_TOKEN_RE.finditer(text))
    for pattern in (r"`([^`]{4,160})`", r'"([^"]{4,160})"'):
        terms.extend(match.group(1) for match in re.finditer(pattern, text))
    normalized: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = " ".join(str(term).split()).strip()
        if len(clean) < 4:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(clean)
    return tuple(normalized[:12])


def _answer_provider_citation_ids(answer: str | None) -> set[int]:
    ids = {int(match.group(1)) for match in _RAGFLOW_INLINE_CITATION_RE.finditer(str(answer or ""))}
    ids.update(
        int(match.group(1))
        for match in re.finditer(
            r"\{\{\s*source\s*:\s*(\d+)\s*\}\}",
            str(answer or ""),
            flags=re.IGNORECASE,
        )
    )
    ids.update(int(match.group(1)) for match in re.finditer(r"##(\d+)\$\$", str(answer or "")))
    return ids


def _answer_source_labels(answer: str | None) -> set[str]:
    return {f"S{match.group(1)}".upper() for match in _SOURCE_LABEL_RE.finditer(str(answer or ""))}


def _source_label(source: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(
        source.get("source_id")
        or source.get("citation_label")
        or metadata.get("source_id")
        or metadata.get("citation_label")
        or ""
    ).upper()


def _source_document_key(source: dict[str, Any], metadata: dict[str, Any]) -> str:
    for value in (
        metadata.get("document_id"),
        metadata.get("path"),
        metadata.get("document_name"),
        metadata.get("doc_name"),
        source.get("name"),
    ):
        text = " ".join(str(value or "").split()).casefold()
        if text:
            return text
    return ""


def _audit_score_components(
    hit: SourceHit,
    *,
    exact_terms: tuple[str, ...],
) -> dict[str, float]:
    source_text = _source_match_text(hit).casefold()
    exact_match = 0.0
    keyword = 0.0
    if exact_terms:
        matches = sum(1 for term in exact_terms if term.casefold() in source_text)
        keyword = matches / len(exact_terms)
        exact_match = 1.0 if matches else 0.0
    vector = _score_float(hit.score) or 0.0
    reranker = _score_float(
        hit.raw.get("reranker_score")
        or hit.raw.get("rerank_score")
        or hit.raw.get("relevance_score")
        or hit.raw.get("score")
        or hit.raw.get("similarity")
    )
    if reranker is None:
        reranker = vector
    locator = _locator_quality_score(hit.locator_quality)
    authority = 1.0 if hit.original_url or hit.path or hit.document_id else 0.5
    duplicate_penalty = 0.0
    weak_locator_penalty = 0.1 if hit.locator_quality in {"unknown", "snippet_only"} else 0.0
    return {
        "exact_match": round(exact_match, 3),
        "keyword": round(keyword, 3),
        "vector": round(vector, 3),
        "reranker": round(reranker, 3),
        "locator_quality": round(locator, 3),
        "source_authority": round(authority, 3),
        "duplicate_penalty": duplicate_penalty,
        "weak_locator_penalty": weak_locator_penalty,
    }


def _combined_audit_score(
    components: dict[str, float],
    *,
    used_in_answer: bool,
) -> float:
    score = (
        0.35 * components["exact_match"]
        + 0.25 * components["reranker"]
        + 0.15 * components["keyword"]
        + 0.15 * components["vector"]
        + 0.05 * components["locator_quality"]
        + 0.05 * components["source_authority"]
        - components["duplicate_penalty"]
        - components["weak_locator_penalty"]
    )
    if used_in_answer:
        score += 0.15
    if components["exact_match"] >= 1.0:
        score = max(score, 0.95)
    return round(max(0.0, min(1.0, score)), 3)


def _match_type_from_components(components: dict[str, float]) -> str:
    if components["exact_match"] >= 1.0:
        return "exact_string_match"
    if components["keyword"] > 0:
        return "keyword_match"
    if components["reranker"] >= 0.7 and components["vector"] >= 0.5:
        return "hybrid_reranked"
    if components["vector"] > 0:
        return "semantic"
    return "unknown"


def _preliminary_source_role(
    components: dict[str, float],
    *,
    audit_score: float,
    used_in_answer: bool,
) -> str:
    if used_in_answer or components["exact_match"] >= 1.0:
        return "primary"
    if audit_score >= 0.7:
        return "supporting"
    if audit_score < 0.25:
        return "unused"
    return "related"


def _audit_hit_sort_key(hit: SourceHit) -> tuple[int, float, int]:
    role_order = {
        "primary": 0,
        "supporting": 1,
        "related": 2,
        "unused": 3,
        "duplicate": 4,
        "rejected": 5,
    }
    return (
        role_order.get(hit.source_role, 6),
        -(hit.audit_score or 0.0),
        hit.rank,
    )


def _source_match_text(hit: SourceHit) -> str:
    parts = [
        hit.title,
        hit.document_name,
        hit.path,
        hit.snippet,
        hit.chunk_id,
        hit.document_id,
    ]
    for key in ("document_name", "doc_name", "path", "source_path", "title", "name"):
        value = hit.raw.get(key)
        if value not in (None, ""):
            parts.append(str(value))
    return "\n".join(str(part) for part in parts if part not in (None, ""))


def _locator_quality_score(value: str) -> float:
    return {
        "exact_line": 1.0,
        "line": 1.0,
        "page": 0.9,
        "section": 0.85,
        "position": 0.8,
        "chunk": 0.65,
        "document": 0.45,
        "snippet_only": 0.35,
        "unknown": 0.2,
    }.get(str(value or "unknown"), 0.2)


def sign_preview_payload(
    payload: dict[str, Any],
    secret: str,
    *,
    now: int | None = None,
    ttl_seconds: int = PREVIEW_TOKEN_TTL_SECONDS,
    purpose: str = SOURCE_PREVIEW_PURPOSE,
    audience: str = OPENWEBUI_PREVIEW_AUDIENCE,
) -> str:
    if ttl_seconds <= 0:
        raise ValueError("preview token ttl must be positive")
    if not purpose or not audience:
        raise ValueError("preview token purpose and audience are required")
    issued_at = int(time.time()) if now is None else int(now)
    body = dict(payload)
    body.update(
        {
            "v": PREVIEW_TOKEN_VERSION,
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
            "purpose": purpose,
            "aud": audience,
        }
    )
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = "z" + _b64encode(zlib.compress(raw, level=9))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_preview_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
    expected_purpose: str = SOURCE_PREVIEW_PURPOSE,
    expected_audience: str = OPENWEBUI_PREVIEW_AUDIENCE,
) -> dict[str, Any]:
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
    version = _preview_token_int_claim(payload, "v")
    issued_at = _preview_token_int_claim(payload, "iat")
    expires_at = _preview_token_int_claim(payload, "exp")
    current_time = int(time.time()) if now is None else int(now)
    if version != PREVIEW_TOKEN_VERSION:
        raise ValueError("unsupported preview token version")
    if issued_at > current_time:
        raise ValueError("preview token issued in the future")
    if expires_at <= issued_at or current_time >= expires_at:
        raise ValueError("preview token expired")
    if payload.get("purpose") != expected_purpose:
        raise ValueError("invalid preview token purpose")
    if payload.get("aud") != expected_audience:
        raise ValueError("invalid preview token audience")
    return payload


def _preview_token_int_claim(payload: dict[str, Any], name: str) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid preview token {name}")
    return value


def _normalize_reference(
    raw: dict[str, Any],
    *,
    index: int,
    provider_citation_id: int,
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
    if document_name or source_path:
        document_name = user_facing_document_name(document_name, source_path)
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
    text_fragment_url = None
    if page in (None, ""):
        text_fragment_url = build_text_fragment_url(original_url, snippet, enabled=True)
    source_open_url_kind = shared_open_url_kind(
        text_fragment_url or original_url,
        page=page,
        text_fragment_url=text_fragment_url,
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
        text_fragment_url=text_fragment_url,
        open_url_kind=source_open_url_kind,
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
        text_fragment_url=text_fragment_url,
        open_url_kind=source_open_url_kind,
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
        provider_citation_id=provider_citation_id,
        language=l10n.language,
        source_dto_version=str(raw.get("source_dto_version") or SOURCE_DTO_VERSION),
        status=str(raw.get("status") or "available"),
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
    text_fragment_url: str | None,
    open_url_kind: str,
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
            "text_fragment_url": text_fragment_url,
            "open_url_kind": open_url_kind,
            "score": score,
            "file_type": file_type,
            "mime_type": mime_type,
        }
        token = sign_preview_payload(
            payload,
            settings.openwebui_proxy_shared_secret,
            purpose=SOURCE_PREVIEW_PURPOSE,
            audience=OPENWEBUI_PREVIEW_AUDIENCE,
        )
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


def _collect_references(
    value: Any,
    references: list[dict[str, Any]],
    *,
    seen: set[int],
    root: bool = False,
    source_container: bool = False,
) -> None:
    if isinstance(value, (dict, list)):
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)

    if isinstance(value, dict):
        if _looks_like_chunk(value):
            references.append(value)
            return
        if source_container and _looks_like_loose_source(value):
            references.append(value)
            return

        choices = value.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict) and "reference" in message:
                    _collect_references(message["reference"], references, seen=seen)
                delta = choice.get("delta")
                if isinstance(delta, dict) and "reference" in delta:
                    _collect_references(delta["reference"], references, seen=seen)

        nested = value.get("data")
        if isinstance(nested, dict):
            for key in ("reference", "references", "sources", "source_documents", "citations"):
                if key in nested:
                    _collect_references(
                        nested[key],
                        references,
                        seen=seen,
                        source_container=key
                        in {"sources", "source_documents", "citations"},
                    )

        for key in (
            "reference",
            "references",
            "sources",
            "source_documents",
            "citations",
            "chunks",
        ):
            if key in value:
                if key == "chunks" and isinstance(value[key], dict):
                    for ref_id, item in _sorted_mapping_items(value[key]):
                        if isinstance(item, dict):
                            raw_item = dict(item)
                            raw_item.setdefault("reference_id", str(ref_id))
                            _collect_references(
                                raw_item,
                                references,
                                seen=seen,
                                source_container=True,
                            )
                    continue
                _collect_references(
                    value[key],
                    references,
                    seen=seen,
                    source_container=key
                    in {"sources", "source_documents", "citations", "chunks"},
                )
        if "doc_aggs" in value:
            _collect_references(value["doc_aggs"], references, seen=seen, source_container=True)
        if source_container:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    _collect_references(item, references, seen=seen, source_container=True)
        if root and not references:
            for item in value.values():
                if isinstance(item, (dict, list)):
                    _collect_references(item, references, seen=seen)
    elif isinstance(value, list):
        for item in value:
            _collect_references(item, references, seen=seen, source_container=source_container)


def _sorted_mapping_items(mapping: dict[Any, Any]) -> list[tuple[Any, Any]]:
    def sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
        number = _int_or_none(item[0])
        return (number if number is not None else 10**9, str(item[0]))

    return sorted(mapping.items(), key=sort_key)


def _looks_like_loose_source(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in ("content", "text", "snippet", "content_with_weight", "name")
    )


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
    return shared_locator_quality(
        page=page,
        section=section,
        line_start=line_start,
        line_end=line_end,
        position=position,
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=document_name,
        source_path=path,
        snippet=snippet,
    )


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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


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
        group.sort(key=lambda item: (_sort_score_key(item), _source_rank(item)))
    groups.sort(key=lambda group: (_sort_score_key(group[0]), _source_rank(group[0])))
    return groups


def _sort_score_key(source: dict[str, Any]) -> tuple[int, float]:
    value = _score_float(source.get("score") or _source_metadata(source).get("score"))
    if value is None:
        return (1, 0.0)
    return (0, -value)


def _sort_score(source: dict[str, Any]) -> tuple[int, float]:
    return _sort_score_key(source)


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
