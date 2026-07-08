from __future__ import annotations

# ruff: noqa: E501

SEARCH_HTML = r"""<!doctype html>
<html lang="de" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wissenssuche</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --grid: rgba(148, 163, 184, .22);
      --surface: #ffffff;
      --surface-2: #f8fbfd;
      --surface-3: #eef4f8;
      --selected: #e0f7f1;
      --text: #172033;
      --strong: #0f172a;
      --muted: #64748b;
      --border: #d7e2ec;
      --border-strong: #a7bacb;
      --accent: #0f766e;
      --accent-2: #14b8a6;
      --accent-soft: #dff7f2;
      --accent-text: #075e57;
      --danger: #b42318;
      --danger-soft: #fff1f0;
      --warning: #9a5300;
      --warning-soft: #fff7ed;
      --hit: #eab308;
      --hit-soft: rgba(234, 179, 8, .12);
      --shadow: 0 18px 46px rgba(15, 23, 42, .08);
      --focus: 0 0 0 3px rgba(20, 184, 166, .25);
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #0d1422;
      --grid: rgba(148, 163, 184, .12);
      --surface: #151f31;
      --surface-2: #101827;
      --surface-3: #1c293d;
      --selected: #113f3c;
      --text: #e6eef8;
      --strong: #f8fafc;
      --muted: #9aa8bc;
      --border: #2f3f55;
      --border-strong: #52647a;
      --accent: #2dd4bf;
      --accent-2: #5eead4;
      --accent-soft: #123f3b;
      --accent-text: #8ff5e6;
      --danger: #fca5a5;
      --danger-soft: #3b1f24;
      --warning: #fbbf24;
      --warning-soft: #3d2f17;
      --hit: #facc15;
      --hit-soft: rgba(250, 204, 21, .12);
      --shadow: 0 24px 70px rgba(0, 0, 0, .34);
      --focus: 0 0 0 3px rgba(45, 212, 191, .28);
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html { min-width: 320px; }
    body {
      margin: 0;
      min-width: 320px;
      min-height: 100vh;
      background:
        linear-gradient(90deg, transparent 0, transparent 23px, var(--grid) 24px),
        linear-gradient(0deg, transparent 0, transparent 23px, var(--grid) 24px),
        radial-gradient(circle at 25% -8%, color-mix(in srgb, var(--accent-soft) 52%, transparent), transparent 34rem),
        var(--bg);
      background-size: 24px 24px, 24px 24px, auto, auto;
      color: var(--text);
      font-family: Segoe UI, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.45;
      letter-spacing: 0;
    }
    button, input { font: inherit; letter-spacing: 0; }
    button:focus-visible, input:focus-visible, a:focus-visible { outline: none; box-shadow: var(--focus); }
    button { cursor: pointer; }
    .shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header {
      min-height: 70px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 0 28px;
      border-bottom: 1px solid var(--border);
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      backdrop-filter: blur(14px);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .brand-mark {
      width: 38px;
      height: 38px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent);
      color: #042321;
      flex: 0 0 auto;
      box-shadow: inset 0 -10px 18px rgba(0, 0, 0, .12);
    }
    .brand-mark svg {
      width: 20px;
      height: 20px;
      stroke: currentColor;
      stroke-width: 2.6;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    h1 { margin: 0; color: var(--strong); font-size: 1.16rem; line-height: 1.1; }
    .user-line { margin-top: 2px; color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
    .header-actions { display: flex; align-items: center; gap: 10px; }
    .theme-toggle {
      display: inline-grid;
      grid-template-columns: 1fr 1fr;
      min-width: 150px;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
    }
    .theme-option {
      min-height: 38px;
      border: 0;
      padding: 0 12px;
      background: transparent;
      color: var(--muted);
      font-weight: 780;
    }
    .theme-option[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent-text); }
    main {
      width: min(1680px, 100%);
      margin: 0 auto;
      padding: 24px;
      display: grid;
      grid-template-columns: minmax(250px, 300px) minmax(0, 1fr) minmax(260px, 320px);
      gap: 16px;
      align-items: start;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: color-mix(in srgb, var(--surface) 98%, transparent);
      box-shadow: var(--shadow);
    }
    .library-panel, .sources-panel { position: sticky; top: 94px; max-height: calc(100vh - 118px); overflow: hidden; display: grid; grid-template-rows: auto 1fr; }
    .panel-head {
      padding: 16px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      display: grid;
      gap: 12px;
    }
    .head-line { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
    .head-actions { display: inline-flex; align-items: center; gap: 8px; }
    .panel h2 { margin: 0; color: var(--strong); font-size: 1rem; line-height: 1.2; }
    .subtle { margin: 3px 0 0; color: var(--muted); font-size: .88rem; }
    .count-pill {
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--surface-3);
      color: var(--muted);
      font-size: .8rem;
      font-weight: 850;
      white-space: nowrap;
    }
    .panel-toggle {
      display: none;
      min-height: 30px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 0 9px;
      background: var(--surface-2);
      color: var(--text);
      font-size: .8rem;
      font-weight: 800;
    }
    .panel-toggle:hover { border-color: var(--accent); color: var(--accent-text); }
    .profile-search, .query-input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-2);
      color: var(--text);
      outline: none;
    }
    .profile-search { min-height: 38px; padding: 0 11px; font-size: .92rem; }
    .query-input {
      min-height: 46px;
      max-height: 96px;
      padding: 11px 14px;
      font-size: 1rem;
      background: var(--surface);
      resize: vertical;
      line-height: 1.35;
    }
    .profile-search:focus, .query-input:focus { border-color: var(--accent); box-shadow: var(--focus); }
    .profile-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .mini-button, .secondary, .source-chip {
      min-height: 36px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 11px;
      background: var(--surface);
      color: var(--text);
      font-weight: 760;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
    }
    .mini-button:hover, .secondary:hover, .source-chip:hover { border-color: var(--accent); color: var(--accent-text); }
    .mini-button:disabled, .primary:disabled { opacity: .52; cursor: not-allowed; }
    .profile-list { padding: 9px; display: grid; gap: 6px; overflow: auto; }
    .profile-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      padding: 9px 10px;
      border: 1px solid transparent;
      border-radius: 8px;
      cursor: pointer;
    }
    .profile-row:hover { background: var(--surface-3); }
    .profile-row:has(input:checked) { background: color-mix(in srgb, var(--accent) 13%, var(--surface)); border-color: color-mix(in srgb, var(--accent) 54%, var(--border)); }
    .profile-row input { width: 16px; height: 16px; margin-top: 3px; accent-color: var(--accent); }
    .profile-name { display: block; color: var(--strong); font-weight: 800; overflow-wrap: anywhere; }
    .profile-kind { display: block; margin-top: 2px; color: var(--muted); font-size: .82rem; }
    .search-panel {
      min-width: 0;
      overflow: hidden;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .search-panel > *,
    .viewer,
    .viewer-head,
    .viewer-title,
    .viewer-actions,
    .answer,
    .inline-sources,
    .results,
    .query-area,
    .inline-source-rail,
    .citation-strip { min-width: 0; }
    .query-area { padding: 14px 16px; display: grid; gap: 10px; border-top: 1px solid var(--border); background: var(--surface); }
    .composer { position: sticky; bottom: 0; z-index: 4; box-shadow: 0 -18px 34px rgba(15, 23, 42, .08); }
    .query-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: start; }
    .primary {
      min-height: 46px;
      height: 46px;
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 0 18px;
      background: var(--accent);
      color: #fff;
      font-weight: 900;
    }
    .primary:hover { background: color-mix(in srgb, var(--accent) 82%, #000); border-color: color-mix(in srgb, var(--accent) 82%, #000); }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
    .segments { display: inline-grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface-2); }
    .segment { min-height: 36px; border: 0; padding: 0 13px; background: transparent; color: var(--muted); font-weight: 780; }
    .segment[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent-text); }
    .topk { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: .9rem; }
    .topk input { width: 72px; height: 38px; border: 1px solid var(--border); border-radius: 8px; padding: 0 9px; background: var(--surface-2); color: var(--text); }
    .state { padding: 15px 18px; border-bottom: 1px solid var(--border); color: var(--muted); background: var(--surface-2); }
    .state.loading { color: var(--accent-text); background: var(--accent-soft); }
    .state.success { color: var(--muted); background: var(--surface); }
    .state.error { color: var(--danger); background: var(--danger-soft); }
    .answer {
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      display: grid;
      gap: 11px;
    }
    .answer h2 { margin: 0; color: var(--strong); font-size: 1.08rem; }
    .answer-text { max-width: 88ch; color: var(--text); overflow-wrap: anywhere; font-size: 1rem; line-height: 1.5; }
    .answer-text p { margin: 0 0 10px; }
    .answer-text p:last-child { margin-bottom: 0; }
    .answer-citation-marker {
      min-height: 24px;
      padding: 1px 7px;
      vertical-align: baseline;
      font-size: .86rem;
      cursor: pointer;
    }
    .viewer {
      min-height: 0;
      border-bottom: 1px solid var(--border);
      background: var(--surface-2);
      display: grid;
      grid-template-rows: auto clamp(170px, 22vh, 260px) auto;
    }
    .viewer-head {
      padding: 14px 16px;
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }
    .viewer-title { min-width: 0; display: grid; gap: 3px; }
    .viewer-title strong { color: var(--strong); overflow-wrap: anywhere; }
    .viewer-title span { color: var(--muted); font-size: .86rem; overflow-wrap: anywhere; }
    .viewer-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: end; }
    .viewer-actions .secondary { min-height: 34px; padding: 0 9px; }
    .viewer-actions .primary-viewer-action {
      border-color: color-mix(in srgb, var(--accent) 54%, var(--border));
      background: var(--accent-soft);
      color: var(--accent-text);
    }
    .viewer-frame, .viewer-text-preview, .viewer-pdf-scroll {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
    }
    .viewer-frame {
      background: #fff;
    }
    .viewer-pdf-scroll {
      box-sizing: border-box;
      padding: 10px;
      background: #f8fafc;
      overflow: auto;
      display: flex;
      align-items: flex-start;
      justify-content: center;
    }
    html[data-theme="dark"] .viewer-pdf-scroll {
      background: #0f172a;
    }
    .viewer-pdf-page {
      display: block;
      width: min(100%, 920px);
      min-width: min(720px, 100%);
      height: auto;
      background: #fff;
      box-shadow: 0 12px 34px rgba(15, 23, 42, .14);
    }
    .viewer-text-preview {
      margin: 0;
      padding: 16px 18px;
      background: color-mix(in srgb, var(--surface-2) 92%, #000);
      color: var(--text);
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 500 .9rem/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }
    html[data-theme="light"] .viewer-text-preview {
      background: #fbfdff;
      color: #111827;
    }
    .viewer-empty {
      min-height: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      color: var(--muted);
      text-align: center;
    }
    .viewer-excerpt {
      padding: 10px 16px 11px;
      display: grid;
      gap: 7px;
      border-top: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      max-height: 118px;
      overflow: hidden;
    }
    .viewer-excerpt.is-expanded { max-height: 240px; overflow: auto; }
    .viewer-excerpt-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .viewer-kicker { color: var(--muted); font-size: .76rem; font-weight: 850; text-transform: uppercase; }
    .viewer-passage-actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; justify-content: end; }
    .passage-action {
      min-height: 28px;
      border: 1px solid var(--border);
      border-radius: 7px;
      padding: 0 9px;
      background: var(--surface-2);
      color: var(--text);
      font-size: .8rem;
      font-weight: 780;
    }
    .passage-action:hover { border-color: var(--accent); color: var(--accent-text); }
    .viewer-passage-text {
      margin: 0;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
      color: var(--strong);
      padding: 7px 10px 7px 12px;
      border-left: 3px solid color-mix(in srgb, var(--hit) 62%, var(--border));
      border-radius: 7px;
      background: color-mix(in srgb, var(--hit-soft) 70%, var(--surface));
    }
    .viewer-excerpt.is-expanded .viewer-passage-text { display: block; }
    .viewer-focus-note { color: var(--muted); font-size: .82rem; }
    .viewer-text-preview mark {
      background: color-mix(in srgb, var(--hit) 30%, transparent);
      color: #251a00;
      border-radius: 3px;
      padding: 0 1px;
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
      outline: 1px solid color-mix(in srgb, var(--hit) 30%, transparent);
      outline-offset: 1px;
    }
    html[data-theme="dark"] .viewer-text-preview mark {
      background: color-mix(in srgb, var(--hit) 24%, transparent);
      color: var(--strong);
    }
    .viewer-excerpt p { margin: 0; overflow-wrap: anywhere; }
    .viewer-message { color: var(--muted); font-size: .86rem; }
    .citation-strip { display: flex; flex-wrap: wrap; gap: 8px; }
    .citation-button {
      min-height: 30px;
      border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
      border-radius: 999px;
      padding: 4px 9px;
      background: var(--accent-soft);
      color: var(--accent-text);
      font-size: .88rem;
      font-weight: 830;
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }
    .inline-sources {
      display: none;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }
    .inline-sources-head {
      min-height: 38px;
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: .86rem;
      border-bottom: 1px solid var(--border);
    }
    .inline-sources-head strong { color: var(--strong); font-size: .94rem; }
    .inline-source-rail {
      padding: 10px 12px;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      scrollbar-width: thin;
    }
    .results { flex: 1 1 auto; min-height: 0; padding: 16px; display: grid; align-content: start; gap: 13px; }
    .results.is-compact { padding-top: 0; }
    .results-details {
      border-top: 1px solid var(--border);
      background: var(--surface);
    }
    .results-details summary {
      min-height: 44px;
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--strong);
      font-weight: 850;
      cursor: pointer;
    }
    .results-details summary::after {
      content: "anzeigen";
      color: var(--muted);
      font-size: .84rem;
      font-weight: 760;
    }
    .results-details[open] summary::after { content: "ausblenden"; }
    .results-grid { padding: 0 16px 16px; display: grid; gap: 13px; }
    .result-card {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      padding: 15px;
      display: grid;
      gap: 11px;
      scroll-margin-top: 96px;
    }
    .result-card.is-active { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 20%, transparent); }
    .result-top { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .result-title { margin: 0; color: var(--strong); font-size: 1.04rem; line-height: 1.25; overflow-wrap: anywhere; }
    .meta { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; color: var(--muted); font-size: .86rem; }
    .pill { display: inline-flex; align-items: center; min-height: 25px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-3); color: var(--muted); font-size: .81rem; font-weight: 790; }
    .pill.source { background: var(--accent-soft); color: var(--accent-text); border-color: color-mix(in srgb, var(--accent) 42%, var(--border)); }
    .snippet { margin: 0; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
    .snippet mark { background: color-mix(in srgb, var(--hit) 24%, transparent); color: inherit; padding: 0 2px; border-radius: 3px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
    html[data-theme="dark"] .snippet mark { background: color-mix(in srgb, var(--hit) 18%, transparent); color: var(--strong); }
    .path { color: var(--muted); font-size: .88rem; overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .secondary[aria-disabled="true"] { opacity: .56; cursor: not-allowed; }
    .secondary svg, .primary svg, .source-chip svg { width: 16px; height: 16px; flex: 0 0 auto; }
    .empty { padding: 32px 20px; color: var(--muted); text-align: center; }
    .source-rail { padding: 10px; display: grid; gap: 8px; overflow: auto; }
    .source-card {
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: var(--surface);
      color: var(--text);
      display: grid;
      gap: 4px;
    }
    .source-card:hover, .source-card.is-active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface)); }
    .source-card:focus-visible { outline: none; box-shadow: var(--focus); }
    .source-card strong { color: var(--strong); overflow-wrap: anywhere; }
    .source-card span { color: var(--muted); font-size: .84rem; overflow-wrap: anywhere; }
    .source-card p {
      margin: 2px 0 0;
      color: var(--text);
      font-size: .86rem;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow-wrap: anywhere;
    }
    .source-card-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
    .source-card-action {
      min-height: 28px;
      border: 1px solid var(--border);
      border-radius: 7px;
      padding: 0 8px;
      background: var(--surface-2);
      color: var(--text);
      font-size: .78rem;
      font-weight: 780;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
    }
    .source-card-action:hover { border-color: var(--accent); color: var(--accent-text); }
    .inline-source-card {
      flex: 0 0 min(280px, 72vw);
      min-height: 78px;
    }
    .hover-card {
      position: fixed;
      z-index: 30;
      width: min(360px, calc(100vw - 24px));
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: 0 22px 70px rgba(15, 23, 42, .22);
      padding: 13px;
      display: none;
      gap: 8px;
      pointer-events: none;
    }
    .hover-card[aria-hidden="false"] { display: grid; }
    .hover-card strong { color: var(--strong); overflow-wrap: anywhere; }
    .hover-card span { color: var(--muted); font-size: .84rem; }
    .hover-card p { margin: 0; overflow-wrap: anywhere; }
    .toast {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 40;
      max-width: min(420px, calc(100vw - 32px));
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 11px 13px;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 18px 50px rgba(15, 23, 42, .22);
      font-weight: 760;
    }
    .toast.success { border-color: color-mix(in srgb, var(--accent) 42%, var(--border)); background: var(--accent-soft); color: var(--accent-text); }
    .toast.error { border-color: color-mix(in srgb, var(--danger) 42%, var(--border)); background: var(--danger-soft); color: var(--danger); }
    @media (max-width: 1280px) {
      main { grid-template-columns: minmax(250px, 300px) minmax(0, 1fr); }
      .sources-panel { display: none; }
      .inline-sources { display: block; }
      .viewer { grid-template-rows: auto clamp(150px, 20vh, 220px) auto; }
    }
    @media (max-width: 820px) {
      header { padding: 12px 16px; align-items: flex-start; }
      main { grid-template-columns: 1fr; padding: 16px; }
      .library-panel, .sources-panel { position: static; max-height: none; }
      .query-form { grid-template-columns: 1fr; }
      .primary { width: 100%; }
      .viewer { grid-template-rows: auto clamp(140px, 24vh, 220px) auto; }
    }
    @media (max-width: 600px) {
      header { display: grid; }
      .header-actions, .theme-toggle { width: 100%; }
      .toolbar { display: grid; }
      .segments { width: 100%; }
      .viewer-head { display: grid; }
      .viewer-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .viewer-actions .secondary { width: auto; min-height: 34px; padding: 0 7px; }
      .panel-toggle { display: inline-flex; }
      .library-panel { grid-template-rows: auto; }
      .library-panel.is-collapsed .profile-search,
      .library-panel.is-collapsed .profile-actions,
      .library-panel.is-collapsed .profile-list { display: none; }
      .library-panel.is-collapsed .panel-head { border-bottom: 0; }
      .viewer-excerpt { max-height: 136px; }
      .viewer-excerpt-head { align-items: start; }
      .viewer-passage-actions { justify-content: start; }
      .result-top { display: grid; }
      .actions .secondary { width: 100%; }
      .source-rail { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="m21 21-4.3-4.3"></path>
            <circle cx="11" cy="11" r="7"></circle>
            <path d="m8.4 11.2 1.7 1.7 3.8-4"></path>
          </svg>
        </div>
        <div>
          <h1>Wissenssuche</h1>
          <div class="user-line" id="userLine">Bereit</div>
        </div>
      </div>
      <div class="header-actions">
        <div class="theme-toggle" role="group" aria-label="Darstellung">
          <button class="theme-option" type="button" data-theme-choice="light" aria-pressed="true">Hell</button>
          <button class="theme-option" type="button" data-theme-choice="dark" aria-pressed="false">Dunkel</button>
        </div>
      </div>
    </header>
    <main>
      <aside class="panel library-panel" aria-label="Bibliotheken">
        <div class="panel-head">
          <div class="head-line">
            <div>
              <h2>Bibliotheken</h2>
              <p id="profileSummary" class="subtle">Profile werden geladen …</p>
            </div>
            <div class="head-actions">
              <button class="panel-toggle" type="button" id="libraryToggle" aria-expanded="true" aria-controls="profileList">Einklappen</button>
              <span class="count-pill" id="selectionCount">0/0</span>
            </div>
          </div>
          <input id="profileFilter" class="profile-search" type="search" autocomplete="off" placeholder="Bibliothek suchen" aria-label="Bibliothek suchen">
          <div class="profile-actions" aria-label="Bibliotheksauswahl">
            <button class="mini-button" type="button" id="selectAllProfiles">Alle</button>
            <button class="mini-button" type="button" id="clearProfiles">Keine</button>
          </div>
        </div>
        <div class="profile-list" id="profileList"></div>
      </aside>
      <section class="panel search-panel" aria-label="Suche">
        <section class="viewer" id="documentViewer" aria-label="Dokumentviewer">
          <div class="viewer-head">
            <div class="viewer-title">
              <strong id="viewerTitle">Kein Dokument ausgewählt</strong>
              <span id="viewerMeta">Wähle rechts eine Quelle aus oder starte eine Suche.</span>
            </div>
            <div class="viewer-actions" id="viewerActions"></div>
          </div>
          <div id="viewerEmpty" class="viewer-empty">Nach der Suche wird hier die beste Quelle im Dokumentviewer geladen.</div>
          <iframe id="viewerFrame" class="viewer-frame" title="Dokumentviewer" hidden></iframe>
          <div id="viewerPdfScroll" class="viewer-pdf-scroll" hidden>
            <img id="viewerPdfPage" class="viewer-pdf-page" alt="PDF-Seitenvorschau">
          </div>
          <div id="viewerTextPreview" class="viewer-text-preview" role="document" aria-label="Textvorschau" hidden></div>
          <div class="viewer-excerpt" id="viewerExcerpt">
            <span class="viewer-message">Trefferpassage und Suchhilfe erscheinen hier.</span>
          </div>
        </section>
        <div id="state" class="state" aria-live="polite">Wähle Bibliotheken aus und starte eine Suche.</div>
        <div id="answer" class="answer" hidden></div>
        <section class="inline-sources" id="inlineSources" aria-label="Quellen im Arbeitsbereich" hidden>
          <div class="inline-sources-head">
            <strong>Quellen</strong>
            <span id="inlineSourceSummary">Noch keine Treffer.</span>
          </div>
          <div class="inline-source-rail" id="inlineSourceRail"></div>
        </section>
        <div id="results" class="results"></div>
        <div class="query-area composer" id="composer">
          <form class="query-form" id="queryForm">
            <textarea class="query-input" id="question" name="question" rows="2" placeholder="Was möchtest du in deinen Bibliotheken wissen?" aria-label="Suchfrage"></textarea>
            <button class="primary" id="submitSearch" type="submit"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.5 18a7.5 7.5 0 1 1 5.3-12.8A7.5 7.5 0 0 1 10.5 18Zm6-1.5 4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Antwort generieren</button>
          </form>
          <div class="toolbar">
            <div class="segments" role="group" aria-label="Suchmodus">
              <button class="segment" type="button" data-mode="retrieval" aria-pressed="false">Dokumente finden</button>
              <button class="segment" type="button" data-mode="chat" aria-pressed="true">Antwort mit Quellen</button>
            </div>
            <label class="topk">Treffer <input id="topK" type="number" min="1" max="20" value="8"></label>
          </div>
        </div>
      </section>
      <aside class="panel sources-panel" aria-label="Quellen">
        <div class="panel-head">
          <div class="head-line">
            <div>
              <h2>Quellen</h2>
              <p id="sourceSummary" class="subtle">Noch keine Treffer.</p>
            </div>
            <span class="count-pill" id="sourceCount">0</span>
          </div>
        </div>
        <div class="source-rail" id="sourceRail">
          <div class="empty">Nach einer Suche erscheinen hier die wichtigsten Quellen mit Vorschau.</div>
        </div>
      </aside>
    </main>
  </div>
  <div class="hover-card" id="sourceHover" role="tooltip" aria-hidden="true"></div>
  <div class="toast" id="toast" role="status" aria-live="polite" hidden></div>
  <script>
    const stateEl = document.getElementById('state');
    const resultsEl = document.getElementById('results');
    const answerEl = document.getElementById('answer');
    const profileListEl = document.getElementById('profileList');
    const libraryPanelEl = document.querySelector('.library-panel');
    const libraryToggleEl = document.getElementById('libraryToggle');
    const profileSummaryEl = document.getElementById('profileSummary');
    const selectionCountEl = document.getElementById('selectionCount');
    const userLineEl = document.getElementById('userLine');
    const topKEl = document.getElementById('topK');
    const questionEl = document.getElementById('question');
    const submitButtonEl = document.getElementById('submitSearch');
    const sourceRailEl = document.getElementById('sourceRail');
    const inlineSourcesEl = document.getElementById('inlineSources');
    const inlineSourceRailEl = document.getElementById('inlineSourceRail');
    const inlineSourceSummaryEl = document.getElementById('inlineSourceSummary');
    const sourceSummaryEl = document.getElementById('sourceSummary');
    const sourceCountEl = document.getElementById('sourceCount');
    const hoverEl = document.getElementById('sourceHover');
    const viewerTitleEl = document.getElementById('viewerTitle');
    const viewerMetaEl = document.getElementById('viewerMeta');
    const viewerActionsEl = document.getElementById('viewerActions');
    const viewerFrameEl = document.getElementById('viewerFrame');
    const viewerPdfScrollEl = document.getElementById('viewerPdfScroll');
    const viewerPdfPageEl = document.getElementById('viewerPdfPage');
    const viewerTextPreviewEl = document.getElementById('viewerTextPreview');
    const viewerEmptyEl = document.getElementById('viewerEmpty');
    const viewerExcerptEl = document.getElementById('viewerExcerpt');
    const toastEl = document.getElementById('toast');
    let profiles = [];
    let mode = 'chat';
    let latestSources = [];
    let toastTimer = null;
    let viewerRequestId = 0;
    let isLoading = false;
    let activeTextMarkEl = null;
    let activeViewerObjectUrl = null;

    function setState(text, kind = '') {
      stateEl.textContent = text;
      stateEl.className = 'state' + (kind ? ` ${kind}` : '');
      stateEl.hidden = false;
    }

    function showToast(text, kind = 'success') {
      if (toastTimer) window.clearTimeout(toastTimer);
      toastEl.textContent = text;
      toastEl.className = 'toast' + (kind ? ` ${kind}` : '');
      toastEl.hidden = false;
      toastTimer = window.setTimeout(() => {
        toastEl.hidden = true;
      }, 3600);
    }

    function selectedProfileIds() {
      return [...document.querySelectorAll('[data-profile-id]:checked')].map(item => item.value);
    }

    function updateSubmitState() {
      submitButtonEl.disabled = isLoading || !questionEl.value.trim() || !selectedProfileIds().length;
    }

    function setLoading(loading) {
      isLoading = loading;
      updateSubmitState();
    }

    function updateProfileSelectionState() {
      const selected = selectedProfileIds().length;
      const total = profiles.length;
      selectionCountEl.textContent = `${selected}/${total}`;
      profileSummaryEl.textContent = total
        ? `${total} verfügbare Bibliothek${total === 1 ? '' : 'en'} · ${selected} ausgewählt`
        : '0 Bibliotheken';
      document.getElementById('selectAllProfiles').disabled = !total || selected === total;
      document.getElementById('clearProfiles').disabled = !selected;
      updateSubmitState();
    }

    function setAllProfiles(checked) {
      document.querySelectorAll('[data-profile-id]').forEach(item => {
        if (!item.closest('.profile-row').hidden) item.checked = checked;
      });
      updateProfileSelectionState();
      if (!checked) setState('Keine Bibliothek ausgewählt. Wähle mindestens eine Bibliothek für die Suche.');
    }

    function renderProfiles() {
      profileListEl.innerHTML = '';
      if (!profiles.length) {
        profileListEl.innerHTML = '<div class="empty">Keine freigegebenen Bibliotheken verfügbar.</div>';
        updateProfileSelectionState();
        return;
      }
      for (const profile of profiles) {
        const label = document.createElement('label');
        label.className = 'profile-row';
        label.dataset.profileName = `${profile.display_name || ''} ${profile.repo_id || ''}`.toLowerCase();
        label.innerHTML = `
          <input data-profile-id type="checkbox" value="${escapeAttr(profile.id)}" checked>
          <span>
            <span class="profile-name">${escapeHtml(profile.display_name || profile.repo_id)}</span>
            <span class="profile-kind">${escapeHtml(profile.kind || 'Bibliothek')}</span>
          </span>`;
        label.querySelector('input').addEventListener('change', updateProfileSelectionState);
        profileListEl.appendChild(label);
      }
      updateProfileSelectionState();
      applyProfileFilter();
    }

    function applyProfileFilter() {
      const query = document.getElementById('profileFilter').value.trim().toLowerCase();
      document.querySelectorAll('.profile-row').forEach(row => {
        row.hidden = Boolean(query) && !row.dataset.profileName.includes(query);
      });
    }

    async function loadProfiles() {
      setState('Bibliotheken werden geladen …', 'loading');
      try {
        const response = await fetch('/api/search/profiles', {headers: {'Accept': 'application/json'}});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || data.error || 'Profile konnten nicht geladen werden.');
        profiles = data.profiles || [];
        userLineEl.textContent = data.user_display || 'Angemeldet';
        renderProfiles();
        setState(profiles.length ? 'Wähle Bibliotheken aus und starte eine Suche.' : 'Keine freigegebenen Bibliotheken verfügbar.');
      } catch (error) {
        setState(error.message || 'Profile konnten nicht geladen werden.', 'error');
      }
    }

    async function runSearch(event) {
      event.preventDefault();
      if (isLoading) return;
      answerEl.hidden = true;
      answerEl.innerHTML = '';
      resultsEl.innerHTML = '';
      renderSourceRail([]);
      selectSource(null);
      const question = questionEl.value.trim();
      if (!question) {
        setState('Gib eine Suchfrage ein.', 'error');
        return;
      }
      const profile_ids = selectedProfileIds();
      if (!profile_ids.length) {
        setState('Wähle mindestens eine Bibliothek aus. Ohne Auswahl wird RAGFlow nicht abgefragt.', 'error');
        return;
      }
      const endpoint = mode === 'chat' ? '/api/search/chat' : '/api/search/query';
      setLoading(true);
      setState(
        mode === 'chat'
          ? `Suche in ${profile_ids.length} Bibliothek${profile_ids.length === 1 ? '' : 'en'} … Antwort wird aus Fundstellen generiert …`
          : `Suche läuft in ${profile_ids.length} Bibliothek${profile_ids.length === 1 ? '' : 'en'} …`,
        'loading'
      );
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: JSON.stringify({profile_ids, question, top_k: Number(topKEl.value || 8)})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || data.error || 'Suche fehlgeschlagen.');
        const results = data.results || data.sources || [];
        latestSources = results;
        if (data.answer) renderAnswer(data.answer, results);
        renderResults(results, question);
        renderSourceRail(results);
        if (results.length) selectSource(results[0]);
        const denied = data.diagnostics && data.diagnostics.profiles_denied ? data.diagnostics.profiles_denied : 0;
        const allowed = data.diagnostics && data.diagnostics.profiles_allowed ? data.diagnostics.profiles_allowed : profile_ids.length;
        const resultText = `${results.length} Treffer aus ${allowed} Bibliothek${allowed === 1 ? '' : 'en'}.`;
        const successText = denied ? `${resultText} ${denied} Bibliothek(en) wurden wegen fehlender Berechtigung ausgelassen.` : resultText;
        if (mode === 'chat' && data.answer) {
          stateEl.hidden = true;
          showToast(successText, 'success');
        } else {
          setState(successText, 'success');
        }
      } catch (error) {
        setState(error.message || 'Suche fehlgeschlagen.', 'error');
      } finally {
        setLoading(false);
      }
    }

    function renderAnswer(answer, sources = []) {
      const answerText = typeof answer === 'string' ? answer : (answer.text || '');
      const citations = typeof answer === 'object' && answer.citations ? answer.citations : sources.slice(0, 8).map(source => ({
        label: source.citation_label || source.source_id,
        source_id: source.source_id,
        document_name: source.document_name,
        viewer_url: source.viewer_url,
        viewer_kind: source.viewer_kind,
        preview_url: source.preview_url,
        open_url: source.open_url
      }));
      answerEl.hidden = false;
      answerEl.innerHTML = '';
      const title = document.createElement('h2');
      title.textContent = 'Antwort mit Quellen';
      const text = renderAnswerText(answerText, sources);
      answerEl.append(title, text);
      if (citations.length) {
        const strip = document.createElement('div');
        strip.className = 'citation-strip answer-sources';
        strip.setAttribute('aria-label', 'Zitierte Quellen');
        for (const citation of citations) {
          const label = citation.label || citation.marker || '';
          const citationSourceIds = citation.sourceIds || citation.source_ids || (citation.source_id ? [citation.source_id] : []);
          const source = sources.find(item =>
            citationSourceIds.includes(item.source_id)
            || item.citation_label === label
            || item.source_id === label
          ) || citation;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'citation-button answer-source-link';
          button.textContent = `${label || source.citation_label || source.source_id || 'Quelle'} · ${source.document_name || 'Quelle'}`;
          bindSourceInteractions(button, source);
          button.addEventListener('click', () => selectSource(source));
          strip.appendChild(button);
        }
        answerEl.appendChild(strip);
      }
    }

    function renderAnswerText(answerText, sources) {
      const wrapper = document.createElement('div');
      wrapper.className = 'answer-text';
      const paragraphs = String(answerText || '').split(/\n{2,}/).filter(Boolean);
      for (const paragraphText of paragraphs.length ? paragraphs : ['']) {
        const paragraph = document.createElement('p');
        appendAnswerSegments(paragraph, paragraphText, sources);
        wrapper.appendChild(paragraph);
      }
      return wrapper;
    }

    function appendAnswerSegments(target, text, sources) {
      const markerPattern = /\[(S\d+)\]/g;
      let lastIndex = 0;
      let match;
      while ((match = markerPattern.exec(text)) !== null) {
        if (match.index > lastIndex) {
          target.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
        }
        const source = sourceByLabel(match[1], sources);
        if (source) {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'citation-button answer-citation-marker';
          button.textContent = `[${match[1]}]`;
          button.title = `${match[1]} im Dokumentviewer anzeigen`;
          bindSourceInteractions(button, source);
          button.addEventListener('click', () => selectSource(source));
          target.appendChild(button);
        } else {
          target.appendChild(document.createTextNode(match[0]));
        }
        lastIndex = markerPattern.lastIndex;
      }
      if (lastIndex < text.length) {
        target.appendChild(document.createTextNode(text.slice(lastIndex)));
      }
    }

    function sourceByLabel(label, sources = latestSources) {
      const clean = String(label || '').replace(/^\[|\]$/g, '');
      return sources.find(item => item.source_id === clean || item.citation_label === clean || item.label === clean);
    }

    function renderResults(results, query) {
      resultsEl.innerHTML = '';
      resultsEl.className = 'results' + (mode === 'chat' ? ' is-compact' : '');
      if (!results.length) {
        resultsEl.innerHTML = '<div class="empty">Keine passenden Treffer in den ausgewählten Bibliotheken gefunden.</div>';
        return;
      }
      const target = mode === 'chat'
        ? document.createElement('div')
        : resultsEl;
      for (const item of results) {
        const card = document.createElement('article');
        card.className = 'result-card';
        card.id = `result-${safeDomId(item.source_id || item.rank || Math.random())}`;
        card.dataset.sourceId = item.source_id || '';
        const location = item.locator && item.locator.label ? item.locator.label : (item.page ? `Seite ${item.page}` : '');
        card.innerHTML = `
          <div class="result-top">
            <div>
              <h3 class="result-title">${escapeHtml(item.document_name || 'Dokument')}</h3>
              <div class="meta">
                <span class="pill source">${escapeHtml(item.citation_label || item.source_id || 'Quelle')}</span>
                <span class="pill">${escapeHtml(item.dataset_name || 'Bibliothek')}</span>
                ${location ? `<span class="pill">${escapeHtml(location)}</span>` : ''}
              </div>
            </div>
            ${item.score_percent !== null && item.score_percent !== undefined ? `<span class="pill">${escapeHtml(String(item.score_percent))}%</span>` : ''}
          </div>
          <p class="snippet">${highlightSnippet(item.snippet || 'Kein Snippet verfügbar.', query)}</p>
          <div class="path">${escapeHtml(item.source_path || '')}</div>
          <div class="actions">
            <button class="secondary" type="button" data-viewer-source="${escapeAttr(item.source_id || '')}">${iconEye()}Quelle öffnen</button>
            <button class="secondary" type="button" data-copy-source="${escapeAttr(item.source_id || '')}">Passage suchen</button>
            ${item.preview_url ? `<a class="secondary" href="${escapeAttr(item.preview_url)}" target="_blank" rel="noreferrer noopener" title="Vorschau im Evidence-Viewer öffnen">${iconEye()}Vorschau</a>` : '<span class="secondary" aria-disabled="true" title="Keine Vorschau verfügbar.">Vorschau</span>'}
            ${item.open_url ? `<a class="secondary" href="${escapeAttr(item.open_url)}" target="_blank" rel="noreferrer noopener" title="Originallink öffnen">${iconExternal()}${openLabel(item)}</a>` : '<span class="secondary" aria-disabled="true" title="Für diesen Treffer ist kein Originallink vorhanden.">Originallink</span>'}
          </div>`;
        card.querySelector('[data-viewer-source]').addEventListener('click', event => {
          event.stopPropagation();
          selectSource(item);
        });
        card.querySelector('[data-copy-source]').addEventListener('click', event => {
          event.stopPropagation();
          copyPassage(item);
        });
        bindSourceInteractions(card, item);
        target.appendChild(card);
      }
      if (mode === 'chat') {
        target.className = 'results-grid';
        const details = document.createElement('details');
        details.className = 'results-details';
        const summary = document.createElement('summary');
        summary.textContent = `Fundstellen prüfen (${results.length})`;
        details.append(summary, target);
        resultsEl.appendChild(details);
      }
    }

    function renderSourceRail(sources) {
      sourceRailEl.innerHTML = '';
      inlineSourceRailEl.innerHTML = '';
      sourceCountEl.textContent = String(sources.length);
      sourceSummaryEl.textContent = sources.length ? `${sources.length} Quellen aus den erlaubten Bibliotheken.` : 'Noch keine Treffer.';
      inlineSourceSummaryEl.textContent = sources.length ? `${sources.length} Quellen` : 'Noch keine Treffer.';
      inlineSourcesEl.hidden = !sources.length;
      if (!sources.length) {
        sourceRailEl.innerHTML = '<div class="empty">Nach einer Suche erscheinen hier die wichtigsten Quellen mit Vorschau.</div>';
        return;
      }
      for (const source of sources) {
        sourceRailEl.appendChild(sourceCard(source, 'source-card'));
        inlineSourceRailEl.appendChild(sourceCard(source, 'source-card inline-source-card'));
      }
    }

    function sourceCard(source, className) {
      const card = document.createElement('article');
      card.className = className;
      card.dataset.sourceId = source.source_id || '';
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `${source.citation_label || source.source_id || 'Quelle'} anzeigen`);
      const location = source.locator && source.locator.label ? source.locator.label : '';
      card.innerHTML = `
        <strong>${escapeHtml(source.citation_label || source.source_id || 'Quelle')} · ${escapeHtml(source.document_name || 'Dokument')}</strong>
        <span>${escapeHtml(source.dataset_name || 'Bibliothek')}${location ? ` · ${escapeHtml(location)}` : ''}</span>
        <p>${escapeHtml(compact(source.snippet || source.passageTextExact || source.passage_text_exact || '', 150))}</p>
        <div class="source-card-actions">
          <button class="source-card-action" type="button" data-source-action="show">Anzeigen</button>
          <button class="source-card-action" type="button" data-source-action="copy">Kopieren</button>
          ${source.open_url ? `<a class="source-card-action" href="${escapeAttr(source.open_url)}" target="_blank" rel="noreferrer noopener">Original</a>` : ''}
        </div>`;
      const select = () => {
        hideHover();
        selectSource(source);
      };
      bindSourceInteractions(card, source);
      card.addEventListener('click', event => {
        if (event.target.closest('button,a')) return;
        select();
      });
      card.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          select();
        }
      });
      card.querySelector('[data-source-action="show"]').addEventListener('click', select);
      card.querySelector('[data-source-action="copy"]').addEventListener('click', event => {
        event.stopPropagation();
        copyPassage(source);
      });
      return card;
    }

    function bindSourceInteractions(element, source) {
      element.addEventListener('mouseenter', event => showHover(event.currentTarget, source));
      element.addEventListener('focus', event => showHover(event.currentTarget, source));
      element.addEventListener('mouseleave', hideHover);
      element.addEventListener('blur', hideHover);
    }

    function showHover(target, source) {
      const location = source.locator && source.locator.label ? source.locator.label : 'Fundstelle';
      hoverEl.innerHTML = `
        <strong>${escapeHtml(source.citation_label || source.source_id || 'Quelle')} · ${escapeHtml(source.document_name || 'Dokument')}</strong>
        <span>${escapeHtml(source.dataset_name || 'Bibliothek')} · ${escapeHtml(location)}</span>
        <p>${escapeHtml(compact(source.snippet || 'Keine Vorschau verfügbar.', 260))}</p>`;
      const rect = target.getBoundingClientRect();
      hoverEl.setAttribute('aria-hidden', 'false');
      const left = Math.min(window.innerWidth - hoverEl.offsetWidth - 12, Math.max(12, rect.left + 12));
      const top = Math.min(window.innerHeight - hoverEl.offsetHeight - 12, Math.max(12, rect.bottom + 8));
      hoverEl.style.left = `${left}px`;
      hoverEl.style.top = `${top}px`;
    }

    function hideHover() {
      hoverEl.setAttribute('aria-hidden', 'true');
    }

    function revokeViewerObjectUrl() {
      if (activeViewerObjectUrl) {
        URL.revokeObjectURL(activeViewerObjectUrl);
        activeViewerObjectUrl = null;
      }
    }

    function selectSource(source) {
      hideHover();
      viewerRequestId += 1;
      if (!source) {
        activeTextMarkEl = null;
        revokeViewerObjectUrl();
        viewerTitleEl.textContent = 'Kein Dokument ausgewählt';
        viewerMetaEl.textContent = 'Wähle rechts eine Quelle aus oder starte eine Suche.';
        viewerActionsEl.innerHTML = '';
        viewerFrameEl.hidden = true;
        viewerFrameEl.removeAttribute('src');
        viewerPdfScrollEl.hidden = true;
        viewerPdfPageEl.removeAttribute('src');
        viewerTextPreviewEl.hidden = true;
        viewerTextPreviewEl.textContent = '';
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = 'Nach der Suche wird hier die beste Quelle im Dokumentviewer geladen.';
        viewerExcerptEl.classList.remove('is-expanded');
        viewerExcerptEl.innerHTML = '<span class="viewer-message">Trefferpassage und Suchhilfe erscheinen hier.</span>';
        document.querySelectorAll('.result-card,.source-card').forEach(item => item.classList.remove('is-active'));
        return;
      }
      renderViewer(source);
      focusSource(source);
    }

    function renderViewer(source) {
      const location = source.locator && source.locator.label ? source.locator.label : '';
      activeTextMarkEl = null;
      viewerTitleEl.textContent = `${source.citation_label || source.source_id || 'Quelle'} · ${source.document_name || 'Dokument'}`;
      viewerMetaEl.textContent = `${source.dataset_name || 'Bibliothek'}${location ? ` · ${location}` : ''}`;
      const actions = [];
      actions.push('<button class="secondary primary-viewer-action" type="button" id="scrollActivePassage">Zur Passage</button>');
      actions.push('<button class="secondary" type="button" id="copyActivePassage">Passage kopieren</button>');
      if (source.viewer_url && source.viewer_kind === 'download') actions.push(`<a class="secondary" href="${escapeAttr(source.viewer_url)}" target="_blank" rel="noreferrer noopener">Datei herunterladen</a>`);
      if (source.open_url) actions.push(`<a class="secondary" href="${escapeAttr(source.open_url)}" target="_blank" rel="noreferrer noopener">Original öffnen</a>`);
      if (source.preview_url && source.preview_url !== source.viewer_url) actions.push(`<a class="secondary" href="${escapeAttr(source.preview_url)}" target="_blank" rel="noreferrer noopener">Vorschau</a>`);
      viewerActionsEl.innerHTML = actions.join('');
      const scrollButton = document.getElementById('scrollActivePassage');
      if (scrollButton) scrollButton.addEventListener('click', () => scrollToActivePassage(source));
      const copyButton = document.getElementById('copyActivePassage');
      if (copyButton) copyButton.addEventListener('click', () => copyPassage(source));

      const message = source.viewer_kind === 'text'
        ? 'Im Dokument ist nur ein kurzer Trefferanker gelb markiert. Die vollständige Passage bleibt hier kopierbar.'
        : (source.viewer_message || 'Bei nativen Viewern ist die Markierung best-effort; die vollständige Passage bleibt hier kopierbar.');
      const snippet = compact(sourcePassage(source) || '', 420);
      viewerExcerptEl.classList.remove('is-expanded');
      viewerExcerptEl.innerHTML = `
        <div class="viewer-excerpt-head">
          <span class="viewer-kicker">Trefferpassage</span>
          <span class="viewer-passage-actions">
            <button class="passage-action" type="button" id="copyViewerPassage">Passage kopieren</button>
            <button class="passage-action" type="button" id="toggleViewerPassage" hidden>mehr anzeigen</button>
          </span>
        </div>
        <p class="viewer-passage-text">${snippet ? escapeHtml(snippet) : 'Kein Textauszug verfügbar.'}</p>
        <span class="viewer-focus-note">${escapeHtml(message)}</span>`;
      const copyPassageButton = document.getElementById('copyViewerPassage');
      if (copyPassageButton) copyPassageButton.addEventListener('click', () => copyPassage(source));
      const togglePassageButton = document.getElementById('toggleViewerPassage');
      if (togglePassageButton && snippet.length > 260) {
        togglePassageButton.hidden = false;
        togglePassageButton.addEventListener('click', () => {
          const expanded = viewerExcerptEl.classList.toggle('is-expanded');
          togglePassageButton.textContent = expanded ? 'weniger anzeigen' : 'mehr anzeigen';
        });
      }

      const inlineTarget = source.viewer_url && source.viewer_url.startsWith('/') && source.viewer_kind !== 'download';
      viewerFrameEl.hidden = true;
      viewerFrameEl.removeAttribute('src');
      revokeViewerObjectUrl();
      viewerPdfScrollEl.hidden = true;
      viewerPdfPageEl.removeAttribute('src');
      viewerTextPreviewEl.hidden = true;
      viewerTextPreviewEl.textContent = '';
      if (inlineTarget && source.viewer_kind === 'text') {
        const requestId = viewerRequestId;
        viewerEmptyEl.hidden = true;
        viewerTextPreviewEl.hidden = false;
        viewerTextPreviewEl.textContent = 'Text wird geladen …';
        loadTextPreview(source.viewer_url, requestId, source);
      } else if (inlineTarget && source.viewer_kind === 'pdf') {
        const requestId = viewerRequestId;
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = 'PDF-Seite wird im Dokumentviewer gerendert …';
        loadPdfPagePreview(source.viewer_url, requestId, source);
      } else if (inlineTarget && source.viewer_kind === 'image') {
        const requestId = viewerRequestId;
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = 'Bild wird im Dokumentviewer geladen …';
        loadBinaryPreview(source.viewer_url, requestId, source);
      } else if (inlineTarget) {
        viewerFrameEl.src = source.viewer_url;
        viewerFrameEl.hidden = false;
        viewerEmptyEl.hidden = true;
      } else {
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = source.viewer_url
          ? 'Diese Quelle ist für den Inline-Viewer nicht geeignet. Nutze „Original öffnen“ oder den Auszug.'
          : 'Für diese Quelle ist kein sicherer Dokumentviewer-Link verfügbar. Nutze Vorschau, Originallink oder den Auszug.';
      }
    }

    function loadPdfPagePreview(url, requestId, source) {
      const target = splitUrlFragment(url);
      const page = pdfPageFromFragment(target.fragment) || source.page || 1;
      const imageUrl = pdfPageImageUrl(target.url, page);
      viewerPdfPageEl.onload = () => {
        if (requestId !== viewerRequestId) return;
        viewerPdfScrollEl.hidden = false;
        viewerEmptyEl.hidden = true;
        viewerPdfScrollEl.scrollTo({top: 0, left: 0});
      };
      viewerPdfPageEl.onerror = () => {
        if (requestId !== viewerRequestId) return;
        viewerPdfScrollEl.hidden = true;
        viewerPdfPageEl.removeAttribute('src');
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = 'PDF-Seitenvorschau konnte nicht geladen werden. Nutze Original öffnen oder den kopierbaren Auszug.';
      };
      viewerPdfPageEl.alt = `${source.document_name || 'PDF'} · Seite ${page}`;
      viewerPdfPageEl.src = imageUrl;
    }

    async function loadBinaryPreview(url, requestId, source) {
      try {
        const target = splitUrlFragment(url);
        const response = await fetch(target.url, {headers: {'Accept': 'image/*, */*'}});
        if (!response.ok) throw new Error('Dokument konnte nicht im Viewer geladen werden.');
        const blob = await response.blob();
        if (requestId !== viewerRequestId) return;
        revokeViewerObjectUrl();
        activeViewerObjectUrl = URL.createObjectURL(blob);
        viewerFrameEl.src = `${activeViewerObjectUrl}${target.fragment}`;
        viewerFrameEl.hidden = false;
        viewerEmptyEl.hidden = true;
      } catch (error) {
        if (requestId !== viewerRequestId) return;
        revokeViewerObjectUrl();
        viewerFrameEl.hidden = true;
        viewerFrameEl.removeAttribute('src');
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = error.message || 'Dokument konnte nicht im Viewer geladen werden. Nutze Original öffnen oder den Auszug.';
      }
    }

    async function loadTextPreview(url, requestId, source) {
      try {
        const target = splitUrlFragment(url);
        const response = await fetch(target.url, {headers: {'Accept': 'text/plain, */*'}});
        if (!response.ok) throw new Error('Text konnte nicht geladen werden.');
        const text = await response.text();
        if (requestId !== viewerRequestId) return;
        renderTextPreview(text, source);
      } catch (error) {
        if (requestId !== viewerRequestId) return;
        viewerTextPreviewEl.hidden = true;
        viewerTextPreviewEl.replaceChildren();
        viewerEmptyEl.hidden = false;
        viewerEmptyEl.textContent = error.message || 'Text konnte nicht geladen werden. Nutze Original öffnen oder den Auszug.';
      }
    }

    function splitUrlFragment(url) {
      const value = String(url || '');
      const index = value.indexOf('#');
      if (index < 0) return {url: value, fragment: ''};
      return {url: value.slice(0, index), fragment: value.slice(index)};
    }

    function pdfPageFromFragment(fragment) {
      const clean = String(fragment || '').replace(/^#/, '');
      if (!clean) return 1;
      const params = new URLSearchParams(clean);
      const value = params.get('page') || clean.match(/page=([^&]+)/)?.[1];
      const page = Number.parseInt(value || '1', 10);
      return Number.isFinite(page) && page > 0 ? page : 1;
    }

    function pdfPageImageUrl(url, page) {
      const target = new URL(url, window.location.origin);
      target.pathname = '/api/search/source/document/page-image';
      target.searchParams.set('page', String(page || 1));
      target.hash = '';
      return `${target.pathname}${target.search}`;
    }

    function renderTextPreview(fullText, source) {
      const passage = sourcePassage(source);
      const passageRange = findPassageRange(fullText, passage);
      let range = findFocusedPassageRange(fullText, passage, passageRange, questionEl.value);
      let visibleText = fullText;
      let offset = 0;
      let prefix = '';
      let suffix = '';
      if (fullText.length > 30000) {
        if (range) {
          const start = Math.max(0, range.start - 9000);
          const end = Math.min(fullText.length, range.end + 18000);
          visibleText = fullText.slice(start, end);
          offset = start;
          range = {start: range.start - offset, end: range.end - offset};
          prefix = start > 0 ? '…\n' : '';
          suffix = end < fullText.length ? '\n…' : '';
        } else {
          visibleText = fullText.slice(0, 30000);
          suffix = '\n…';
        }
      }
      viewerTextPreviewEl.replaceChildren();
      if (prefix) viewerTextPreviewEl.appendChild(document.createTextNode(prefix));
      if (range && range.start >= 0 && range.end > range.start) {
        viewerTextPreviewEl.appendChild(document.createTextNode(visibleText.slice(0, range.start)));
        const mark = document.createElement('mark');
        mark.textContent = visibleText.slice(range.start, range.end);
        viewerTextPreviewEl.appendChild(mark);
        viewerTextPreviewEl.appendChild(document.createTextNode(visibleText.slice(range.end)));
        activeTextMarkEl = mark;
        window.requestAnimationFrame(() => mark.scrollIntoView({block: 'center'}));
      } else {
        viewerTextPreviewEl.appendChild(document.createTextNode(visibleText));
        activeTextMarkEl = null;
        if (passage) {
          showToast('Die Passage konnte im Text nicht automatisch markiert werden. Der Auszug bleibt kopierbar.', 'error');
        }
      }
      if (suffix) viewerTextPreviewEl.appendChild(document.createTextNode(suffix));
    }

    function findFocusedPassageRange(text, passage, passageRange, query) {
      if (!passageRange) return null;
      const passageText = text.slice(passageRange.start, passageRange.end);
      const queryTerms = focusTerms(query);
      for (const term of queryTerms) {
        const termRange = findTermRange(passageText, term);
        if (termRange) {
          return {
            start: passageRange.start + termRange.start,
            end: passageRange.start + termRange.end,
          };
        }
      }
      const compactRange = bestPassageAnchorRange(passageText);
      if (compactRange) {
        return {
          start: passageRange.start + compactRange.start,
          end: passageRange.start + compactRange.end,
        };
      }
      return clampRangeToReadableLength(text, passageRange, 160);
    }

    function findPassageRange(text, passage) {
      const cleanPassage = String(passage || '').trim();
      if (!cleanPassage) return null;
      const exactIndex = text.indexOf(cleanPassage);
      if (exactIndex >= 0) return {start: exactIndex, end: exactIndex + cleanPassage.length};
      const normalized = findNormalizedRange(text, cleanPassage);
      if (normalized) return normalized;
      const shortened = cleanPassage.slice(0, 240).trim();
      if (shortened && shortened !== cleanPassage) {
        const shortExactIndex = text.indexOf(shortened);
        if (shortExactIndex >= 0) return {start: shortExactIndex, end: shortExactIndex + shortened.length};
        return findNormalizedRange(text, shortened);
      }
      return null;
    }

    function findNormalizedRange(text, passage) {
      const normalizedText = normalizeWithMap(text);
      const normalizedPassage = normalizeForMatch(passage);
      if (!normalizedPassage) return null;
      const index = normalizedText.text.indexOf(normalizedPassage);
      if (index < 0) return null;
      const last = index + normalizedPassage.length - 1;
      const start = normalizedText.indexes[index];
      const end = (normalizedText.indexes[last] ?? start) + 1;
      return {start, end};
    }

    function focusTerms(query) {
      const stopWords = new Set([
        'aber', 'alle', 'auch', 'aus', 'bei', 'das', 'den', 'der', 'die', 'ein', 'eine',
        'einen', 'einer', 'eines', 'für', 'gibt', 'haben', 'ich', 'ist', 'mit', 'nach',
        'oder', 'sich', 'sind', 'und', 'was', 'welche', 'welchen', 'welcher', 'wer', 'wie',
        'wird', 'wo', 'zu', 'zum', 'zur',
      ]);
      return [...new Set(String(query || '')
        .toLowerCase()
        .split(/[^\p{L}\p{N}_-]+/u)
        .map(term => term.trim())
        .filter(term => term.length >= 4 && !stopWords.has(term)))]
        .sort((left, right) => right.length - left.length)
        .slice(0, 6);
    }

    function findTermRange(text, term) {
      const lowerText = String(text || '').toLowerCase();
      const lowerTerm = String(term || '').toLowerCase();
      if (!lowerTerm) return null;
      const index = lowerText.indexOf(lowerTerm);
      if (index < 0) return null;
      return expandToReadableToken(text, index, index + lowerTerm.length);
    }

    function expandToReadableToken(text, start, end) {
      let nextStart = start;
      let nextEnd = end;
      while (nextStart > 0 && /[\p{L}\p{N}_-]/u.test(text[nextStart - 1])) nextStart -= 1;
      while (nextEnd < text.length && /[\p{L}\p{N}_-]/u.test(text[nextEnd])) nextEnd += 1;
      if (nextEnd - nextStart > 96) return {start, end};
      return {start: nextStart, end: nextEnd};
    }

    function bestPassageAnchorRange(text) {
      const value = String(text || '');
      const candidates = [];
      let offset = 0;
      for (const line of value.split('\n')) {
        const trimmed = line.trim();
        const localStart = line.search(/\S/);
        if (trimmed.length >= 18 && localStart >= 0 && !isLowValuePassageLine(trimmed)) {
          candidates.push({
            start: offset + localStart,
            text: trimmed,
            score: passageLineScore(trimmed),
          });
        }
        offset += line.length + 1;
      }
      const best = candidates.sort((left, right) => right.score - left.score || left.start - right.start)[0];
      if (!best) return clampRangeToReadableLength(value, {start: 0, end: Math.min(value.length, 96)}, 96);
      return clampRangeToReadableLength(value, {start: best.start, end: best.start + best.text.length}, 96);
    }

    function isLowValuePassageLine(line) {
      const value = String(line || '').trim();
      if (!value) return true;
      if (value.startsWith('#')) return true;
      if (/^[A-Z0-9_-]{18,}$/.test(value.replace(/\s+/g, ''))) return true;
      return false;
    }

    function passageLineScore(line) {
      const value = String(line || '');
      let score = 0;
      if (/GS_[A-Za-z0-9_-]+/.test(value)) score += 6;
      if (/(ACL|Freigabe|Zugriff|Sichtbarkeit|dürfen|darf|Gruppe|Rolle)/i.test(value)) score += 5;
      if (/(Handbuch|Dokument|Betrieb|Sicherheit|Nutzer|Admin)/i.test(value)) score += 3;
      if (/[.!?]$/.test(value.trim())) score += 1;
      return score;
    }

    function clampRangeToReadableLength(text, range, limit) {
      if (!range || range.end <= range.start) return null;
      if (range.end - range.start <= limit) return range;
      let start = range.start;
      while (start < range.end && /\s/.test(text[start])) start += 1;
      const hardEnd = Math.min(range.end, start + limit);
      const segment = text.slice(start, hardEnd);
      const punctuation = segment.search(/[.!?]\s/);
      if (punctuation >= 32) return {start, end: start + punctuation + 1};
      const lastSpace = segment.lastIndexOf(' ');
      const end = lastSpace >= 48 ? start + lastSpace : hardEnd;
      return {start, end};
    }

    function normalizeWithMap(value) {
      const chars = [];
      const indexes = [];
      let inSpace = false;
      const text = String(value || '');
      for (let index = 0; index < text.length; index += 1) {
        const char = text[index];
        if (/\s/.test(char)) {
          if (chars.length && !inSpace) {
            chars.push(' ');
            indexes.push(index);
            inSpace = true;
          }
        } else {
          chars.push(char.toLowerCase());
          indexes.push(index);
          inSpace = false;
        }
      }
      if (chars[chars.length - 1] === ' ') {
        chars.pop();
        indexes.pop();
      }
      return {text: chars.join(''), indexes};
    }

    function normalizeForMatch(value) {
      return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function focusSource(source) {
      document.querySelectorAll('.result-card,.source-card').forEach(item => item.classList.remove('is-active'));
      const selector = `[data-source-id="${cssEscape(source.source_id || '')}"]`;
      document.querySelectorAll(selector).forEach(item => item.classList.add('is-active'));
    }

    function openPreview(source) {
      const target = source.preview_url || source.open_url;
      if (target) window.open(target, '_blank', 'noopener,noreferrer');
    }

    function sourcePassage(source) {
      return String(
        source.passageTextExact
        || source.passage_text_exact
        || source.text
        || source.snippet
        || ''
      ).trim();
    }

    function scrollToActivePassage(source) {
      if (activeTextMarkEl) {
        activeTextMarkEl.scrollIntoView({block: 'center'});
        activeTextMarkEl.focus?.();
        return;
      }
      viewerExcerptEl.scrollIntoView({block: 'center'});
      if (source && source.viewer_kind !== 'text') {
        showToast('Bei nativen Viewern bleibt der Treffer als kopierbarer Auszug sichtbar.', 'success');
      }
    }

    async function copyPassage(source) {
      const passage = sourcePassage(source) || source.document_name || '';
      if (!passage) {
        showToast('Für diese Quelle gibt es keinen kopierbaren Passage-Text.', 'error');
        return;
      }
      try {
        await navigator.clipboard.writeText(passage);
        showToast('Passage kopiert. Nutze Strg+F im Dokumentviewer und füge den Text ein.', 'success');
      } catch (_error) {
        showToast('Passage konnte nicht automatisch kopiert werden. Markiere den gelben Auszug manuell und nutze Strg+F.', 'error');
      }
    }

    function openLabel(item) {
      if (item.open_url_kind === 'page_anchor') return 'Seite öffnen';
      if (item.open_url_kind === 'text_fragment') return 'Passage suchen';
      return 'Quelle öffnen';
    }

    function highlightSnippet(snippet, query) {
      let html = escapeHtml(snippet || '');
      const terms = snippetHighlightTerms(query);
      for (const term of terms) {
        const pattern = new RegExp(`(${escapeRegExp(escapeHtml(term))})`, 'ig');
        html = html.replace(pattern, '<mark>$1</mark>');
      }
      return html;
    }

    function snippetHighlightTerms(query) {
      const broadTerms = new Set(['test', 'handbuch', 'dokument', 'quelle', 'suche']);
      return focusTerms(query)
        .filter(term => term.length >= 5 && !broadTerms.has(term))
        .slice(0, 4);
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }

    function escapeAttr(value) { return escapeHtml(value).replace(/`/g, '&#96;'); }
    function escapeRegExp(value) { return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    function compact(value, limit) {
      const clean = String(value || '').replace(/\s+/g, ' ').trim();
      return clean.length <= limit ? clean : clean.slice(0, Math.max(0, limit - 3)).trimEnd() + '...';
    }
    function safeDomId(value) { return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_') || 'source'; }
    function cssEscape(value) {
      if (window.CSS && CSS.escape) return CSS.escape(value);
      return String(value).replace(/["\\]/g, '\\$&');
    }
    function iconEye() { return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>'; }
    function iconExternal() { return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M13 11l7-7M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'; }

    function setLibraryCollapsed(collapsed) {
      libraryPanelEl.classList.toggle('is-collapsed', collapsed);
      libraryToggleEl.setAttribute('aria-expanded', String(!collapsed));
      libraryToggleEl.textContent = collapsed ? 'Ausklappen' : 'Einklappen';
    }

    function syncLibraryCollapse() {
      const isMobile = window.matchMedia('(max-width: 600px)').matches;
      if (isMobile && !libraryPanelEl.dataset.userCollapse) {
        setLibraryCollapsed(true);
      } else if (!isMobile) {
        libraryPanelEl.dataset.userCollapse = '';
        setLibraryCollapsed(false);
      }
    }

    function applyTheme(theme) {
      const next = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('connector-search-theme', next);
      document.querySelectorAll('[data-theme-choice]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.themeChoice === next));
      });
    }

    function initialTheme() {
      const stored = localStorage.getItem('connector-search-theme');
      if (stored === 'light' || stored === 'dark') return stored;
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
    });
    document.querySelectorAll('.segment').forEach(button => {
      button.addEventListener('click', () => {
        mode = button.dataset.mode;
        document.querySelectorAll('.segment').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
        submitButtonEl.lastChild.textContent = mode === 'chat' ? 'Antwort generieren' : 'Suchen';
      });
    });
    document.getElementById('selectAllProfiles').addEventListener('click', () => setAllProfiles(true));
    document.getElementById('clearProfiles').addEventListener('click', () => setAllProfiles(false));
    document.getElementById('profileFilter').addEventListener('input', applyProfileFilter);
    questionEl.addEventListener('input', updateSubmitState);
    questionEl.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.getElementById('queryForm').requestSubmit();
      }
    });
    document.getElementById('queryForm').addEventListener('submit', runSearch);
    libraryToggleEl.addEventListener('click', () => {
      libraryPanelEl.dataset.userCollapse = 'true';
      setLibraryCollapsed(!libraryPanelEl.classList.contains('is-collapsed'));
    });
    window.addEventListener('resize', syncLibraryCollapse);
    applyTheme(initialTheme());
    syncLibraryCollapse();
    updateSubmitState();
    loadProfiles();
  </script>
</body>
</html>"""
