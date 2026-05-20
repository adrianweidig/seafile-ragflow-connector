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
      --text: #f4f7fb;
      --muted: #96a3b7;
      --soft: #cbd5e1;
      --border: rgba(148, 163, 184, 0.24);
      --border-strong: rgba(148, 163, 184, 0.42);
      --accent: #2dd4bf;
      --accent-2: #60a5fa;
      --accent-3: #f59e0b;
      --ok: #34d399;
      --warn: #fbbf24;
      --bad: #fb7185;
      --info: #38bdf8;
      --unknown: #94a3b8;
      --shadow: 0 24px 70px rgba(0, 0, 0, 0.32);
      --radius: 8px;
      --focus: 0 0 0 3px rgba(45, 212, 191, 0.28);
    }
    :root[data-theme="light"] {
      color-scheme: light;
      --bg: #eef2f7;
      --bg-2: #f8fafc;
      --surface: #ffffff;
      --surface-2: #f5f8fc;
      --surface-3: #eaf0f8;
      --text: #142033;
      --muted: #5b677a;
      --soft: #334155;
      --border: rgba(92, 108, 130, 0.22);
      --border-strong: rgba(92, 108, 130, 0.38);
      --accent: #0f766e;
      --accent-2: #2563eb;
      --accent-3: #b45309;
      --ok: #047857;
      --warn: #b45309;
      --bad: #be123c;
      --info: #0369a1;
      --unknown: #64748b;
      --shadow: 0 20px 60px rgba(15, 23, 42, 0.12);
      --focus: 0 0 0 3px rgba(15, 118, 110, 0.22);
    }
    * { box-sizing: border-box; }
    html { min-height: 100%; }
    body {
      margin: 0;
      min-height: 100%;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--bg-2) 88%, #000 12%), var(--bg) 38%),
        repeating-linear-gradient(90deg, transparent 0 38px, rgba(148, 163, 184, 0.05) 38px 39px);
      color: var(--text);
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
      letter-spacing: 0;
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
      min-height: 36px;
      padding: 8px 12px;
      text-decoration: none;
      transition: border-color 140ms ease, background 140ms ease, color 140ms ease, transform 140ms ease;
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
      min-height: 36px;
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
      background: color-mix(in srgb, var(--surface) 88%, transparent);
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
      width: 100%;
    }
    .tab .tab-dot {
      background: var(--border-strong);
      border-radius: 999px;
      height: 8px;
      width: 8px;
    }
    .tab[aria-selected="true"] {
      background: color-mix(in srgb, var(--accent) 14%, var(--surface));
      border-color: color-mix(in srgb, var(--accent) 56%, var(--border));
      color: var(--text);
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
      display: flex;
      gap: 14px;
      justify-content: space-between;
      margin-bottom: 18px;
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
    .action, .ghost {
      background: var(--surface);
      color: var(--text);
    }
    .primary {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-color: transparent;
      color: #041116;
      font-weight: 700;
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
      grid-template-columns: minmax(280px, 1.1fr) minmax(280px, 0.9fr);
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
    }
    .rail-bar.warn { background: linear-gradient(180deg, var(--accent-3), var(--warn)); }
    .rail-bar.bad { background: linear-gradient(180deg, var(--bad), #f43f5e); }
    .panel, .metric {
      background: color-mix(in srgb, var(--surface) 94%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-header {
      align-items: center;
      border-bottom: 1px solid var(--border);
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
      overflow: auto;
      width: 100%;
    }
    table {
      border-collapse: collapse;
      min-width: 840px;
      table-layout: fixed;
      width: 100%;
    }
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
    tbody tr {
      transition: background 120ms ease;
    }
    tbody tr:hover td, tbody tr:focus-within td {
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }
    td {
      color: var(--soft);
      overflow-wrap: anywhere;
    }
    tr.clickable { cursor: pointer; }
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
    .status.warning, .status.warn, .status.retrying, .status.skipped, .status.übersprungen {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 42%, var(--border));
      background: color-mix(in srgb, var(--warn) 10%, transparent);
    }
    .status.warning::before, .status.warn::before, .status.retrying::before, .status.skipped::before, .status.übersprungen::before {
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
    .problem-list {
      display: grid;
      gap: 10px;
    }
    .problem-item {
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
    .message-cell {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      overflow: hidden;
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
      .topbar { align-items: stretch; flex-direction: column; }
      .actions { justify-content: stretch; }
      .actions > * { flex: 1; }
      .nav { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: 1fr; }
      .state-value { font-size: 28px; }
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
        <button class="tab" data-tab="diagnostics" aria-selected="false"><span class="tab-dot"></span>Diagnose</button>
      </nav>
      <div class="sidebar-footer">
        <div id="sidebar-state">Lade Status...</div>
        <div id="sidebar-updated">Noch nicht aktualisiert</div>
      </div>
    </aside>
    <main class="workspace">
      <div class="topbar">
        <div class="topbar-title">
          <h2 id="view-title">Übersicht</h2>
          <p id="view-subtitle">Live-Zustand, Durchsatz und Auffälligkeiten</p>
        </div>
        <div class="actions">
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
    const state = {
      activeTab: 'overview',
      pages: { syncs: 0, changes: 0, logs: 0 },
      titles: {
        overview: ['Übersicht', 'Live-Zustand, Durchsatz und Auffälligkeiten'],
        syncs: ['Sync-Läufe', 'Historie, Laufzeiten und Ergebnisdetails'],
        changes: ['Änderungen', 'Aktionen mit Quelle, Ziel, Objekt und Status'],
        logs: ['Logs', 'Filterbare Debug- und Audit-Ereignisse'],
        systems: ['Systeme', 'Seafile-Libraries und RAGFlow-Datasets'],
        diagnostics: ['Diagnose', 'Technische Werte ohne Secrets']
      }
    };
    const $ = (id) => document.getElementById(id);

    function showError(message) {
      const node = $('error');
      node.textContent = message || '';
      node.style.display = message ? 'block' : 'none';
    }
    async function api(path) {
      const res = await fetch(path, { headers: { 'Accept': 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error || 'API-Fehler');
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
      return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
    }
    function fmtDuration(ms) {
      return ms == null ? '-' : (ms / 1000).toFixed(1) + ' s';
    }
    function fmtNumber(value) {
      return Number(value || 0).toLocaleString('de-DE');
    }
    function statusClass(value) {
      return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9äöüß_-]+/g, '-');
    }
    function status(value) {
      const span = document.createElement('span');
      span.className = 'status ' + statusClass(value);
      span.textContent = value || 'unbekannt';
      return span;
    }
    function cell(row, value, className) {
      const td = document.createElement('td');
      if (className) td.className = className;
      if (value instanceof Node) td.appendChild(value); else td.textContent = value ?? '';
      row.appendChild(td);
    }
    function table(id, headers, rows, onClick) {
      const target = $(id);
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
        td.textContent = 'Keine Einträge vorhanden.';
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
      label.textContent = start + '-' + end + ' von ' + page.total;
      const previous = document.createElement('button');
      previous.type = 'button';
      previous.textContent = 'Zurück';
      previous.disabled = page.offset <= 0;
      previous.addEventListener('click', () => setPage(-1));
      const next = document.createElement('button');
      next.type = 'button';
      next.textContent = 'Weiter';
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
      setText('problem-count', items.length + ' Einträge');
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'Keine aktuellen Fehler oder Warnungen.';
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
    async function loadOverview() {
      const [statusData, metricsData, syncs, changes, errors, warnings] = await Promise.all([
        api('/api/status'),
        api('/api/metrics'),
        api('/api/sync-runs?limit=6'),
        api('/api/changes?limit=6'),
        api('/api/logs?level=error&limit=4'),
        api('/api/logs?level=warning&limit=4')
      ]);
      setText('state-value', statusData.state);
      clear($('state-pill'));
      $('state-pill').appendChild(status(statusData.state));
      setText('started-at', 'Start: ' + fmtDate(statusData.started_at));
      setText('last-success', 'Letzter Erfolg: ' + fmtDate(statusData.last_successful_sync && statusData.last_successful_sync.ended_at));
      setText('last-failure', 'Letzter Fehler: ' + fmtDate(statusData.last_failed_sync && statusData.last_failed_sync.ended_at));
      setText('sidebar-state', 'Status: ' + (statusData.state || 'unbekannt'));
      setText('sidebar-updated', 'Aktualisiert: ' + new Date().toLocaleTimeString());
      renderHealthRail(statusData);
      const grid = $('metrics');
      clear(grid);
      grid.append(
        metric('Libraries', fmtNumber(metricsData.libraries), 'Seafile-Quellen', 'info'),
        metric('Dateien', fmtNumber(metricsData.files), 'bekannter State'),
        metric('Sync-Läufe', fmtNumber(metricsData.sync_runs), 'persistierte Historie'),
        metric('Änderungen', fmtNumber(statusData.changes_detected), 'erkannte Events', 'info'),
        metric('Objekte geprüft', fmtNumber(statusData.objects_processed), 'Summe aller Läufe'),
        metric('Queue/Retry', fmtNumber(statusData.queued_or_retrying_jobs), 'wartende Jobs', 'warn'),
        metric('Warnungen', fmtNumber(statusData.warnings_count), 'Log-Level warning', 'warn'),
        metric('Fehler', fmtNumber(statusData.errors_count), 'Log-Level error', statusData.errors_count ? 'bad' : '')
      );
      renderProblems(errors, warnings);
      setText('recent-sync-count', syncs.items.length);
      table('recent-syncs', ['Start', 'Status', 'Quelle', 'Ziel', 'Objekte'], syncs.items.map((run) => ({
        ...run,
        __cells: [fmtDate(run.started_at), status(run.status), run.source, run.target, fmtNumber(run.objects_checked)]
      })), (run) => openSyncDetail(run.sync_id));
      setText('recent-change-count', changes.items.length);
      table('recent-changes', ['Zeit', 'Typ', 'Status', 'Objekt', 'Ziel'], changes.items.map((change) => ({
        ...change,
        __cells: [fmtDate(change.occurred_at), change.change_type, status(change.status), change.object_name, change.target_path]
      })));
    }
    async function loadSyncs() {
      const statusValue = $('sync-status').value;
      const offset = state.pages.syncs * PAGE_SIZE;
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (statusValue) params.set('status', statusValue);
      const data = await api('/api/sync-runs?' + params.toString());
      setText('sync-total', fmtNumber(data.total) + ' Läufe');
      table('sync-table', ['Sync-ID', 'Start', 'Dauer', 'Status', 'Geprüft', 'Neu', 'Aktualisiert', 'Gelöscht', 'Übersprungen'], data.items.map((run) => ({
        ...run,
        __cells: [run.sync_id, fmtDate(run.started_at), fmtDuration(run.duration_ms), status(run.status), fmtNumber(run.objects_checked), fmtNumber(run.objects_created), fmtNumber(run.objects_updated), fmtNumber(run.objects_deleted), fmtNumber(run.objects_skipped)]
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
      title.textContent = 'Detail ' + syncId;
      const small = document.createElement('small');
      small.appendChild(status(data.status));
      header.append(title, small);
      const body = document.createElement('div');
      body.className = 'panel-body';
      const pills = document.createElement('div');
      pills.className = 'pill-row';
      [
        'Quelle: ' + (data.source || '-'),
        'Ziel: ' + (data.target || '-'),
        'Dauer: ' + fmtDuration(data.duration_ms),
        'Änderungen: ' + (data.changes || []).length,
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
      setText('change-total', fmtNumber(data.total) + ' Ereignisse');
      table('change-table', ['Zeit', 'Sync-ID', 'Aktion', 'Typ', 'Status', 'Objekt', 'Quelle', 'Ziel', 'Fehler'], data.items.map((change) => ({
        ...change,
        __cells: [fmtDate(change.occurred_at), change.sync_id, change.action, change.change_type, status(change.status), change.object_name, change.source_path, change.target_path, change.error_message]
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
      table('log-table', ['Zeit', 'Level', 'Komponente', 'Sync-ID', 'Nachricht'], data.items.map((entry) => ({
        ...entry,
        __cells: [fmtDate(entry.occurred_at), status(entry.level), entry.component, entry.sync_id, [entry.message, 'message-cell']]
      })), (entry) => {
        const detail = $('log-detail');
        detail.hidden = false;
        detail.textContent = JSON.stringify(entry, null, 2);
      });
      renderPager('log-pager', data, (delta) => { state.pages.logs = Math.max(0, state.pages.logs + delta); loadLogs(); });
    }
    async function loadSystems() {
      const data = await api('/api/systems');
      table('source-table', ['Repo-ID', 'Name', 'Status', 'Head Commit', 'Letzter Sync', 'Fehler'], (data.source.libraries || []).map((library) => ({
        ...library,
        __cells: [library.repo_id, library.name, status(library.status), library.head_commit_id, library.last_synced_commit_id, library.last_error]
      })));
      table('target-table', ['Repo-ID', 'Dataset-ID', 'Dataset-Name', 'Template Hash'], (data.target.datasets || []).map((dataset) => ({
        ...dataset,
        __cells: [dataset.repo_id, dataset.dataset_id, dataset.dataset_name, dataset.template_hash]
      })));
    }
    async function loadDiagnostics() {
      $('diagnostics-json').textContent = JSON.stringify(await api('/api/diagnostics'), null, 2);
    }
    async function loadActive() {
      showError('');
      try {
        if (state.activeTab === 'overview') await loadOverview();
        if (state.activeTab === 'syncs') await loadSyncs();
        if (state.activeTab === 'changes') await loadChanges();
        if (state.activeTab === 'logs') await loadLogs();
        if (state.activeTab === 'systems') await loadSystems();
        if (state.activeTab === 'diagnostics') await loadDiagnostics();
      } catch (err) {
        showError(err.message || String(err));
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
    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => activateTab(button.dataset.tab));
    });
    $('refresh-active').addEventListener('click', loadActive);
    $('sync-refresh').addEventListener('click', () => { state.pages.syncs = 0; loadSyncs(); });
    $('change-refresh').addEventListener('click', () => { state.pages.changes = 0; loadChanges(); });
    $('log-refresh').addEventListener('click', () => { state.pages.logs = 0; loadLogs(); });
    initThemeToggle();
    loadActive();
    setInterval(() => { if (state.activeTab === 'overview') loadOverview(); }, 30000);
  </script>
</body>
</html>
"""
