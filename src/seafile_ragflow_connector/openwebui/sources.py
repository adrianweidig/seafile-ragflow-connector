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
    document_name: str | None = None
    path: str | None = None
    page: Any = None
    line: Any = None
    section: Any = None
    chunk_id: str | None = None
    score: Any = None
    preview_url: str | None = None
    original_url: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    document_id: str | None = None
    repo_id: str | None = None
    file_type: str | None = None
    mime_type: str | None = None
    position: Any = None
    citation_label: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def relevance(self) -> str:
        value = _score_float(self.score)
        if value is None:
            return "unbekannt"
        if value >= 0.8:
            return "hoch"
        if value >= 0.55:
            return "mittel"
        return "niedrig"

    @property
    def display_location(self) -> str:
        parts = []
        if self.page not in (None, ""):
            parts.append(f"Seite {self.page}")
        if self.section not in (None, ""):
            parts.append(f"Abschnitt {self.section}")
        if self.line not in (None, ""):
            parts.append(f"Zeile {self.line}")
        return " · ".join(parts) or "Fundstelle nicht angegeben"

    def metadata(self) -> dict[str, Any]:
        values = {
            "rank": self.rank,
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
            "position": self.position,
            "score": self.score,
            "relevance": self.relevance,
            "path": self.path,
            "repo_id": self.repo_id,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "original_url": self.original_url,
            "preview_url": self.preview_url,
        }
        return {key: value for key, value in values.items() if value not in (None, "")}

    def to_openwebui_source(self) -> dict[str, Any]:
        metadata = self.metadata()
        title = self.title or self.document_name or f"Quelle {self.rank}"
        return {
            "name": title,
            "document": [self.snippet or title],
            "metadata": [metadata],
            "source_metadata": metadata,
            "source": {"name": title, "url": self.preview_url},
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
        sources.append(source.to_openwebui_source())
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


def render_sources_markdown(
    sources: list[dict[str, Any]],
    *,
    show_scores: bool = True,
    show_debug: bool = False,
    max_documents: int = 6,
) -> str:
    if not sources:
        return "Keine passenden Quellen gefunden."
    groups = _group_sources_by_document(sources)
    lines = ["## Gefundene Quellen", ""]
    for display_index, group in enumerate(groups[:max_documents], start=1):
        best = group[0]
        metadata = _source_metadata(best)
        name = _markdown_plain(str(best.get("name") or "Quelle"))
        location = _source_location(metadata)
        relevance = _relevance_label(metadata, best) if show_scores else ""
        hit_count = "" if len(group) == 1 else f" · {len(group)} Treffer"
        summary_parts = [part for part in (location, relevance) if part]
        lines.append(f"### {display_index}. {name}")
        if summary_parts or hit_count:
            lines.append(f"**{' · '.join(summary_parts)}{hit_count}**")
        actions = _source_actions(best)
        if actions:
            lines.append(f"**Aktionen:** {actions}")
        snippet = _clean_reference_text(str(best.get("snippet") or best.get("text") or "")) or ""
        if snippet:
            lines.append("")
            lines.extend(_blockquote(_compact_markdown_text(snippet, _SOURCE_SNIPPET_MAX_CHARS)))
        other_locations = [
            _source_location(_source_metadata(item))
            for item in group[1:4]
            if _source_location(_source_metadata(item)) != location
        ]
        if other_locations:
            lines.append("")
            lines.append(f"Weitere Fundstellen: {', '.join(other_locations)}")
        if show_debug:
            debug_parts = _debug_parts(metadata)
            if debug_parts:
                lines.append("")
                lines.append(f"Debug: {' · '.join(debug_parts)}")
        lines.append("")
    if len(groups) > max_documents:
        lines.append(f"_Weitere {len(groups) - max_documents} Dokumente wurden ausgeblendet._")
    return "\n".join(lines).rstrip()


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
    page = raw.get("page") or raw.get("page_num") or raw.get("page_number") or _first_page(position)
    file_row = files_by_document_id.get(document_id or "")
    if file_row:
        document_name = _safe_document_name_from_file_row(file_row) or document_name
    source_path = _source_path(raw, file_row)
    repo_id = _repo_id(raw, file_row)
    file_type = _file_type(document_name or source_path)
    mime_type = _first_text(raw, "mime_type", "mime", "content_type")
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
        score=score,
        file_type=file_type,
        mime_type=mime_type,
    )
    title = document_name or f"Quelle {index}"
    return SourceHit(
        rank=index,
        title=title,
        document_name=document_name,
        path=source_path,
        page=page,
        line=raw.get("line") or raw.get("line_number"),
        section=raw.get("section"),
        chunk_id=chunk_id,
        score=score,
        snippet=snippet or "",
        preview_url=preview_url,
        original_url=original_url,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        document_id=document_id,
        repo_id=repo_id,
        file_type=file_type,
        mime_type=mime_type,
        position=position,
        citation_label=citation_label,
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
    position: Any,
    repo_id: str | None,
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
            "position": position,
            "snippet": _preview_snippet(snippet),
            "repo_id": repo_id,
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
        clean = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
        clean = re.sub(r"(?s)<[^>]+>", " ", clean)
        return clean
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


def _group_sources_by_document(sources: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        metadata = _source_metadata(source)
        key = str(
            metadata.get("path")
            or metadata.get("document_id")
            or metadata.get("document_name")
            or source.get("name")
            or source.get("title")
            or "Quelle"
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


def _source_location(metadata: dict[str, Any]) -> str:
    parts = []
    if metadata.get("page") not in (None, ""):
        parts.append(f"Seite {metadata.get('page')}")
    if metadata.get("section") not in (None, ""):
        parts.append(f"Abschnitt {metadata.get('section')}")
    if metadata.get("line") not in (None, ""):
        parts.append(f"Zeile {metadata.get('line')}")
    return " · ".join(parts) or "Fundstelle nicht angegeben"


def _relevance_label(metadata: dict[str, Any], source: dict[str, Any]) -> str:
    score = source.get("score") or metadata.get("score")
    formatted = _format_score(score)
    relevance = metadata.get("relevance") or SourceHit(rank=1, title="", score=score).relevance
    if formatted:
        return f"Relevanz {relevance} ({formatted})"
    return f"Relevanz {relevance}"


def _source_actions(source: dict[str, Any]) -> str:
    preview_url = source.get("preview_url") or source.get("url")
    original_url = source.get("original_url") or _source_metadata(source).get("original_url")
    links = []
    if preview_url:
        links.append(f"[Preview öffnen]({preview_url})")
    if original_url:
        links.append(f"[Original öffnen]({original_url})")
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


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    return _b64decode_bytes(value).decode("utf-8")


def _b64decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
