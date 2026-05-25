from __future__ import annotations

# ruff: noqa: E501

DASHBOARD_HTML = r"""<!doctype html>
<html lang="de" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Seafile RAGFlow Connector Dashboard</title>
  <script>
    const dashboardTheme = localStorage.getItem('connector-dashboard-theme') || 'dark';
    document.documentElement.dataset.theme = dashboardTheme;
  </script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #090d14;
      --bg-2: #111827;
      --surface: #141b29;
      --surface-2: #192235;
      --surface-3: #202b40;
      --surface-glass: rgba(20, 27, 41, 0.82);
      --text: #f4f7fb;
      --muted: #96a3b7;
      --soft: #cbd5e1;
      --border: rgba(148, 163, 184, 0.24);
      --border-strong: rgba(148, 163, 184, 0.42);
      --accent: #2dd4bf;
      --accent-2: #60a5fa;
      --accent-3: #f59e0b;
      --accent-soft: rgba(45, 212, 191, 0.16);
      --ok: #34d399;
      --warn: #fbbf24;
      --bad: #fb7185;
      --info: #38bdf8;
      --unknown: #94a3b8;
      --shadow: 0 24px 70px rgba(0, 0, 0, 0.32);
      --shadow-soft: 0 14px 38px rgba(0, 0, 0, 0.22);
      --radius: 8px;
      --focus: 0 0 0 3px rgba(45, 212, 191, 0.36);
      --primary-bg: linear-gradient(135deg, var(--accent), var(--accent-2));
      --primary-text: #041116;
      --primary-border: transparent;
      --motion-fast: 160ms;
      --motion-slow: 1100ms;
    }
    :root[data-theme="light"] {
      color-scheme: light;
      --bg: #eef2f7;
      --bg-2: #f8fafc;
      --surface: #ffffff;
      --surface-2: #f5f8fc;
      --surface-3: #eaf0f8;
      --surface-glass: rgba(255, 255, 255, 0.86);
      --text: #142033;
      --muted: #5b677a;
      --soft: #334155;
      --border: rgba(92, 108, 130, 0.22);
      --border-strong: rgba(92, 108, 130, 0.38);
      --accent: #0f766e;
      --accent-2: #2563eb;
      --accent-3: #b45309;
      --accent-soft: rgba(15, 118, 110, 0.12);
      --ok: #047857;
      --warn: #b45309;
      --bad: #be123c;
      --info: #0369a1;
      --unknown: #64748b;
      --shadow: 0 20px 60px rgba(15, 23, 42, 0.12);
      --shadow-soft: 0 12px 30px rgba(15, 23, 42, 0.10);
      --focus: 0 0 0 3px rgba(15, 118, 110, 0.30);
      --primary-bg: linear-gradient(135deg, #ccfbf1, #dbeafe);
      --primary-text: #0f172a;
      --primary-border: rgba(15, 118, 110, 0.28);
    }
    * { box-sizing: border-box; }
    html { min-height: 100%; }
    body {
      margin: 0;
      min-height: 100%;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--bg-2) 88%, #000 12%), var(--bg) 38%),
        linear-gradient(120deg, color-mix(in srgb, var(--accent) 10%, transparent), transparent 32%, color-mix(in srgb, var(--accent-2) 10%, transparent) 72%, transparent),
        repeating-linear-gradient(90deg, transparent 0 38px, rgba(148, 163, 184, 0.05) 38px 39px);
      color: var(--text);
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
      letter-spacing: 0;
    }
    @keyframes surfaceIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes gridDrift {
      from { transform: translateX(0); }
      to { transform: translateX(38px); }
    }
    @keyframes railRise {
      from { transform: scaleY(0.25); opacity: 0.35; }
      to { transform: scaleY(1); opacity: 0.86; }
    }
    @keyframes softPulse {
      0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 0%, transparent); }
      50% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent) 18%, transparent); }
    }
    @keyframes refreshProgress {
      from { transform: scaleX(0); }
      to { transform: scaleX(1); }
    }
    @keyframes sheen {
      from { transform: translateX(-120%); }
      to { transform: translateX(140%); }
    }
    button, input, select, a.action {
      font: inherit;
    }
    button, a.action {
      align-items: center;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      cursor: pointer;
      display: inline-flex;
      gap: 8px;
      justify-content: center;
      min-height: 40px;
      padding: 8px 12px;
      text-decoration: none;
      transition: border-color var(--motion-fast) ease, background var(--motion-fast) ease, color var(--motion-fast) ease, transform var(--motion-fast) ease;
      user-select: none;
    }
    button:hover, a.action:hover { transform: translateY(-1px); border-color: var(--border-strong); }
    button:focus-visible, input:focus-visible, select:focus-visible, a.action:focus-visible {
      outline: 0;
      box-shadow: var(--focus);
    }
    input, select {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: var(--text);
      min-height: 40px;
      padding: 8px 10px;
      width: 100%;
    }
    label {
      color: var(--muted);
      display: grid;
      font-size: 12px;
      gap: 5px;
      min-width: 160px;
    }
    .app-shell {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      backdrop-filter: blur(18px);
      background: var(--surface-glass);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 20px;
      padding: 18px;
      position: sticky;
      top: 0;
      height: 100vh;
    }
    .brand {
      border-bottom: 1px solid var(--border);
      padding-bottom: 18px;
    }
    .brand-mark {
      align-items: center;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-radius: var(--radius);
      color: #061016;
      display: inline-flex;
      font-weight: 800;
      height: 34px;
      justify-content: center;
      margin-bottom: 12px;
      width: 34px;
      animation: softPulse 4.8s ease-in-out infinite;
      box-shadow: 0 10px 28px color-mix(in srgb, var(--accent) 22%, transparent);
    }
    .brand h1 {
      font-size: 18px;
      line-height: 1.18;
      margin: 0;
    }
    .brand span {
      color: var(--muted);
      display: block;
      font-size: 12px;
      margin-top: 6px;
    }
    .nav {
      display: grid;
      gap: 8px;
    }
    .tab {
      background: transparent;
      color: var(--muted);
      justify-content: flex-start;
      min-height: 42px;
      position: relative;
      width: 100%;
    }
    .tab .tab-dot {
      background: var(--border-strong);
      border-radius: 999px;
      height: 8px;
      width: 8px;
    }
    .tab[aria-selected="true"] {
      background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 18%, var(--surface)), color-mix(in srgb, var(--accent-2) 7%, var(--surface)));
      border-color: color-mix(in srgb, var(--accent) 56%, var(--border));
      color: var(--text);
    }
    .tab[aria-selected="true"]::after {
      background: linear-gradient(180deg, var(--accent), var(--accent-2));
      border-radius: 999px;
      content: "";
      inset: 9px 8px 9px auto;
      position: absolute;
      width: 3px;
    }
    .tab[aria-selected="true"] .tab-dot { background: var(--accent); }
    .sidebar-footer {
      margin-top: auto;
      color: var(--muted);
      font-size: 12px;
    }
    .workspace {
      min-width: 0;
      padding: 22px;
    }
    .topbar {
      align-items: center;
      backdrop-filter: blur(12px);
      background: linear-gradient(180deg, color-mix(in srgb, var(--bg) 78%, transparent), transparent);
      display: flex;
      gap: 14px;
      justify-content: space-between;
      margin-bottom: 18px;
      position: sticky;
      top: 0;
      z-index: 5;
      padding-bottom: 12px;
    }
    .topbar-title h2 {
      font-size: 24px;
      margin: 0;
    }
    .topbar-title p {
      color: var(--muted);
      margin: 4px 0 0;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }
    .refresh-control {
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: grid;
      gap: 5px;
      min-width: 150px;
      overflow: hidden;
      padding: 6px 8px 4px;
      position: relative;
    }
    .refresh-control span {
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      text-transform: uppercase;
    }
    .refresh-control select {
      background: transparent;
      border: 0;
      min-height: 24px;
      padding: 0 18px 0 0;
    }
    .refresh-progress {
      background: color-mix(in srgb, var(--accent) 20%, transparent);
      bottom: 0;
      height: 2px;
      left: 0;
      overflow: hidden;
      position: absolute;
      right: 0;
    }
    .refresh-progress i {
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      display: block;
      height: 100%;
      transform: scaleX(0);
      transform-origin: left;
    }
    .refresh-control.is-active .refresh-progress i {
      animation: refreshProgress var(--refresh-ms, 10000ms) linear infinite;
    }
    .workspace.is-refreshing .status-stage,
    .workspace.is-refreshing .panel-header {
      border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
    }
    .action, .ghost {
      background: var(--surface);
      color: var(--text);
    }
    .ghost:hover, .action:hover {
      background: color-mix(in srgb, var(--accent) 8%, var(--surface));
    }
    .primary {
      background: var(--primary-bg);
      border-color: var(--primary-border);
      color: var(--primary-text);
      font-weight: 700;
      position: relative;
      overflow: hidden;
    }
    .primary::after {
      background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.34), transparent);
      content: "";
      inset: 0;
      pointer-events: none;
      position: absolute;
      transform: translateX(-120%);
    }
    .primary:hover::after {
      animation: sheen 900ms ease;
    }
    .danger-soft {
      color: var(--bad);
    }
    .icon {
      display: inline-block;
      height: 14px;
      position: relative;
      width: 14px;
    }
    .icon::before, .icon::after {
      background: currentColor;
      content: "";
      display: block;
      position: absolute;
    }
    .icon.refresh::before { border-radius: 999px; height: 14px; left: 0; opacity: 0.18; top: 0; width: 14px; }
    .icon.refresh::after { height: 8px; left: 6px; top: 3px; width: 2px; }
    .icon.export::before { height: 10px; left: 6px; top: 1px; width: 2px; }
    .icon.export::after { height: 2px; left: 3px; top: 11px; width: 8px; }
    .icon.theme::before { border-radius: 999px; height: 14px; left: 0; top: 0; width: 14px; }
    .icon.theme::after { background: var(--surface); border-radius: 999px; height: 10px; left: 6px; top: 2px; width: 10px; }
    .error-box {
      background: color-mix(in srgb, var(--bad) 14%, var(--surface));
      border: 1px solid color-mix(in srgb, var(--bad) 46%, var(--border));
      border-radius: var(--radius);
      color: var(--text);
      display: none;
      margin-bottom: 14px;
      padding: 12px 14px;
    }
    section[hidden] { display: none; }
    .overview-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: minmax(340px, 1.15fr) minmax(280px, 0.9fr) minmax(280px, 0.9fr);
      margin-bottom: 14px;
    }
    .status-stage {
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, var(--surface)), var(--surface) 58%),
        linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent-2) 14%, transparent));
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      min-height: 230px;
      overflow: hidden;
      padding: 20px;
      position: relative;
    }
    .status-stage::before {
      background: linear-gradient(90deg, var(--accent), var(--accent-2), var(--accent-3));
      content: "";
      height: 3px;
      inset: 0 0 auto;
      position: absolute;
    }
    .status-stage::after {
      background: repeating-linear-gradient(90deg, transparent 0 18px, rgba(148, 163, 184, 0.08) 18px 19px);
      bottom: 0;
      content: "";
      left: 0;
      opacity: 0.45;
      pointer-events: none;
      position: absolute;
      right: 0;
      top: 0;
      animation: gridDrift 22s linear infinite;
    }
    .status-stage > * { position: relative; z-index: 1; }
    .status-line {
      align-items: flex-start;
      display: flex;
      gap: 16px;
      justify-content: space-between;
    }
    .status-title {
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
    }
    .state-value {
      font-size: 34px;
      font-weight: 800;
      line-height: 1.05;
      margin-top: 8px;
      overflow-wrap: anywhere;
    }
    .status-meta {
      color: var(--soft);
      display: grid;
      gap: 8px;
      margin-top: 24px;
    }
    .status-meta div {
      align-items: center;
      background: color-mix(in srgb, var(--surface-3) 62%, transparent);
      border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
      border-radius: var(--radius);
      display: flex;
      gap: 8px;
      padding: 7px 9px;
    }
    .health-rail {
      align-items: end;
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(8, 1fr);
      margin-top: 26px;
      min-height: 62px;
    }
    .rail-bar {
      background: linear-gradient(180deg, var(--accent), var(--accent-2));
      border-radius: 4px 4px 0 0;
      min-height: 10px;
      opacity: 0.86;
      transform-origin: bottom;
      animation: railRise var(--motion-slow) cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .rail-bar.warn { background: linear-gradient(180deg, var(--accent-3), var(--warn)); }
    .rail-bar.bad { background: linear-gradient(180deg, var(--bad), #f43f5e); }
    .panel, .metric {
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
      animation: surfaceIn 420ms ease both;
    }
    .panel:hover, .metric:hover {
      border-color: color-mix(in srgb, var(--accent) 28%, var(--border));
      transform: translateY(-1px);
      transition: border-color var(--motion-fast) ease, transform var(--motion-fast) ease;
    }
    .panel-header {
      align-items: center;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 78%, transparent), transparent);
      display: flex;
      gap: 12px;
      justify-content: space-between;
      min-height: 54px;
      padding: 14px 16px;
    }
    .panel-header h3 {
      font-size: 15px;
      margin: 0;
    }
    .panel-header small {
      color: var(--muted);
      white-space: nowrap;
    }
    .panel-body { padding: 14px 16px; }
    .metric-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 14px;
    }
    .metric {
      min-height: 112px;
      padding: 14px;
      position: relative;
    }
    .metric::after {
      background: radial-gradient(circle at 85% 15%, color-mix(in srgb, var(--accent) 24%, transparent), transparent 46%);
      content: "";
      inset: 0;
      opacity: 0.75;
      pointer-events: none;
      position: absolute;
    }
    .metric > * { position: relative; z-index: 1; }
    .metric::before {
      background: var(--accent);
      content: "";
      height: 3px;
      left: 14px;
      position: absolute;
      right: 14px;
      top: 0;
    }
    .metric.warn::before { background: var(--warn); }
    .metric.bad::before { background: var(--bad); }
    .metric.info::before { background: var(--info); }
    .metric-label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }
    .metric-value {
      font-size: 26px;
      font-weight: 780;
      margin-top: 10px;
      overflow-wrap: anywhere;
    }
    .metric-sub {
      color: var(--muted);
      margin-top: 8px;
      overflow-wrap: anywhere;
    }
    .filters {
      align-items: end;
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      margin-bottom: 12px;
    }
    .filter-actions {
      align-self: end;
      display: flex;
      gap: 8px;
    }
    .table-wrap {
      border-radius: 0 0 var(--radius) var(--radius);
      overflow: auto;
      width: 100%;
    }
    .table-wrap[aria-busy="true"] {
      opacity: 0.72;
    }
    table {
      border-collapse: collapse;
      min-width: 840px;
      table-layout: fixed;
      width: 100%;
    }
    #sync-table { min-width: 1180px; }
    #change-table { min-width: 1360px; }
    #log-table { min-width: 1120px; }
    #source-table, #target-table { min-width: 920px; }
    #openwebui-table { min-width: 1420px; }
    #log-table th:nth-child(1) { width: 17%; }
    #log-table th:nth-child(2) { width: 10%; }
    #log-table th:nth-child(3) { width: 15%; }
    #log-table th:nth-child(4) { width: 18%; }
    #log-table th:nth-child(5) { width: 40%; }
    #change-table th:nth-child(1) { width: 12%; }
    #change-table th:nth-child(2) { width: 15%; }
    #change-table th:nth-child(3) { width: 8%; }
    #change-table th:nth-child(4) { width: 8%; }
    #change-table th:nth-child(5) { width: 9%; }
    #change-table th:nth-child(6) { width: 14%; }
    #change-table th:nth-child(7) { width: 15%; }
    #change-table th:nth-child(8) { width: 15%; }
    #change-table th:nth-child(9) { width: 14%; }
    th, td {
      border-bottom: 1px solid var(--border);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: var(--surface-2);
      color: var(--muted);
      font-size: 11px;
      position: sticky;
      text-transform: uppercase;
      top: 0;
      z-index: 1;
    }
    th:first-child, td:first-child { padding-left: 16px; }
    th:last-child, td:last-child { padding-right: 16px; }
    tbody tr {
      transition: background 120ms ease;
    }
    tbody tr:hover td, tbody tr:focus-within td {
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }
    td {
      color: var(--soft);
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    tr.clickable { cursor: pointer; }
    tr.clickable:focus-visible {
      outline: 0;
      box-shadow: inset var(--focus);
    }
    .compact-table table { min-width: 680px; }
    .status {
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 999px;
      display: inline-flex;
      gap: 6px;
      max-width: 100%;
      padding: 3px 9px;
      white-space: nowrap;
    }
    .status::before {
      background: var(--unknown);
      border-radius: 999px;
      content: "";
      height: 7px;
      width: 7px;
    }
    .status.ok, .status.succeeded, .status.synced, .status.done, .status.running, .status.wartend {
      color: var(--ok);
      border-color: color-mix(in srgb, var(--ok) 42%, var(--border));
      background: color-mix(in srgb, var(--ok) 10%, transparent);
    }
    .status.ok::before, .status.succeeded::before, .status.synced::before, .status.done::before, .status.running::before, .status.wartend::before {
      background: var(--ok);
    }
    .status.warning, .status.warn, .status.retrying, .status.skipped, .status.übersprungen, .status.manual_required, .status.partial, .status.planned, .status.deleted {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 42%, var(--border));
      background: color-mix(in srgb, var(--warn) 10%, transparent);
    }
    .status.warning::before, .status.warn::before, .status.retrying::before, .status.skipped::before, .status.übersprungen::before, .status.manual_required::before, .status.partial::before, .status.planned::before, .status.deleted::before {
      background: var(--warn);
    }
    .status.error, .status.failed, .status.dead, .status.fehlgeschlagen, .status.fehlerhaft {
      color: var(--bad);
      border-color: color-mix(in srgb, var(--bad) 42%, var(--border));
      background: color-mix(in srgb, var(--bad) 10%, transparent);
    }
    .status.error::before, .status.failed::before, .status.dead::before, .status.fehlgeschlagen::before, .status.fehlerhaft::before {
      background: var(--bad);
    }
    .detail {
      background: #070b12;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: #dce7f5;
      line-height: 1.5;
      max-height: 460px;
      overflow: auto;
      padding: 14px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    :root[data-theme="light"] .detail {
      background: #0f172a;
      color: #eef2ff;
    }
    .empty {
      color: var(--muted);
      padding: 14px 0;
    }
    .empty-state {
      align-items: center;
      display: grid;
      gap: 5px;
      justify-items: center;
      min-height: 112px;
      text-align: center;
    }
    .empty-state strong {
      color: var(--text);
      font-size: 14px;
    }
    .empty-state span {
      color: var(--muted);
      font-size: 12px;
    }
    .problem-list {
      display: grid;
      gap: 10px;
    }
    .problem-item {
      background: color-mix(in srgb, var(--surface-2) 66%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 10px 12px;
    }
    .problem-item strong {
      color: var(--text);
      display: block;
      margin-bottom: 4px;
      overflow-wrap: anywhere;
    }
    .problem-item span {
      color: var(--muted);
      display: block;
      font-size: 12px;
    }
    .health-list {
      display: grid;
      gap: 10px;
    }
    .health-item {
      align-items: flex-start;
      background: color-mix(in srgb, var(--surface-2) 58%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      display: grid;
      gap: 8px;
      grid-template-columns: auto minmax(0, 1fr) auto;
      padding: 10px 12px;
    }
    .health-led {
      background: var(--unknown);
      border-radius: 999px;
      height: 10px;
      margin-top: 5px;
      width: 10px;
    }
    .health-item.ok .health-led {
      background: var(--ok);
      box-shadow: 0 0 0 5px color-mix(in srgb, var(--ok) 14%, transparent);
    }
    .health-item.warning .health-led {
      background: var(--warn);
      box-shadow: 0 0 0 5px color-mix(in srgb, var(--warn) 14%, transparent);
    }
    .health-item.error .health-led {
      background: var(--bad);
      box-shadow: 0 0 0 5px color-mix(in srgb, var(--bad) 14%, transparent);
    }
    .health-name {
      color: var(--text);
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .health-message {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    .health-transport {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
      overflow-wrap: anywhere;
    }
    .transport-badge {
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      font-size: 11px;
      font-weight: 800;
      margin-right: 6px;
      padding: 2px 7px;
      text-transform: uppercase;
    }
    .transport-badge.https {
      background: color-mix(in srgb, var(--ok) 12%, transparent);
      border-color: color-mix(in srgb, var(--ok) 38%, var(--border));
      color: var(--ok);
    }
    .transport-badge.http {
      background: color-mix(in srgb, var(--warn) 12%, transparent);
      border-color: color-mix(in srgb, var(--warn) 38%, var(--border));
      color: var(--warn);
    }
    .health-latency {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .pager {
      align-items: center;
      color: var(--muted);
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      padding-top: 12px;
    }
    .pager button {
      background: var(--surface-2);
      color: var(--text);
      min-width: 76px;
    }
    .pager button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
      transform: none;
    }
    .split {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .sync-detail {
      margin-top: 14px;
    }
    .long-cell {
      min-width: 0;
    }
    .long-text {
      display: grid;
      gap: 7px;
      max-width: 100%;
      min-width: 0;
    }
    .long-text-preview {
      color: var(--soft);
      display: block;
      max-width: 100%;
      overflow-wrap: anywhere;
      white-space: normal;
      word-break: break-word;
    }
    .long-text.is-collapsible:not(.is-expanded) .long-text-preview {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: var(--cell-lines, 2);
      overflow: hidden;
    }
    .long-text.is-expanded .long-text-preview {
      display: block;
    }
    .cell-toggle {
      background: color-mix(in srgb, var(--accent) 10%, var(--surface));
      border-color: color-mix(in srgb, var(--accent) 34%, var(--border));
      color: var(--text);
      font-size: 12px;
      justify-self: start;
      min-height: 28px;
      padding: 4px 8px;
    }
    .cell-toggle::before {
      content: "+";
      color: var(--accent);
      font-weight: 800;
    }
    .cell-toggle[aria-expanded="true"]::before {
      content: "-";
    }
    .message-cell .long-text {
      --cell-lines: 3;
    }
    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .mini-pill {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--soft);
      padding: 5px 9px;
    }
    @media (max-width: 1180px) {
      .app-shell { grid-template-columns: 1fr; }
      .sidebar {
        height: auto;
        position: relative;
      }
      .nav {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .overview-grid, .split { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .workspace, .sidebar { padding: 12px; }
      .topbar { align-items: stretch; flex-direction: column; position: static; }
      .actions { justify-content: stretch; }
      .actions > * { flex: 1; }
      .nav { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: 1fr; }
      .state-value { font-size: 28px; }
      button, a.action, input, select { min-height: 44px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 1ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
        transition-duration: 1ms !important;
      }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">SR</div>
        <h1>Connector Dashboard</h1>
        <span>Seafile zu RAGFlow</span>
      </div>
      <nav class="nav" aria-label="Dashboard Bereiche">
        <button class="tab" data-tab="overview" aria-selected="true"><span class="tab-dot"></span>Übersicht</button>
        <button class="tab" data-tab="syncs" aria-selected="false"><span class="tab-dot"></span>Sync-Läufe</button>
        <button class="tab" data-tab="changes" aria-selected="false"><span class="tab-dot"></span>Änderungen</button>
        <button class="tab" data-tab="logs" aria-selected="false"><span class="tab-dot"></span>Logs</button>
        <button class="tab" data-tab="systems" aria-selected="false"><span class="tab-dot"></span>Systeme</button>
        <button class="tab" data-tab="openwebui" aria-selected="false"><span class="tab-dot"></span>OpenWebUI</button>
        <button class="tab" data-tab="diagnostics" aria-selected="false"><span class="tab-dot"></span>Diagnose</button>
      </nav>
      <div class="sidebar-footer">
        <div id="sidebar-state">Lade Status...</div>
        <div id="sidebar-updated">Noch nicht aktualisiert</div>
      </div>
    </aside>
    <main class="workspace" aria-busy="false">
      <div class="topbar">
        <div class="topbar-title">
          <h2 id="view-title">Übersicht</h2>
          <p id="view-subtitle">Live-Zustand, Durchsatz und Auffälligkeiten</p>
        </div>
        <div class="actions">
          <label class="refresh-control" for="refresh-interval">
            <span>Auto-Refresh</span>
            <select id="refresh-interval">
              <option value="0">Aus</option>
              <option value="5000">5 Sekunden</option>
              <option value="10000">10 Sekunden</option>
              <option value="60000">1 Minute</option>
            </select>
            <b class="refresh-progress" aria-hidden="true"><i></i></b>
          </label>
          <label class="refresh-control" for="language-select">
            <span>Sprache</span>
            <select id="language-select" autocomplete="off">
              <option value="de">Deutsch</option>
              <option value="en">English</option>
              <option value="es">Español</option>
              <option value="fr">Français</option>
              <option value="it">Italiano</option>
              <option value="pt">Português</option>
              <option value="nl">Nederlands</option>
              <option value="pl">Polski</option>
              <option value="tr">Türkçe</option>
              <option value="uk">Українська</option>
              <option value="zh">中文</option>
              <option value="ja">日本語</option>
              <option value="ar">العربية</option>
            </select>
            <b class="refresh-progress" aria-hidden="true"><i></i></b>
          </label>
          <button class="ghost" id="refresh-active" type="button"><span class="icon refresh"></span>Aktualisieren</button>
          <button class="ghost" id="theme-toggle" type="button" aria-pressed="true"><span class="icon theme"></span>Dark</button>
          <a class="action primary" id="audit-export" href="/api/audit.xlsx" download><span class="icon export"></span>Audit Excel</a>
        </div>
      </div>
      <div id="error" class="error-box" role="alert"></div>

      <section id="overview">
        <div class="overview-grid">
          <div class="status-stage">
            <div class="status-line">
              <div>
                <div class="status-title">Connector Zustand</div>
                <div class="state-value" id="state-value">-</div>
              </div>
              <div id="state-pill"></div>
            </div>
            <div class="status-meta">
              <div id="started-at">Start: -</div>
              <div id="last-success">Letzter Erfolg: -</div>
              <div id="last-failure">Letzter Fehler: -</div>
            </div>
            <div class="health-rail" id="health-rail" aria-hidden="true"></div>
          </div>
          <div class="panel">
            <div class="panel-header">
              <h3>System Health</h3>
              <small id="health-summary">prüfe...</small>
            </div>
            <div class="panel-body"><div id="dependency-health" class="health-list"></div></div>
          </div>
          <div class="panel">
            <div class="panel-header">
              <h3>Fehler und Warnungen</h3>
              <small id="problem-count">0 Einträge</small>
            </div>
            <div class="panel-body"><div id="problems" class="problem-list"></div></div>
          </div>
        </div>
        <div class="metric-grid" id="metrics"></div>
        <div class="split">
          <div class="panel compact-table">
            <div class="panel-header"><h3>Letzte Sync-Läufe</h3><small id="recent-sync-count">0</small></div>
            <div class="table-wrap"><table id="recent-syncs"></table></div>
          </div>
          <div class="panel compact-table">
            <div class="panel-header"><h3>Neueste Änderungen</h3><small id="recent-change-count">0</small></div>
            <div class="table-wrap"><table id="recent-changes"></table></div>
          </div>
        </div>
      </section>

      <section id="syncs" hidden>
        <div class="panel">
          <div class="panel-header"><h3>Synchronisationshistorie</h3><small id="sync-total">0 Läufe</small></div>
          <div class="panel-body">
            <div class="filters">
              <label>Status
                <select id="sync-status">
                  <option value="">Alle</option>
                  <option value="running">running</option>
                  <option value="succeeded">succeeded</option>
                  <option value="failed">failed</option>
                </select>
              </label>
              <div class="filter-actions">
                <button class="primary" id="sync-refresh" type="button">Filtern</button>
              </div>
            </div>
            <div class="table-wrap"><table id="sync-table"></table></div>
            <div id="sync-pager" class="pager"></div>
            <div id="sync-detail" class="sync-detail"></div>
          </div>
        </div>
      </section>

      <section id="changes" hidden>
        <div class="panel">
          <div class="panel-header"><h3>Erkannte Änderungen</h3><small id="change-total">0 Ereignisse</small></div>
          <div class="panel-body">
            <div class="filters">
              <label>Sync-ID <input id="change-sync" autocomplete="off" placeholder="optional"></label>
              <label>Status <input id="change-status" autocomplete="off" placeholder="synced, failed, skipped"></label>
              <label>Typ <input id="change-type" autocomplete="off" placeholder="created, updated, deleted"></label>
              <label>Suche <input id="change-query" autocomplete="off" placeholder="Pfad, Name, Fehler"></label>
              <div class="filter-actions"><button class="primary" id="change-refresh" type="button">Filtern</button></div>
            </div>
            <div class="table-wrap"><table id="change-table"></table></div>
            <div id="change-pager" class="pager"></div>
          </div>
        </div>
      </section>

      <section id="logs" hidden>
        <div class="panel">
          <div class="panel-header"><h3>Logereignisse</h3><small id="log-total">0 Logs</small></div>
          <div class="panel-body">
            <div class="filters">
              <label>Level
                <select id="log-level">
                  <option value="">Alle</option>
                  <option value="debug">debug</option>
                  <option value="info">info</option>
                  <option value="warning">warning</option>
                  <option value="error">error</option>
                </select>
              </label>
              <label>Sync-ID <input id="log-sync" autocomplete="off" placeholder="optional"></label>
              <label>Suche <input id="log-query" autocomplete="off" placeholder="Nachricht oder Komponente"></label>
              <div class="filter-actions"><button class="primary" id="log-refresh" type="button">Filtern</button></div>
            </div>
            <div class="table-wrap"><table id="log-table"></table></div>
            <div id="log-pager" class="pager"></div>
            <pre id="log-detail" class="detail" hidden></pre>
          </div>
        </div>
      </section>

      <section id="systems" hidden>
        <div class="split">
          <div class="panel">
            <div class="panel-header"><h3>Quellsysteme</h3><small>Seafile</small></div>
            <div class="table-wrap"><table id="source-table"></table></div>
          </div>
          <div class="panel">
            <div class="panel-header"><h3>Zielsysteme</h3><small>RAGFlow</small></div>
            <div class="table-wrap"><table id="target-table"></table></div>
          </div>
        </div>
      </section>

      <section id="openwebui" hidden>
        <div class="panel">
          <div class="panel-header"><h3>OpenWebUI Integration</h3><small id="openwebui-summary">-</small></div>
          <div class="panel-body">
            <div class="metric-grid" id="openwebui-metrics"></div>
            <div class="table-wrap"><table id="openwebui-table"></table></div>
            <div id="openwebui-pager" class="pager"></div>
            <pre id="openwebui-detail" class="detail"></pre>
          </div>
        </div>
      </section>

      <section id="diagnostics" hidden>
        <div class="panel">
          <div class="panel-header"><h3>Technische Diagnose</h3><small>maskierte Konfiguration</small></div>
          <div class="panel-body"><pre id="diagnostics-json" class="detail"></pre></div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const PAGE_SIZE = 100;
    const SUPPORTED_LANGUAGES = ['de', 'en', 'es', 'fr', 'it', 'pt', 'nl', 'pl', 'tr', 'uk', 'zh', 'ja', 'ar'];
    const I18N = {
      de: {
        'brand.subtitle': 'Seafile zu RAGFlow',
        'nav.label': 'Dashboard Bereiche',
        'nav.overview': 'Übersicht',
        'nav.syncs': 'Sync-Läufe',
        'nav.changes': 'Änderungen',
        'nav.logs': 'Logs',
        'nav.systems': 'Systeme',
        'nav.openwebui': 'OpenWebUI',
        'nav.diagnostics': 'Diagnose',
        'sidebar.loading': 'Lade Status...',
        'sidebar.notUpdated': 'Noch nicht aktualisiert',
        'action.refresh': 'Aktualisieren',
        'action.audit': 'Audit Excel',
        'action.filter': 'Filtern',
        'action.more': 'Mehr',
        'action.less': 'Weniger',
        'pager.of': 'von',
        'pager.previous': 'Zurück',
        'pager.next': 'Weiter',
        'empty.title': 'Keine Einträge vorhanden',
        'empty.hint': 'Die Ansicht ist geladen und enthält aktuell keine passenden Daten.',
        'status.unknown': 'unbekannt',
        'health.encrypted': 'verschlüsselt',
        'health.unencrypted': 'unverschlüsselt',
        'health.fallback': 'Fallback nach HTTPS-Fehler',
        'health.none': 'Keine Health-Daten vorhanden.',
        'problems.none': 'Keine aktuellen Fehler oder Warnungen.',
        'counts.entries': 'Einträge',
        'counts.runs': 'Läufe',
        'counts.events': 'Ereignisse',
        'titles.overview': 'Übersicht',
        'subtitles.overview': 'Live-Zustand, Durchsatz und Auffälligkeiten',
        'titles.syncs': 'Sync-Läufe',
        'subtitles.syncs': 'Historie, Laufzeiten und Ergebnisdetails',
        'titles.changes': 'Änderungen',
        'subtitles.changes': 'Aktionen mit Quelle, Ziel, Objekt und Status',
        'titles.logs': 'Logs',
        'subtitles.logs': 'Filterbare Debug- und Audit-Ereignisse',
        'titles.systems': 'Systeme',
        'subtitles.systems': 'Seafile-Libraries und RAGFlow-Datasets',
        'titles.openwebui': 'OpenWebUI',
        'subtitles.openwebui': 'Tools, Pipes, Custom-Modelle und Fehlerstatus',
        'titles.diagnostics': 'Diagnose',
        'subtitles.diagnostics': 'Technische Werte ohne Secrets',
        'metric.libraries': 'Libraries',
        'metric.files': 'Dateien',
        'metric.syncRuns': 'Sync-Läufe',
        'metric.changes': 'Änderungen',
        'metric.checked': 'Objekte geprüft',
        'metric.queue': 'Queue/Retry',
        'metric.warnings': 'Warnungen',
        'metric.errors': 'Fehler',
        'table.time': 'Zeit',
        'table.start': 'Start',
        'table.status': 'Status',
        'table.source': 'Quelle',
        'table.target': 'Ziel',
        'table.objects': 'Objekte',
        'table.duration': 'Dauer',
        'table.new': 'Neu',
        'table.updated': 'Aktualisiert',
        'table.deleted': 'Gelöscht',
        'table.skipped': 'Übersprungen',
        'table.action': 'Aktion',
        'table.type': 'Typ',
        'table.error': 'Fehler',
        'table.message': 'Nachricht',
        'openwebui.active': 'aktiv',
        'openwebui.off': 'aus',
        'api.error': 'API-Fehler'
      },
      en: {
        'brand.subtitle': 'Seafile to RAGFlow',
        'nav.label': 'Dashboard sections',
        'nav.overview': 'Overview',
        'nav.syncs': 'Sync runs',
        'nav.changes': 'Changes',
        'nav.logs': 'Logs',
        'nav.systems': 'Systems',
        'nav.openwebui': 'OpenWebUI',
        'nav.diagnostics': 'Diagnostics',
        'sidebar.loading': 'Loading status...',
        'sidebar.notUpdated': 'Not updated yet',
        'action.refresh': 'Refresh',
        'action.audit': 'Audit Excel',
        'action.filter': 'Filter',
        'action.more': 'More',
        'action.less': 'Less',
        'pager.of': 'of',
        'pager.previous': 'Previous',
        'pager.next': 'Next',
        'empty.title': 'No entries available',
        'empty.hint': 'The view is loaded and currently has no matching data.',
        'status.unknown': 'unknown',
        'health.encrypted': 'encrypted',
        'health.unencrypted': 'unencrypted',
        'health.fallback': 'fallback after HTTPS error',
        'health.none': 'No health data available.',
        'problems.none': 'No current errors or warnings.',
        'counts.entries': 'entries',
        'counts.runs': 'runs',
        'counts.events': 'events',
        'titles.overview': 'Overview',
        'subtitles.overview': 'Live state, throughput, and anomalies',
        'titles.syncs': 'Sync runs',
        'subtitles.syncs': 'History, runtimes, and result details',
        'titles.changes': 'Changes',
        'subtitles.changes': 'Actions with source, target, object, and status',
        'titles.logs': 'Logs',
        'subtitles.logs': 'Filterable debug and audit events',
        'titles.systems': 'Systems',
        'subtitles.systems': 'Seafile libraries and RAGFlow datasets',
        'titles.openwebui': 'OpenWebUI',
        'subtitles.openwebui': 'Tools, pipes, custom models, and error state',
        'titles.diagnostics': 'Diagnostics',
        'subtitles.diagnostics': 'Technical values without secrets',
        'metric.libraries': 'Libraries',
        'metric.files': 'Files',
        'metric.syncRuns': 'Sync runs',
        'metric.changes': 'Changes',
        'metric.checked': 'Objects checked',
        'metric.queue': 'Queue/retry',
        'metric.warnings': 'Warnings',
        'metric.errors': 'Errors',
        'table.time': 'Time',
        'table.start': 'Start',
        'table.status': 'Status',
        'table.source': 'Source',
        'table.target': 'Target',
        'table.objects': 'Objects',
        'table.duration': 'Duration',
        'table.new': 'New',
        'table.updated': 'Updated',
        'table.deleted': 'Deleted',
        'table.skipped': 'Skipped',
        'table.action': 'Action',
        'table.type': 'Type',
        'table.error': 'Error',
        'table.message': 'Message',
        'openwebui.active': 'active',
        'openwebui.off': 'off',
        'api.error': 'API error'
      }
    };
    Object.assign(I18N, {
      es: {'brand.subtitle':'Seafile a RAGFlow','nav.label':'Secciones del panel','nav.overview':'Resumen','nav.syncs':'Sincronizaciones','nav.changes':'Cambios','nav.logs':'Logs','nav.systems':'Sistemas','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnóstico','titles.overview':'Resumen','subtitles.overview':'Estado en vivo, rendimiento y anomalías','titles.syncs':'Sincronizaciones','subtitles.syncs':'Historial, tiempos y detalles','titles.changes':'Cambios','subtitles.changes':'Acciones con origen, destino, objeto y estado','titles.logs':'Logs','subtitles.logs':'Eventos de depuración y auditoría filtrables','titles.systems':'Sistemas','subtitles.systems':'Bibliotecas de Seafile y datasets de RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Herramientas, pipes, modelos personalizados y errores','titles.diagnostics':'Diagnóstico','subtitles.diagnostics':'Valores técnicos sin secretos','action.refresh':'Actualizar','action.filter':'Filtrar','action.more':'Más','action.less':'Menos','status.unknown':'desconocido','table.source':'Origen','table.target':'Destino','table.status':'Estado','table.message':'Mensaje','table.error':'Error','openwebui.active':'activo','openwebui.off':'apagado','api.error':'Error de API'},
      fr: {'brand.subtitle':'Seafile vers RAGFlow','nav.label':'Sections du tableau de bord','nav.overview':'Vue d’ensemble','nav.syncs':'Synchronisations','nav.changes':'Changements','nav.logs':'Logs','nav.systems':'Systèmes','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnostic','titles.overview':'Vue d’ensemble','subtitles.overview':'État en direct, débit et anomalies','titles.syncs':'Synchronisations','subtitles.syncs':'Historique, durées et détails','titles.changes':'Changements','subtitles.changes':'Actions avec source, cible, objet et état','titles.logs':'Logs','subtitles.logs':'Événements de debug et d’audit filtrables','titles.systems':'Systèmes','subtitles.systems':'Bibliothèques Seafile et datasets RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Outils, pipes, modèles personnalisés et erreurs','titles.diagnostics':'Diagnostic','subtitles.diagnostics':'Valeurs techniques sans secrets','action.refresh':'Actualiser','action.filter':'Filtrer','action.more':'Plus','action.less':'Moins','status.unknown':'inconnu','table.source':'Source','table.target':'Cible','table.status':'État','table.message':'Message','table.error':'Erreur','openwebui.active':'actif','openwebui.off':'désactivé','api.error':'Erreur API'},
      it: {'brand.subtitle':'Da Seafile a RAGFlow','nav.label':'Sezioni dashboard','nav.overview':'Panoramica','nav.syncs':'Sincronizzazioni','nav.changes':'Modifiche','nav.logs':'Log','nav.systems':'Sistemi','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnostica','titles.overview':'Panoramica','subtitles.overview':'Stato live, throughput e anomalie','titles.syncs':'Sincronizzazioni','subtitles.syncs':'Storico, tempi e dettagli','titles.changes':'Modifiche','subtitles.changes':'Azioni con origine, destinazione, oggetto e stato','titles.logs':'Log','subtitles.logs':'Eventi debug e audit filtrabili','titles.systems':'Sistemi','subtitles.systems':'Librerie Seafile e dataset RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Tool, pipe, modelli personalizzati ed errori','titles.diagnostics':'Diagnostica','subtitles.diagnostics':'Valori tecnici senza segreti','action.refresh':'Aggiorna','action.filter':'Filtra','action.more':'Altro','action.less':'Meno','status.unknown':'sconosciuto','table.source':'Origine','table.target':'Destinazione','table.status':'Stato','table.message':'Messaggio','table.error':'Errore','openwebui.active':'attivo','openwebui.off':'spento','api.error':'Errore API'},
      pt: {'brand.subtitle':'Seafile para RAGFlow','nav.label':'Seções do painel','nav.overview':'Visão geral','nav.syncs':'Sincronizações','nav.changes':'Alterações','nav.logs':'Logs','nav.systems':'Sistemas','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnóstico','titles.overview':'Visão geral','subtitles.overview':'Estado ao vivo, vazão e anomalias','titles.syncs':'Sincronizações','subtitles.syncs':'Histórico, tempos e detalhes','titles.changes':'Alterações','subtitles.changes':'Ações com origem, destino, objeto e estado','titles.logs':'Logs','subtitles.logs':'Eventos de depuração e auditoria filtráveis','titles.systems':'Sistemas','subtitles.systems':'Bibliotecas Seafile e datasets RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Ferramentas, pipes, modelos personalizados e erros','titles.diagnostics':'Diagnóstico','subtitles.diagnostics':'Valores técnicos sem segredos','action.refresh':'Atualizar','action.filter':'Filtrar','action.more':'Mais','action.less':'Menos','status.unknown':'desconhecido','table.source':'Origem','table.target':'Destino','table.status':'Status','table.message':'Mensagem','table.error':'Erro','openwebui.active':'ativo','openwebui.off':'desligado','api.error':'Erro de API'},
      nl: {'brand.subtitle':'Seafile naar RAGFlow','nav.label':'Dashboardsecties','nav.overview':'Overzicht','nav.syncs':'Syncs','nav.changes':'Wijzigingen','nav.logs':'Logs','nav.systems':'Systemen','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnose','titles.overview':'Overzicht','subtitles.overview':'Live status, doorvoer en afwijkingen','titles.syncs':'Syncs','subtitles.syncs':'Historie, looptijden en details','titles.changes':'Wijzigingen','subtitles.changes':'Acties met bron, doel, object en status','titles.logs':'Logs','subtitles.logs':'Filterbare debug- en auditgebeurtenissen','titles.systems':'Systemen','subtitles.systems':'Seafile-bibliotheken en RAGFlow-datasets','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Tools, pipes, custommodellen en fouten','titles.diagnostics':'Diagnose','subtitles.diagnostics':'Technische waarden zonder secrets','action.refresh':'Vernieuwen','action.filter':'Filteren','action.more':'Meer','action.less':'Minder','status.unknown':'onbekend','table.source':'Bron','table.target':'Doel','table.status':'Status','table.message':'Bericht','table.error':'Fout','openwebui.active':'actief','openwebui.off':'uit','api.error':'API-fout'},
      pl: {'brand.subtitle':'Seafile do RAGFlow','nav.label':'Sekcje panelu','nav.overview':'Przegląd','nav.syncs':'Synchronizacje','nav.changes':'Zmiany','nav.logs':'Logi','nav.systems':'Systemy','nav.openwebui':'OpenWebUI','nav.diagnostics':'Diagnostyka','titles.overview':'Przegląd','subtitles.overview':'Stan na żywo, przepustowość i anomalie','titles.syncs':'Synchronizacje','subtitles.syncs':'Historia, czasy i szczegóły','titles.changes':'Zmiany','subtitles.changes':'Akcje ze źródłem, celem, obiektem i statusem','titles.logs':'Logi','subtitles.logs':'Filtrowalne zdarzenia debug i audytu','titles.systems':'Systemy','subtitles.systems':'Biblioteki Seafile i zbiory RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Narzędzia, pipes, modele niestandardowe i błędy','titles.diagnostics':'Diagnostyka','subtitles.diagnostics':'Wartości techniczne bez sekretów','action.refresh':'Odśwież','action.filter':'Filtruj','action.more':'Więcej','action.less':'Mniej','status.unknown':'nieznany','table.source':'Źródło','table.target':'Cel','table.status':'Status','table.message':'Komunikat','table.error':'Błąd','openwebui.active':'aktywny','openwebui.off':'wyłączony','api.error':'Błąd API'},
      tr: {'brand.subtitle':'Seafile’dan RAGFlow’a','nav.label':'Pano bölümleri','nav.overview':'Genel bakış','nav.syncs':'Senkronizasyonlar','nav.changes':'Değişiklikler','nav.logs':'Loglar','nav.systems':'Sistemler','nav.openwebui':'OpenWebUI','nav.diagnostics':'Tanılama','titles.overview':'Genel bakış','subtitles.overview':'Canlı durum, aktarım ve anomaliler','titles.syncs':'Senkronizasyonlar','subtitles.syncs':'Geçmiş, süreler ve ayrıntılar','titles.changes':'Değişiklikler','subtitles.changes':'Kaynak, hedef, nesne ve durumlu eylemler','titles.logs':'Loglar','subtitles.logs':'Filtrelenebilir debug ve denetim olayları','titles.systems':'Sistemler','subtitles.systems':'Seafile kitaplıkları ve RAGFlow veri kümeleri','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Araçlar, pipe’lar, özel modeller ve hatalar','titles.diagnostics':'Tanılama','subtitles.diagnostics':'Secrets içermeyen teknik değerler','action.refresh':'Yenile','action.filter':'Filtrele','action.more':'Daha fazla','action.less':'Daha az','status.unknown':'bilinmiyor','table.source':'Kaynak','table.target':'Hedef','table.status':'Durum','table.message':'Mesaj','table.error':'Hata','openwebui.active':'aktif','openwebui.off':'kapalı','api.error':'API hatası'},
      uk: {'brand.subtitle':'Seafile до RAGFlow','nav.label':'Розділи панелі','nav.overview':'Огляд','nav.syncs':'Синхронізації','nav.changes':'Зміни','nav.logs':'Логи','nav.systems':'Системи','nav.openwebui':'OpenWebUI','nav.diagnostics':'Діагностика','titles.overview':'Огляд','subtitles.overview':'Живий стан, пропускна здатність і відхилення','titles.syncs':'Синхронізації','subtitles.syncs':'Історія, тривалості та деталі','titles.changes':'Зміни','subtitles.changes':'Дії з джерелом, ціллю, об’єктом і статусом','titles.logs':'Логи','subtitles.logs':'Фільтровані події debug і аудиту','titles.systems':'Системи','subtitles.systems':'Бібліотеки Seafile та набори RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'Інструменти, pipes, користувацькі моделі та помилки','titles.diagnostics':'Діагностика','subtitles.diagnostics':'Технічні значення без секретів','action.refresh':'Оновити','action.filter':'Фільтрувати','action.more':'Більше','action.less':'Менше','status.unknown':'невідомо','table.source':'Джерело','table.target':'Ціль','table.status':'Статус','table.message':'Повідомлення','table.error':'Помилка','openwebui.active':'активно','openwebui.off':'вимкнено','api.error':'Помилка API'},
      zh: {'brand.subtitle':'Seafile 到 RAGFlow','nav.label':'仪表板区域','nav.overview':'概览','nav.syncs':'同步','nav.changes':'变更','nav.logs':'日志','nav.systems':'系统','nav.openwebui':'OpenWebUI','nav.diagnostics':'诊断','titles.overview':'概览','subtitles.overview':'实时状态、吞吐量和异常','titles.syncs':'同步','subtitles.syncs':'历史、运行时间和结果详情','titles.changes':'变更','subtitles.changes':'包含来源、目标、对象和状态的操作','titles.logs':'日志','subtitles.logs':'可筛选的调试和审计事件','titles.systems':'系统','subtitles.systems':'Seafile 库和 RAGFlow 数据集','titles.openwebui':'OpenWebUI','subtitles.openwebui':'工具、pipes、自定义模型和错误状态','titles.diagnostics':'诊断','subtitles.diagnostics':'不含密钥的技术值','action.refresh':'刷新','action.filter':'筛选','action.more':'更多','action.less':'更少','status.unknown':'未知','table.source':'来源','table.target':'目标','table.status':'状态','table.message':'消息','table.error':'错误','openwebui.active':'启用','openwebui.off':'关闭','api.error':'API 错误'},
      ja: {'brand.subtitle':'Seafile から RAGFlow','nav.label':'ダッシュボードセクション','nav.overview':'概要','nav.syncs':'同期','nav.changes':'変更','nav.logs':'ログ','nav.systems':'システム','nav.openwebui':'OpenWebUI','nav.diagnostics':'診断','titles.overview':'概要','subtitles.overview':'ライブ状態、処理量、異常','titles.syncs':'同期','subtitles.syncs':'履歴、実行時間、結果詳細','titles.changes':'変更','subtitles.changes':'ソース、ターゲット、オブジェクト、状態のアクション','titles.logs':'ログ','subtitles.logs':'フィルター可能なデバッグと監査イベント','titles.systems':'システム','subtitles.systems':'Seafile ライブラリと RAGFlow データセット','titles.openwebui':'OpenWebUI','subtitles.openwebui':'ツール、pipes、カスタムモデル、エラー状態','titles.diagnostics':'診断','subtitles.diagnostics':'シークレットを含まない技術値','action.refresh':'更新','action.filter':'フィルター','action.more':'さらに表示','action.less':'折りたたむ','status.unknown':'不明','table.source':'ソース','table.target':'ターゲット','table.status':'状態','table.message':'メッセージ','table.error':'エラー','openwebui.active':'有効','openwebui.off':'オフ','api.error':'API エラー'},
      ar: {'brand.subtitle':'Seafile إلى RAGFlow','nav.label':'أقسام لوحة التحكم','nav.overview':'نظرة عامة','nav.syncs':'المزامنات','nav.changes':'التغييرات','nav.logs':'السجلات','nav.systems':'الأنظمة','nav.openwebui':'OpenWebUI','nav.diagnostics':'التشخيص','titles.overview':'نظرة عامة','subtitles.overview':'الحالة الحية ومعدل المعالجة والشذوذ','titles.syncs':'المزامنات','subtitles.syncs':'السجل والمدد وتفاصيل النتائج','titles.changes':'التغييرات','subtitles.changes':'إجراءات مع المصدر والهدف والكائن والحالة','titles.logs':'السجلات','subtitles.logs':'أحداث تصحيح وتدقيق قابلة للتصفية','titles.systems':'الأنظمة','subtitles.systems':'مكتبات Seafile ومجموعات RAGFlow','titles.openwebui':'OpenWebUI','subtitles.openwebui':'الأدوات و pipes والنماذج المخصصة وحالة الأخطاء','titles.diagnostics':'التشخيص','subtitles.diagnostics':'قيم تقنية دون أسرار','action.refresh':'تحديث','action.filter':'تصفية','action.more':'المزيد','action.less':'أقل','status.unknown':'غير معروف','table.source':'المصدر','table.target':'الهدف','table.status':'الحالة','table.message':'الرسالة','table.error':'خطأ','openwebui.active':'نشط','openwebui.off':'متوقف','api.error':'خطأ API'}
    });
    const LOCALE_TAGS = {de:'de-DE', en:'en-US', es:'es-ES', fr:'fr-FR', it:'it-IT', pt:'pt-PT', nl:'nl-NL', pl:'pl-PL', tr:'tr-TR', uk:'uk-UA', zh:'zh-CN', ja:'ja-JP', ar:'ar-SA'};
    function normalizeLanguage(value) {
      const code = String(value || '').replace('_', '-').toLowerCase().split('-')[0];
      return SUPPORTED_LANGUAGES.includes(code) ? code : '';
    }
    function initialLanguage() {
      const params = new URLSearchParams(window.location.search);
      return normalizeLanguage(params.get('lang'))
        || normalizeLanguage(localStorage.getItem('connector-dashboard-language'))
        || normalizeLanguage(navigator.language)
        || 'de';
    }
    let currentLanguage = initialLanguage();
    function t(key) {
      return (I18N[currentLanguage] && I18N[currentLanguage][key])
        || I18N.en[key]
        || I18N.de[key]
        || key;
    }
    function localeTag() {
      return LOCALE_TAGS[currentLanguage] || 'de-DE';
    }
    const state = {
      activeTab: 'overview',
      loading: false,
      pendingLoad: false,
      refreshTimer: null,
      refreshMs: Number(localStorage.getItem('connector-dashboard-refresh-ms') || '10000'),
      pages: { syncs: 0, changes: 0, logs: 0, openwebui: 0 },
      titles: {}
    };
    const $ = (id) => document.getElementById(id);
    let disclosureId = 0;

    function applyLanguage() {
      document.documentElement.lang = currentLanguage;
      document.documentElement.dir = currentLanguage === 'ar' ? 'rtl' : 'ltr';
      document.title = currentLanguage === 'en'
        ? 'Seafile RAGFlow Connector Dashboard'
        : 'Seafile RAGFlow Connector Dashboard';
      const languageSelect = $('language-select');
      if (languageSelect) languageSelect.value = currentLanguage;
      document.querySelector('.brand span').textContent = t('brand.subtitle');
      document.querySelector('.nav').setAttribute('aria-label', t('nav.label'));
      document.querySelector('[data-tab="overview"]').lastChild.textContent = t('nav.overview');
      document.querySelector('[data-tab="syncs"]').lastChild.textContent = t('nav.syncs');
      document.querySelector('[data-tab="changes"]').lastChild.textContent = t('nav.changes');
      document.querySelector('[data-tab="logs"]').lastChild.textContent = t('nav.logs');
      document.querySelector('[data-tab="systems"]').lastChild.textContent = t('nav.systems');
      document.querySelector('[data-tab="diagnostics"]').lastChild.textContent = t('nav.diagnostics');
      $('sidebar-state').textContent = t('sidebar.loading');
      $('sidebar-updated').textContent = t('sidebar.notUpdated');
      $('refresh-active').lastChild.textContent = t('action.refresh');
      $('audit-export').lastChild.textContent = t('action.audit');
      document.querySelectorAll('.filter-actions button').forEach((button) => {
        button.textContent = t('action.filter');
      });
      state.titles = {
        overview: [t('titles.overview'), t('subtitles.overview')],
        syncs: [t('titles.syncs'), t('subtitles.syncs')],
        changes: [t('titles.changes'), t('subtitles.changes')],
        logs: [t('titles.logs'), t('subtitles.logs')],
        systems: [t('titles.systems'), t('subtitles.systems')],
        openwebui: [t('titles.openwebui'), t('subtitles.openwebui')],
        diagnostics: [t('titles.diagnostics'), t('subtitles.diagnostics')]
      };
      const title = state.titles[state.activeTab] || state.titles.overview;
      setText('view-title', title[0]);
      setText('view-subtitle', title[1]);
    }

    function showError(message) {
      const node = $('error');
      node.textContent = message || '';
      node.style.display = message ? 'block' : 'none';
    }
    async function api(path) {
      const res = await fetch(path, { headers: { 'Accept': 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error || t('api.error'));
      return data;
    }
    function clear(node) {
      while (node.firstChild) node.removeChild(node.firstChild);
    }
    function setText(id, value) {
      $(id).textContent = value == null || value === '' ? '-' : String(value);
    }
    function fmtDate(value) {
      if (!value) return '-';
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(localeTag());
    }
    function fmtDuration(ms) {
      return ms == null ? '-' : (ms / 1000).toFixed(1) + ' s';
    }
    function fmtNumber(value) {
      return Number(value || 0).toLocaleString(localeTag());
    }
    function statusClass(value) {
      return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9äöüß_-]+/g, '-');
    }
    function status(value) {
      const span = document.createElement('span');
      span.className = 'status ' + statusClass(value);
      span.textContent = value || t('status.unknown');
      return span;
    }
    function longText(value, options = {}) {
      const text = value == null || value === '' ? '-' : String(value);
      const threshold = options.threshold || 72;
      const lines = options.lines || 2;
      const wrapper = document.createElement('div');
      wrapper.className = 'long-text';
      wrapper.style.setProperty('--cell-lines', String(lines));
      const preview = document.createElement('span');
      preview.className = 'long-text-preview';
      preview.textContent = text;
      wrapper.appendChild(preview);
      if (text.length > threshold || text.includes('\n')) {
        const id = 'cell-disclosure-' + (++disclosureId);
        preview.id = id;
        wrapper.classList.add('is-collapsible');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'cell-toggle';
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-controls', id);
        button.textContent = options.moreLabel || t('action.more');
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          const expanded = !wrapper.classList.contains('is-expanded');
          wrapper.classList.toggle('is-expanded', expanded);
          button.setAttribute('aria-expanded', String(expanded));
          button.textContent = expanded ? (options.lessLabel || t('action.less')) : (options.moreLabel || t('action.more'));
        });
        wrapper.appendChild(button);
      }
      return wrapper;
    }
    function compactText(value, options = {}) {
      return [longText(value, options), options.className || 'long-cell'];
    }
    function cell(row, value, className) {
      const td = document.createElement('td');
      if (className) td.className = className;
      if (value instanceof Node) td.appendChild(value); else td.textContent = value ?? '';
      row.appendChild(td);
    }
    function table(id, headers, rows, onClick) {
      const target = $(id);
      const tableWrap = target.closest('.table-wrap');
      if (tableWrap) tableWrap.setAttribute('aria-busy', 'false');
      clear(target);
      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');
      headers.forEach((header) => {
        const th = document.createElement('th');
        th.textContent = header;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      target.appendChild(thead);
      const tbody = document.createElement('tbody');
      if (!rows.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = headers.length;
        td.className = 'empty';
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const title = document.createElement('strong');
        title.textContent = t('empty.title');
        const hint = document.createElement('span');
        hint.textContent = t('empty.hint');
        empty.append(title, hint);
        td.appendChild(empty);
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
      rows.forEach((item) => {
        const tr = document.createElement('tr');
        if (onClick) {
          tr.className = 'clickable';
          tr.tabIndex = 0;
          tr.addEventListener('click', () => onClick(item));
          tr.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') onClick(item);
          });
        }
        item.__cells.forEach((entry) => {
          if (Array.isArray(entry)) cell(tr, entry[0], entry[1]); else cell(tr, entry);
        });
        tbody.appendChild(tr);
      });
      target.appendChild(tbody);
    }
    function metric(label, value, sub, tone) {
      const node = document.createElement('div');
      node.className = 'metric ' + (tone || '');
      const labelNode = document.createElement('div');
      labelNode.className = 'metric-label';
      labelNode.textContent = label;
      const valueNode = document.createElement('div');
      valueNode.className = 'metric-value';
      valueNode.textContent = value ?? '0';
      const subNode = document.createElement('div');
      subNode.className = 'metric-sub';
      subNode.textContent = sub || '';
      node.append(labelNode, valueNode, subNode);
      return node;
    }
    function renderPager(id, page, setPage) {
      const node = $(id);
      clear(node);
      const start = page.total ? page.offset + 1 : 0;
      const end = Math.min(page.offset + page.items.length, page.total);
      const label = document.createElement('span');
      label.textContent = start + '-' + end + ' ' + t('pager.of') + ' ' + page.total;
      const previous = document.createElement('button');
      previous.type = 'button';
      previous.textContent = t('pager.previous');
      previous.disabled = page.offset <= 0;
      previous.addEventListener('click', () => setPage(-1));
      const next = document.createElement('button');
      next.type = 'button';
      next.textContent = t('pager.next');
      next.disabled = !page.has_next;
      next.addEventListener('click', () => setPage(1));
      node.append(label, previous, next);
    }
    function renderHealthRail(statusData) {
      const node = $('health-rail');
      clear(node);
      const counts = [
        statusData.running_jobs || 0,
        statusData.queued_or_retrying_jobs || 0,
        statusData.objects_processed || 0,
        statusData.changes_detected || 0,
        statusData.warnings_count || 0,
        statusData.errors_count || 0,
        statusData.failed_jobs || 0,
        statusData.uptime_seconds || 0
      ];
      const max = Math.max(...counts, 1);
      counts.forEach((value, index) => {
        const bar = document.createElement('div');
        bar.className = 'rail-bar' + (index >= 5 && value ? ' bad' : index === 4 && value ? ' warn' : '');
        bar.style.height = Math.max(10, Math.round((value / max) * 62)) + 'px';
        node.appendChild(bar);
      });
    }
    function renderProblems(errors, warnings) {
      const node = $('problems');
      clear(node);
      const items = [...errors.items, ...warnings.items].slice(0, 8);
      setText('problem-count', items.length + ' ' + t('counts.entries'));
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = t('problems.none');
        node.appendChild(empty);
        return;
      }
      items.forEach((item) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'problem-item';
        const title = document.createElement('strong');
        title.append(status(item.level));
        const message = document.createElement('span');
        message.textContent = item.message || '-';
        const meta = document.createElement('span');
        meta.textContent = fmtDate(item.occurred_at) + ' · ' + (item.component || '-');
        wrapper.append(title, message, meta);
        node.appendChild(wrapper);
      });
    }
    function renderDependencyHealth(health) {
      const node = $('dependency-health');
      clear(node);
      const summary = health.summary || { ok: 0, warning: 0, error: 0 };
      setText('health-summary', (health.status || t('status.unknown')) + ' · ' + summary.ok + ' ok / ' + summary.warning + ' warn / ' + summary.error + ' error');
      (health.checks || []).forEach((check) => {
        const item = document.createElement('div');
        item.className = 'health-item ' + statusClass(check.status);
        const led = document.createElement('div');
        led.className = 'health-led';
        const copy = document.createElement('div');
        const name = document.createElement('div');
        name.className = 'health-name';
        name.textContent = check.label || check.name || 'Check';
        const message = document.createElement('div');
        message.className = 'health-message';
        message.textContent = check.message || '-';
        copy.append(name, message);
        if (check.transport || check.scheme || check.endpoint) {
          const transport = check.transport || {};
          const scheme = String(transport.scheme || check.scheme || 'unknown').toLowerCase();
          const transportNode = document.createElement('div');
          transportNode.className = 'health-transport';
          const badge = document.createElement('span');
          badge.className = 'transport-badge ' + statusClass(scheme);
          badge.textContent = scheme || 'unknown';
          const detail = document.createElement('span');
          const encrypted = (transport.encrypted ?? check.encrypted) ? t('health.encrypted') : t('health.unencrypted');
          const endpoint = transport.selected_url || check.endpoint || '-';
          const fallback = transport.fallback_used ? ' · ' + t('health.fallback') : '';
          detail.textContent = encrypted + ' · ' + endpoint + fallback;
          transportNode.append(badge, detail);
          copy.appendChild(transportNode);
        }
        const latency = document.createElement('div');
        latency.className = 'health-latency';
        latency.textContent = check.latency_ms == null ? '-' : check.latency_ms + ' ms';
        item.append(led, copy, latency);
        node.appendChild(item);
      });
      if (!node.childNodes.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = t('health.none');
        node.appendChild(empty);
      }
    }
    async function loadOverview() {
      const [statusData, metricsData, syncs, changes, errors, warnings, health] = await Promise.all([
        api('/api/status'),
        api('/api/metrics'),
        api('/api/sync-runs?limit=6'),
        api('/api/changes?limit=6'),
        api('/api/logs?level=error&limit=4'),
        api('/api/logs?level=warning&limit=4'),
        api('/api/health')
      ]);
      setText('state-value', statusData.state);
      clear($('state-pill'));
      $('state-pill').appendChild(status(statusData.state));
      setText('started-at', t('table.start') + ': ' + fmtDate(statusData.started_at));
      setText('last-success', (currentLanguage === 'de' ? 'Letzter Erfolg' : 'Last success') + ': ' + fmtDate(statusData.last_successful_sync && statusData.last_successful_sync.ended_at));
      setText('last-failure', (currentLanguage === 'de' ? 'Letzter Fehler' : 'Last error') + ': ' + fmtDate(statusData.last_failed_sync && statusData.last_failed_sync.ended_at));
      setText('sidebar-state', t('table.status') + ': ' + (statusData.state || t('status.unknown')));
      setText('sidebar-updated', (currentLanguage === 'de' ? 'Aktualisiert' : 'Updated') + ': ' + new Date().toLocaleTimeString(localeTag()));
      renderHealthRail(statusData);
      renderDependencyHealth(health);
      const grid = $('metrics');
      clear(grid);
      grid.append(
        metric(t('metric.libraries'), fmtNumber(metricsData.libraries), currentLanguage === 'de' ? 'Seafile-Quellen' : 'Seafile sources', 'info'),
        metric(t('metric.files'), fmtNumber(metricsData.files), currentLanguage === 'de' ? 'bekannter State' : 'known state'),
        metric(t('metric.syncRuns'), fmtNumber(metricsData.sync_runs), currentLanguage === 'de' ? 'persistierte Historie' : 'persisted history'),
        metric(t('metric.changes'), fmtNumber(statusData.changes_detected), currentLanguage === 'de' ? 'erkannte Events' : 'detected events', 'info'),
        metric(t('metric.checked'), fmtNumber(statusData.objects_processed), currentLanguage === 'de' ? 'Summe aller Läufe' : 'sum across all runs'),
        metric(t('metric.queue'), fmtNumber(statusData.queued_or_retrying_jobs), currentLanguage === 'de' ? 'wartende Jobs' : 'waiting jobs', 'warn'),
        metric(t('metric.warnings'), fmtNumber(statusData.warnings_count), 'Log-Level warning', 'warn'),
        metric(t('metric.errors'), fmtNumber(statusData.errors_count), 'Log-Level error', statusData.errors_count ? 'bad' : '')
      );
      renderProblems(errors, warnings);
      setText('recent-sync-count', syncs.items.length);
      table('recent-syncs', [t('table.start'), t('table.status'), t('table.source'), t('table.target'), t('table.objects')], syncs.items.map((run) => ({
        ...run,
        __cells: [fmtDate(run.started_at), status(run.status), compactText(run.source, { threshold: 40 }), compactText(run.target, { threshold: 40 }), fmtNumber(run.objects_checked)]
      })), (run) => openSyncDetail(run.sync_id));
      setText('recent-change-count', changes.items.length);
      table('recent-changes', [t('table.time'), t('table.type'), t('table.status'), 'Objekt', t('table.target')], changes.items.map((change) => ({
        ...change,
        __cells: [fmtDate(change.occurred_at), change.change_type, status(change.status), compactText(change.object_name, { threshold: 36 }), compactText(change.target_path, { threshold: 44 })]
      })));
    }
    async function loadSyncs() {
      const statusValue = $('sync-status').value;
      const offset = state.pages.syncs * PAGE_SIZE;
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (statusValue) params.set('status', statusValue);
      const data = await api('/api/sync-runs?' + params.toString());
      setText('sync-total', fmtNumber(data.total) + ' ' + t('counts.runs'));
      table('sync-table', ['Sync-ID', t('table.start'), t('table.duration'), t('table.status'), currentLanguage === 'de' ? 'Geprüft' : 'Checked', t('table.new'), t('table.updated'), t('table.deleted'), t('table.skipped')], data.items.map((run) => ({
        ...run,
        __cells: [compactText(run.sync_id, { threshold: 34 }), fmtDate(run.started_at), fmtDuration(run.duration_ms), status(run.status), fmtNumber(run.objects_checked), fmtNumber(run.objects_created), fmtNumber(run.objects_updated), fmtNumber(run.objects_deleted), fmtNumber(run.objects_skipped)]
      })), (run) => openSyncDetail(run.sync_id, false));
      renderPager('sync-pager', data, (delta) => { state.pages.syncs = Math.max(0, state.pages.syncs + delta); loadSyncs(); });
    }
    async function openSyncDetail(syncId, switchTab = true) {
      if (switchTab && state.activeTab !== 'syncs') {
        activateTab('syncs');
      }
      const data = await api('/api/sync-runs/' + encodeURIComponent(syncId));
      const node = $('sync-detail');
      clear(node);
      const panel = document.createElement('div');
      panel.className = 'panel';
      const header = document.createElement('div');
      header.className = 'panel-header';
      const title = document.createElement('h3');
      title.textContent = (currentLanguage === 'en' ? 'Detail ' : 'Detail ') + syncId;
      const small = document.createElement('small');
      small.appendChild(status(data.status));
      header.append(title, small);
      const body = document.createElement('div');
      body.className = 'panel-body';
      const pills = document.createElement('div');
      pills.className = 'pill-row';
      [
        t('table.source') + ': ' + (data.source || '-'),
        t('table.target') + ': ' + (data.target || '-'),
        t('table.duration') + ': ' + fmtDuration(data.duration_ms),
        t('metric.changes') + ': ' + (data.changes || []).length,
        'Logs: ' + (data.logs || []).length
      ].forEach((item) => {
        const pill = document.createElement('span');
        pill.className = 'mini-pill';
        pill.textContent = item;
        pills.appendChild(pill);
      });
      const pre = document.createElement('pre');
      pre.className = 'detail';
      pre.textContent = JSON.stringify(data, null, 2);
      body.append(pills, pre);
      panel.append(header, body);
      node.appendChild(panel);
    }
    async function loadChanges() {
      const offset = state.pages.changes * PAGE_SIZE;
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      [['sync_id','change-sync'], ['status','change-status'], ['change_type','change-type'], ['q','change-query']].forEach(([key, id]) => {
        if ($(id).value) params.set(key, $(id).value);
      });
      const data = await api('/api/changes?' + params.toString());
      setText('change-total', fmtNumber(data.total) + ' ' + t('counts.events'));
      table('change-table', [t('table.time'), 'Sync-ID', t('table.action'), t('table.type'), t('table.status'), 'Objekt', t('table.source'), t('table.target'), t('table.error')], data.items.map((change) => ({
        ...change,
        __cells: [
          fmtDate(change.occurred_at),
          compactText(change.sync_id, { threshold: 34 }),
          change.action,
          change.change_type,
          status(change.status),
          compactText(change.object_name, { threshold: 42 }),
          compactText(change.source_path, { threshold: 48 }),
          compactText(change.target_path, { threshold: 48 }),
          compactText(change.error_message, { threshold: 48 })
        ]
      })));
      renderPager('change-pager', data, (delta) => { state.pages.changes = Math.max(0, state.pages.changes + delta); loadChanges(); });
    }
    async function loadLogs() {
      const offset = state.pages.logs * PAGE_SIZE;
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if ($('log-level').value) params.set('level', $('log-level').value);
      if ($('log-sync').value) params.set('sync_id', $('log-sync').value);
      if ($('log-query').value) params.set('q', $('log-query').value);
      const data = await api('/api/logs?' + params.toString());
      setText('log-total', fmtNumber(data.total) + ' Logs');
      table('log-table', [t('table.time'), 'Level', currentLanguage === 'de' ? 'Komponente' : 'Component', 'Sync-ID', t('table.message')], data.items.map((entry) => ({
        ...entry,
        __cells: [
          fmtDate(entry.occurred_at),
          status(entry.level),
          compactText(entry.component, { threshold: 34 }),
          compactText(entry.sync_id, { threshold: 34 }),
          compactText(entry.message, { threshold: 86, lines: 3, className: 'message-cell long-cell' })
        ]
      })), (entry) => {
        const detail = $('log-detail');
        detail.hidden = false;
        detail.textContent = JSON.stringify(entry, null, 2);
      });
      renderPager('log-pager', data, (delta) => { state.pages.logs = Math.max(0, state.pages.logs + delta); loadLogs(); });
    }
    async function loadSystems() {
      const data = await api('/api/systems');
      table('source-table', ['Repo-ID', 'Name', t('table.status'), 'Head Commit', currentLanguage === 'de' ? 'Letzter Sync' : 'Last sync', t('table.error')], (data.source.libraries || []).map((library) => ({
        ...library,
        __cells: [compactText(library.repo_id, { threshold: 34 }), compactText(library.name, { threshold: 38 }), status(library.status), compactText(library.head_commit_id, { threshold: 34 }), compactText(library.last_synced_commit_id, { threshold: 34 }), compactText(library.last_error, { threshold: 48 })]
      })));
      table('target-table', ['Repo-ID', 'Dataset-ID', 'Dataset-Name', 'Template Hash'], (data.target.datasets || []).map((dataset) => ({
        ...dataset,
        __cells: [compactText(dataset.repo_id, { threshold: 34 }), compactText(dataset.dataset_id, { threshold: 34 }), compactText(dataset.dataset_name, { threshold: 48 }), compactText(dataset.template_hash, { threshold: 34 })]
      })));
    }
    async function loadOpenWebUI() {
      const offset = state.pages.openwebui * PAGE_SIZE;
      const [statusData, mappings, capabilities, dryRun] = await Promise.all([
        api('/api/openwebui/status'),
        api('/api/openwebui/mappings?limit=' + PAGE_SIZE + '&offset=' + offset),
        api('/api/openwebui/capabilities'),
        api('/api/openwebui/dry-run')
      ]);
      const counts = statusData.counts || {};
      setText('openwebui-summary', (statusData.status || 'disabled') + ' · ' + (statusData.mode || 'disabled'));
      const grid = $('openwebui-metrics');
      clear(grid);
      grid.append(
        metric('Integration', statusData.enabled ? t('openwebui.active') : t('openwebui.off'), statusData.base_url || '-', statusData.enabled ? 'info' : ''),
        metric('Datasets', fmtNumber(counts.datasets), currentLanguage === 'de' ? 'erkannte Mappings' : 'known mappings'),
        metric(currentLanguage === 'de' ? 'Synchronisiert' : 'Synchronized', fmtNumber(counts.synced_or_planned), currentLanguage === 'de' ? 'inkl. Dry-Run geplant' : 'including dry-run planned', counts.failed ? '' : 'info'),
        metric(t('table.deleted'), fmtNumber(counts.deleted), currentLanguage === 'de' ? 'Seafile-Library entfernt' : 'Seafile library removed', counts.deleted ? 'warn' : ''),
        metric(currentLanguage === 'de' ? 'Manuell' : 'Manual', fmtNumber(counts.manual_required), 'API-Fallback', counts.manual_required ? 'warn' : ''),
        metric(t('metric.errors'), fmtNumber(counts.failed), statusData.last_error || (currentLanguage === 'de' ? 'keine' : 'none'), counts.failed ? 'bad' : '')
      );
      table('openwebui-table', ['Dataset', t('table.status'), 'Chat', 'Tool', 'Pipe', currentLanguage === 'de' ? 'Modell' : 'Model', currentLanguage === 'de' ? 'Letzter Erfolg' : 'Last success', t('table.error')], (mappings.items || []).map((item) => ({
        ...item,
        __cells: [
          compactText(item.ragflow_dataset_name, { threshold: 42 }),
          status(item.sync_status),
          compactText(item.ragflow_chat_id, { threshold: 34 }),
          compactText(item.openwebui_tool_id, { threshold: 34 }),
          compactText(item.openwebui_pipe_id, { threshold: 34 }),
          compactText(item.openwebui_model_name, { threshold: 42 }),
          fmtDate(item.last_successful_sync_at),
          compactText(item.last_error, { threshold: 56 })
        ]
      })));
      renderPager('openwebui-pager', mappings, (delta) => { state.pages.openwebui = Math.max(0, state.pages.openwebui + delta); loadOpenWebUI(); });
      $('openwebui-detail').textContent = JSON.stringify({ status: statusData, capabilities, dry_run: dryRun }, null, 2);
    }
    async function loadDiagnostics() {
      $('diagnostics-json').textContent = JSON.stringify(await api('/api/diagnostics'), null, 2);
    }
    async function loadActive() {
      if (state.loading) {
        state.pendingLoad = true;
        return;
      }
      state.loading = true;
      showError('');
      const workspace = document.querySelector('.workspace');
      workspace.classList.add('is-refreshing');
      workspace.setAttribute('aria-busy', 'true');
      document.querySelectorAll('section:not([hidden]) .table-wrap').forEach((node) => node.setAttribute('aria-busy', 'true'));
      try {
        if (state.activeTab === 'overview') await loadOverview();
        if (state.activeTab === 'syncs') await loadSyncs();
        if (state.activeTab === 'changes') await loadChanges();
        if (state.activeTab === 'logs') await loadLogs();
        if (state.activeTab === 'systems') await loadSystems();
        if (state.activeTab === 'openwebui') await loadOpenWebUI();
        if (state.activeTab === 'diagnostics') await loadDiagnostics();
      } catch (err) {
        showError(err.message || String(err));
      } finally {
        state.loading = false;
        workspace.setAttribute('aria-busy', 'false');
        window.setTimeout(() => workspace.classList.remove('is-refreshing'), 240);
        if (state.pendingLoad) {
          state.pendingLoad = false;
          loadActive();
        }
      }
    }
    function activateTab(name) {
      document.querySelectorAll('.tab').forEach((button) => {
        button.setAttribute('aria-selected', String(button.dataset.tab === name));
      });
      document.querySelectorAll('main > section').forEach((section) => { section.hidden = true; });
      state.activeTab = name;
      $(name).hidden = false;
      const title = state.titles[name] || [name, ''];
      setText('view-title', title[0]);
      setText('view-subtitle', title[1]);
      loadActive();
    }
    function initThemeToggle() {
      const button = $('theme-toggle');
      const update = () => {
        const theme = document.documentElement.dataset.theme || 'dark';
        button.setAttribute('aria-pressed', String(theme === 'dark'));
        button.lastChild.textContent = theme === 'dark' ? 'Dark' : 'Light';
      };
      button.addEventListener('click', () => {
        const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('connector-dashboard-theme', next);
        update();
      });
      update();
    }
    function initLanguageSelect() {
      const select = $('language-select');
      select.value = currentLanguage;
      select.addEventListener('change', () => {
        currentLanguage = normalizeLanguage(select.value) || 'de';
        localStorage.setItem('connector-dashboard-language', currentLanguage);
        applyLanguage();
        loadActive();
      });
    }
    function initAutoRefresh() {
      const select = $('refresh-interval');
      const wrapper = select.closest('.refresh-control');
      const apply = () => {
        state.refreshMs = Number(select.value || 0);
        localStorage.setItem('connector-dashboard-refresh-ms', String(state.refreshMs));
        if (state.refreshTimer) {
          clearInterval(state.refreshTimer);
          state.refreshTimer = null;
        }
        wrapper.classList.toggle('is-active', state.refreshMs > 0);
        wrapper.style.setProperty('--refresh-ms', state.refreshMs + 'ms');
        if (state.refreshMs > 0) {
          state.refreshTimer = setInterval(loadActive, state.refreshMs);
        }
      };
      if (![0, 5000, 10000, 60000].includes(state.refreshMs)) {
        state.refreshMs = 10000;
      }
      select.value = String(state.refreshMs);
      select.addEventListener('change', apply);
      apply();
    }
    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => activateTab(button.dataset.tab));
    });
    $('refresh-active').addEventListener('click', loadActive);
    $('sync-refresh').addEventListener('click', () => { state.pages.syncs = 0; loadSyncs(); });
    $('change-refresh').addEventListener('click', () => { state.pages.changes = 0; loadChanges(); });
    $('log-refresh').addEventListener('click', () => { state.pages.logs = 0; loadLogs(); });
    initLanguageSelect();
    applyLanguage();
    initThemeToggle();
    initAutoRefresh();
    loadActive();
  </script>
</body>
</html>
"""
