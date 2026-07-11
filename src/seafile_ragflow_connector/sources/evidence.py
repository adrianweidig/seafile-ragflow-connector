from __future__ import annotations

# ruff: noqa: E501
import html
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


@dataclass(frozen=True)
class EvidenceHit:
    source_id: str
    citation_label: str
    rank: int
    document_name: str
    dataset_name: str
    repo_id: str | None = None
    ragflow_dataset_id: str | None = None
    source_path: str | None = None
    snippet: str = ""
    snippet_before: str | None = None
    snippet_after: str | None = None
    highlight_terms: tuple[str, ...] = ()
    page: Any = None
    line_start: Any = None
    line_end: Any = None
    section: Any = None
    chunk_id: str | None = None
    document_id: str | None = None
    score: float | None = None
    match_type: str = "semantic"
    source_role: str = "related"
    locator_quality: str = "unknown"
    preview_url: str | None = None
    open_url: str | None = None
    open_url_kind: str = "none"
    text_fragment_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score_percent(self) -> int | None:
        if self.score is None:
            return None
        return int(round(max(0.0, min(1.0, self.score)) * 100))

    @property
    def location_label(self) -> str:
        return source_location_label(
            page=self.page,
            section=self.section,
            line_start=self.line_start,
            line_end=self.line_end,
            locator_quality=self.locator_quality,
        )

    def preview_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "citation_label": self.citation_label,
            "dataset_id": self.ragflow_dataset_id,
            "dataset_name": self.dataset_name,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "chunk_id": self.chunk_id,
            "page": self.page,
            "section": self.section,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "locator_quality": self.locator_quality,
            "snippet": compact_text(self.snippet, 900),
            "repo_id": self.repo_id,
            "source_path": self.source_path,
            "original_url": self.open_url,
            "text_fragment_url": self.text_fragment_url,
            "open_url_kind": self.open_url_kind,
            "score": self.score,
            "match_type": self.match_type,
            "source_role": self.source_role,
        }

    def to_search_result(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "citation_label": self.citation_label,
            "rank": self.rank,
            "dataset_name": self.dataset_name,
            "repo_id": self.repo_id,
            "ragflow_dataset_id": self.ragflow_dataset_id,
            "document_name": self.document_name,
            "source_path": self.source_path or "",
            "snippet": self.snippet,
            "snippet_before": self.snippet_before,
            "snippet_after": self.snippet_after,
            "highlight_terms": list(self.highlight_terms),
            "locator": {
                "page": self.page,
                "line_start": self.line_start,
                "line_end": self.line_end,
                "section": self.section,
                "quality": self.locator_quality,
                "label": self.location_label,
            },
            "page": self.page,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "section": self.section,
            "score": self.score,
            "score_percent": self.score_percent,
            "match_type": self.match_type,
            "source_role": self.source_role,
            "locator_quality": self.locator_quality,
            "preview_url": self.preview_url,
            "open_url": self.open_url,
            "open_url_kind": self.open_url_kind,
            "text_fragment_url": self.text_fragment_url,
        }


def locator_quality(
    *,
    page: Any = None,
    section: Any = None,
    line_start: Any = None,
    line_end: Any = None,
    position: Any = None,
    chunk_id: str | None = None,
    document_id: str | None = None,
    document_name: str | None = None,
    source_path: str | None = None,
    snippet: str | None = None,
) -> str:
    if line_start not in (None, "") or line_end not in (None, ""):
        return "exact_line"
    if page not in (None, ""):
        return "page"
    if section not in (None, ""):
        return "section"
    if position not in (None, "", [], {}):
        return "position"
    if chunk_id:
        return "chunk"
    if document_id or document_name or source_path:
        return "document"
    if snippet:
        return "snippet_only"
    return "unknown"


def line_range(start: Any, end: Any) -> str:
    if start in (None, "") and end in (None, ""):
        return ""
    if end in (None, "") or str(end) == str(start):
        return str(start)
    if start in (None, ""):
        return str(end)
    return f"{start}-{end}"


def source_location_label(
    *,
    page: Any = None,
    section: Any = None,
    line_start: Any = None,
    line_end: Any = None,
    locator_quality: str = "unknown",
) -> str:
    parts: list[str] = []
    if page not in (None, ""):
        parts.append(f"Seite {page}")
    if section not in (None, ""):
        parts.append(f"Abschnitt {section}")
    lines = line_range(line_start, line_end)
    if lines:
        parts.append(f"Zeile {lines}")
    if parts:
        return " · ".join(parts)
    if locator_quality == "snippet_only":
        return "Treffertext"
    if locator_quality in {"document", "chunk", "position"}:
        return "Dokumentstelle"
    return "Fundstelle unbekannt"


def score_value(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1:
        score = score / 100
    return max(0.0, min(1.0, score))


def build_text_fragment_url(open_url: str | None, snippet: str | None, *, enabled: bool) -> str | None:
    if not enabled or not open_url or not snippet:
        return None
    parsed = urlsplit(open_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    text = stable_text_fragment(snippet)
    if not text:
        return None
    fragment = f":~:text={quote(text, safe='')}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, fragment))


def stable_text_fragment(snippet: str | None) -> str | None:
    clean = compact_text(snippet, 180)
    clean = clean.replace("----- BEGIN SOURCE CONTENT -----", "")
    clean = clean.replace("----- END SOURCE CONTENT -----", "")
    clean = " ".join(clean.split())
    if len(clean) < 18:
        return None
    if len(clean) > 120:
        clean = clean[:120].rsplit(" ", 1)[0].strip()
    return clean or None


def open_url_kind(
    open_url: str | None,
    *,
    page: Any = None,
    text_fragment_url: str | None = None,
) -> str:
    if text_fragment_url:
        return "text_fragment"
    if open_url and page not in (None, "") and f"#page={page}" in open_url:
        return "page_anchor"
    if open_url:
        return "original"
    return "none"


def compact_text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def render_preview_html(
    token: str | None,
    secret: str | None,
    *,
    language: str = "de",
    expected_purpose: str = "source_preview",
    expected_audience: str = "openwebui_proxy",
) -> str:
    from seafile_ragflow_connector.openwebui.sources import verify_preview_token

    if not token or not secret:
        return _preview_unavailable_html(language)
    try:
        payload = verify_preview_token(
            token,
            secret,
            expected_purpose=expected_purpose,
            expected_audience=expected_audience,
        )
    except ValueError:
        return _preview_unavailable_html(language)
    return render_preview_payload_html(payload, language=language)


def render_preview_payload_html(payload: dict[str, Any], *, language: str = "de") -> str:
    del language
    title = _escape(_payload_text(payload, "document_name") or "Quelle")
    dataset = _escape(_payload_text(payload, "dataset_name") or "Bibliothek")
    citation = _escape(_payload_text(payload, "citation_label") or _payload_text(payload, "source_id") or "S?")
    source_path = _escape(_payload_text(payload, "source_path") or "")
    locator = source_location_label(
        page=_payload_text(payload, "page"),
        section=_payload_text(payload, "section"),
        line_start=_payload_text(payload, "line_start"),
        line_end=_payload_text(payload, "line_end"),
        locator_quality=_payload_text(payload, "locator_quality") or "unknown",
    )
    locator_html = _escape(locator)
    locator_quality_html = _escape(_payload_text(payload, "locator_quality") or "unknown")
    snippet_text = _clean_source_snippet(payload.get("snippet") or "")
    snippet = _escape(snippet_text)
    score = score_value(payload.get("score"))
    score_text = "unbekannt" if score is None else f"{score:.0%}"
    open_url = _safe_http_url(_payload_text(payload, "original_url"))
    text_fragment_url = _safe_http_url(_payload_text(payload, "text_fragment_url"))
    best_original = text_fragment_url or open_url
    original_action = (
        f'<a class="button primary" href="{_escape(best_original, quote=True)}" '
        'target="_blank" rel="noreferrer noopener">Original öffnen</a>'
        if best_original
        else '<span class="missing">Kein sicherer Originallink vorhanden</span>'
    )
    raw_json = _escape(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    empty = '<span class="empty">Keine Passage im Treffer vorhanden.</span>'
    snippet_html = f"<mark>{snippet}</mark>" if snippet else empty
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#f4f7fb; --panel:#fff; --soft:#eef4f8; --text:#111827; --muted:#64748b; --border:#d8e1ec; --accent:#0f766e; --accent-soft:#dff7f2; --mark:#fff4b8; --shadow:0 18px 52px rgba(15,23,42,.1); }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b1120; --panel:#121b2d; --soft:#18243a; --text:#f8fafc; --muted:#9aa8bc; --border:#2a3950; --accent:#2dd4bf; --accent-soft:#123f3b; --mark:#5b4b15; --shadow:0 26px 76px rgba(0,0,0,.35); }} }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Segoe UI,system-ui,-apple-system,BlinkMacSystemFont,sans-serif; line-height:1.55; letter-spacing:0; }}
    main {{ max-width:1120px; margin:0 auto; padding:28px 18px 46px; display:grid; gap:16px; }}
    .hero, .panel, .metric {{ border:1px solid var(--border); border-radius:8px; background:var(--panel); box-shadow:var(--shadow); }}
    .hero {{ padding:22px; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:start; border-left:5px solid var(--accent); }}
    h1 {{ margin:0; font-size:clamp(1.35rem,3vw,2.25rem); line-height:1.12; overflow-wrap:anywhere; }}
    .meta {{ margin:.6rem 0 0; color:var(--muted); overflow-wrap:anywhere; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:9px; justify-content:flex-end; }}
    .button {{ min-height:42px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:8px; padding:9px 13px; background:var(--panel); color:var(--text); font-weight:760; text-decoration:none; cursor:pointer; }}
    .button.primary {{ min-width:160px; background:var(--accent); border-color:var(--accent); color:white; }}
    .button:hover {{ transform:translateY(-1px); border-color:var(--accent); }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
    .metric {{ box-shadow:none; padding:14px; }}
    .metric span {{ display:block; color:var(--muted); font-size:.78rem; font-weight:800; text-transform:uppercase; }}
    .metric strong {{ display:block; margin-top:5px; overflow-wrap:anywhere; }}
    .panel-head {{ padding:15px 18px; border-bottom:1px solid var(--border); background:var(--soft); display:flex; justify-content:space-between; gap:12px; }}
    .panel-head h2 {{ margin:0; font-size:1.02rem; }}
    .panel-head p {{ margin:.25rem 0 0; color:var(--muted); }}
    pre.snippet {{ margin:0; padding:24px; white-space:pre-wrap; overflow-wrap:anywhere; background:var(--panel); font-size:1.04rem; line-height:1.78; max-height:52vh; overflow:auto; }}
    mark {{ background:var(--mark); color:var(--text); padding:2px 3px; border-radius:4px; box-decoration-break:clone; -webkit-box-decoration-break:clone; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }}
    dl {{ margin:0; padding:6px 18px 14px; }}
    dl div {{ display:grid; grid-template-columns:150px minmax(0,1fr); gap:12px; padding:10px 0; border-bottom:1px solid var(--border); }}
    dl div:last-child {{ border-bottom:0; }}
    dt {{ color:var(--muted); font-size:.84rem; }}
    dd {{ margin:0; font-weight:650; overflow-wrap:anywhere; }}
    details summary {{ padding:15px 18px; background:var(--soft); cursor:pointer; font-weight:800; }}
    pre.raw {{ margin:0; padding:16px; overflow:auto; max-height:360px; background:var(--panel); }}
    .missing {{ display:inline-flex; min-height:42px; align-items:center; border:1px solid var(--border); border-radius:8px; padding:9px 13px; color:var(--muted); }}
    .empty {{ color:var(--muted); font-style:italic; }}
    @media (max-width:800px) {{ .hero,.grid {{ grid-template-columns:1fr; }} .actions {{ justify-content:flex-start; }} .summary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width:560px) {{ main {{ padding:14px 10px 30px; }} .summary {{ grid-template-columns:1fr; }} dl div {{ grid-template-columns:1fr; gap:3px; }} .button,.missing {{ width:100%; }} }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <h1>{title}</h1>
        <p class="meta">{dataset} · {citation}{f" · {source_path}" if source_path else ""}</p>
      </div>
      <div class="actions">
        {original_action}
        <button class="button" type="button" data-copy-url>Link kopieren</button>
      </div>
    </section>
    <section class="summary" aria-label="Quellenüberblick">
      <article class="metric"><span>Bibliothek</span><strong>{dataset}</strong></article>
      <article class="metric"><span>Fundstelle</span><strong>{locator_html}</strong></article>
      <article class="metric"><span>Relevanz</span><strong>{_escape(score_text)}</strong></article>
      <article class="metric"><span>Qualität</span><strong>{locator_quality_html}</strong></article>
    </section>
    <section class="panel">
      <div class="panel-head"><div><h2>Verwendete Passage</h2><p>Diese Passage stammt aus dem autorisierten RAGFlow-Treffer.</p></div><button class="button" type="button" data-copy-target="snippet">Passage kopieren</button></div>
      <pre class="snippet" id="snippet">{snippet_html}</pre>
    </section>
    <section class="grid">
      <article class="panel"><div class="panel-head"><div><h2>Fundstelle</h2><p>Die Genauigkeit hängt von den gelieferten RAGFlow-Metadaten ab.</p></div></div><dl>{_definition_rows([("Zitat", citation), ("Ort", locator_html), ("Locator", locator_quality_html)])}</dl></article>
      <article class="panel"><div class="panel-head"><div><h2>Original</h2><p>Der Originallink ist ein bestmöglicher Sprung in Seafile.</p></div></div><dl>{_definition_rows([("Dokument", title), ("Pfad", source_path or "unbekannt"), ("Linktyp", _escape(_payload_text(payload, "open_url_kind") or "original"))])}</dl></article>
    </section>
    <details class="panel"><summary>Technische Details</summary><pre class="raw" id="raw">{raw_json}</pre></details>
  </main>
  <script>
    async function copyText(text, button) {{
      const old = button.textContent;
      try {{ await navigator.clipboard.writeText(text); button.textContent = 'Kopiert'; }}
      catch (err) {{ button.textContent = 'Nicht kopiert'; }}
      setTimeout(() => button.textContent = old, 1300);
    }}
    document.querySelectorAll('[data-copy-url]').forEach(btn => btn.addEventListener('click', () => copyText(location.href, btn)));
    document.querySelectorAll('[data-copy-target]').forEach(btn => btn.addEventListener('click', () => {{
      const target = document.getElementById(btn.dataset.copyTarget || '');
      copyText(target ? target.textContent || '' : '', btn);
    }}));
  </script>
</body>
</html>"""


def _preview_unavailable_html(language: str) -> str:
    del language
    return """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Quelle nicht verfügbar</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;padding:18px;background:#f4f7fb;color:#111827;font-family:Segoe UI,system-ui,sans-serif}main{max-width:620px;border:1px solid #d8e1ec;border-left:5px solid #0f766e;border-radius:8px;background:#fff;padding:28px;box-shadow:0 18px 52px rgba(15,23,42,.1)}h1{margin:0 0 .6rem;font-size:1.8rem}p{color:#64748b;line-height:1.55}</style></head><body><main><h1>Quelle nicht verfügbar</h1><p>Der Vorschau-Link ist ungültig oder die Signatur konnte nicht geprüft werden.</p></main></body></html>"""


def _definition_rows(rows: list[tuple[str, str]]) -> str:
    return "".join(f"<div><dt>{_escape(label)}</dt><dd>{value}</dd></div>" for label, value in rows)


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip()
    lowered = clean.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return clean
    return None


def _clean_source_snippet(value: Any) -> str:
    clean = html.unescape(str(value or ""))
    if "<" in clean or "&" in clean:
        parser = _HTMLToTextParser()
        try:
            parser.feed(clean)
            parser.close()
        except Exception:
            return ""
        clean = html.unescape(parser.text)
    return "\n".join(line.strip() for line in clean.splitlines() if line.strip())


def _escape(value: Any, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


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
            self._parts.append("\n")
        elif name in {"td", "th"}:
            self._parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        name = str(tag or "").lower()
        if name in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if not self._ignored_depth and name in {"p", "div", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)
