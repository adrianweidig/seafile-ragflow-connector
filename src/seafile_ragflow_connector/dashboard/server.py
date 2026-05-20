from __future__ import annotations

# ruff: noqa: E501
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore
from seafile_ragflow_connector.utils.redaction import redact_mapping


class DashboardBindError(RuntimeError):
    pass


@dataclass
class DashboardServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@dataclass(frozen=True)
class DashboardContext:
    store: DashboardEventStore
    settings: Settings
    started_at: datetime


def start_dashboard_server(context: DashboardContext, *, background: bool = True) -> DashboardServerHandle:
    handler_class = _build_handler(context)
    try:
        server = ThreadingHTTPServer(
            (context.settings.connector_dashboard_host, context.settings.connector_dashboard_port),
            handler_class,
        )
    except OSError as exc:
        raise DashboardBindError(
            "dashboard port could not be bound: "
            f"{context.settings.connector_dashboard_host}:{context.settings.connector_dashboard_port}: {exc}"
        ) from exc
    thread = threading.Thread(target=server.serve_forever, name="connector-dashboard", daemon=True)
    if background:
        thread.start()
    return DashboardServerHandle(server=server, thread=thread)


def serve_dashboard_forever(context: DashboardContext) -> None:
    handle = start_dashboard_server(context, background=False)
    structlog.get_logger(__name__).info(
        "dashboard.started",
        host=context.settings.connector_dashboard_host,
        port=context.settings.connector_dashboard_port,
    )
    try:
        handle.server.serve_forever()
    finally:
        handle.server.server_close()


def _build_handler(context: DashboardContext):
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "SeafileRAGFlowConnectorDashboard/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path in {"/", "/dashboard"}:
                    self._send_html(DASHBOARD_HTML)
                    return
                if parsed.path == "/api/health":
                    self._send_json({"status": "ok", "dashboard_enabled": True})
                    return
                if parsed.path == "/api/status":
                    self._send_json(context.store.connector_status(started_at=context.started_at))
                    return
                if parsed.path == "/api/metrics":
                    self._send_json(context.store.metrics())
                    return
                if parsed.path == "/api/systems":
                    self._send_json(context.store.systems())
                    return
                if parsed.path == "/api/sync-runs":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_sync_runs(
                            status=_one(params, "status"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path.startswith("/api/sync-runs/"):
                    sync_id = parsed.path.rsplit("/", 1)[-1]
                    item = context.store.get_sync_run(sync_id)
                    if item is None:
                        self._send_json({"error": "sync run not found"}, status=HTTPStatus.NOT_FOUND)
                    else:
                        self._send_json(item)
                    return
                if parsed.path == "/api/changes":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_changes(
                            sync_id=_one(params, "sync_id"),
                            status=_one(params, "status"),
                            change_type=_one(params, "change_type"),
                            query=_one(params, "q"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path == "/api/logs":
                    params = parse_qs(parsed.query)
                    self._send_json(
                        context.store.list_logs(
                            level=_one(params, "level"),
                            sync_id=_one(params, "sync_id"),
                            query=_one(params, "q"),
                            limit=_int(params, "limit"),
                            offset=_int(params, "offset"),
                        )
                    )
                    return
                if parsed.path == "/api/diagnostics":
                    self._send_json(context.store.diagnostics(_safe_config(context.settings)))
                    return
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                structlog.get_logger(__name__).warning("dashboard.request_failed", path=parsed.path, error=str(exc))
                self._send_json(
                    {"error": "dashboard request failed", "message": "Die Daten konnten nicht geladen werden."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, format: str, *args: Any) -> None:
            structlog.get_logger(__name__).debug("dashboard.http_access", message=format % args)

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardRequestHandler


def _one(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _int(params: dict[str, list[str]], key: str) -> int | None:
    value = _one(params, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_config(settings: Settings) -> dict[str, Any]:
    safe = {
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "log_format": settings.log_format,
        "dry_run": settings.dry_run,
        "seafile_base_url": settings.seafile_base_url,
        "seafile_skip_encrypted_libraries": settings.seafile_skip_encrypted_libraries,
        "seafile_skip_virtual_repos": settings.seafile_skip_virtual_repos,
        "ragflow_base_url": settings.ragflow_base_url,
        "ragflow_template_dataset_name": settings.ragflow_template_dataset_name,
        "ragflow_refresh_dataset_settings": settings.ragflow_refresh_dataset_settings,
        "postgres_host": settings.postgres_host,
        "postgres_port": settings.postgres_port,
        "postgres_db": settings.postgres_db,
        "redis_host": settings.redis_host,
        "redis_port": settings.redis_port,
        "redis_db": settings.redis_db,
        "allow_unknown_text_files": settings.allow_unknown_text_files,
        "deny_extensions": settings.deny_extensions,
        "text_extensions": settings.text_extensions,
        "default_text_ingestion_strategy": settings.default_text_ingestion_strategy,
        "discovery_interval_seconds": settings.discovery_interval_seconds,
        "delta_sync_interval_seconds": settings.delta_sync_interval_seconds,
        "reconcile_interval_seconds": settings.reconcile_interval_seconds,
        "delete_ragflow_docs_on_seafile_delete": settings.delete_ragflow_docs_on_seafile_delete,
        "connector_dashboard_enabled": settings.connector_dashboard_enabled,
        "connector_dashboard_host": settings.connector_dashboard_host,
        "connector_dashboard_port": settings.connector_dashboard_port,
        "connector_dashboard_max_log_entries": settings.connector_dashboard_max_log_entries,
        "connector_dashboard_max_event_entries": settings.connector_dashboard_max_event_entries,
        "connector_dashboard_max_sync_runs": settings.connector_dashboard_max_sync_runs,
        "connector_dashboard_log_page_size": settings.connector_dashboard_log_page_size,
    }
    return dict(redact_mapping(safe))


DASHBOARD_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Seafile RAGFlow Connector Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-muted: #eef1f4;
      --text: #16202a;
      --muted: #637083;
      --border: #d9dee7;
      --accent: #0f6cbd;
      --ok: #107c41;
      --warn: #986f0b;
      --bad: #c42b1c;
      --unknown: #5c6470;
      --shadow: 0 8px 24px rgba(22, 32, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }
    header {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    header h1 { margin: 0; font-size: 20px; font-weight: 650; }
    header p { margin: 4px 0 0; color: var(--muted); }
    main { padding: 20px 24px 32px; max-width: 1600px; margin: 0 auto; }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
    .tab {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      border-radius: 6px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
    }
    .tab[aria-selected="true"] { border-color: var(--accent); color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    section[hidden] { display: none; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric, .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric { padding: 14px; min-height: 88px; }
    .metric .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; }
    .metric .value { margin-top: 8px; font-size: 24px; font-weight: 650; word-break: break-word; }
    .panel { margin-bottom: 16px; overflow: hidden; }
    .panel h2 { margin: 0; padding: 14px 16px; font-size: 16px; border-bottom: 1px solid var(--border); }
    .panel-body { padding: 14px 16px; }
    .filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-bottom: 12px; }
    label { display: grid; gap: 4px; color: var(--muted); font-size: 12px; }
    input, select, button {
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      min-height: 36px;
      padding: 7px 10px;
      font: inherit;
    }
    button { cursor: pointer; }
    button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    th, td { border-bottom: 1px solid var(--border); padding: 9px 10px; text-align: left; vertical-align: top; }
    th { background: var(--surface-muted); color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; }
    td { overflow-wrap: anywhere; }
    tr:hover td { background: #fafbfc; }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      border: 1px solid var(--border);
      color: var(--unknown);
      background: #f8f9fb;
    }
    .status.ok, .status.succeeded, .status.synced, .status.done { color: var(--ok); border-color: #b7dfc4; background: #eef8f1; }
    .status.warning, .status.retrying { color: var(--warn); border-color: #ecd99c; background: #fff8df; }
    .status.error, .status.failed, .status.dead { color: var(--bad); border-color: #f1b8b1; background: #fff1ef; }
    .detail {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #0f1720;
      color: #e6edf3;
      border-radius: 8px;
      padding: 12px;
      max-height: 360px;
      overflow: auto;
    }
    .empty { color: var(--muted); padding: 12px 0; }
    .error-box { color: var(--bad); background: #fff1ef; border: 1px solid #f1b8b1; border-radius: 8px; padding: 10px; margin-bottom: 12px; display: none; }
    .two-col { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
    @media (max-width: 760px) {
      header, main { padding-left: 12px; padding-right: 12px; }
      table { min-width: 760px; }
      .table-wrap { overflow-x: auto; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Seafile RAGFlow Connector Dashboard</h1>
    <p>Lesende Übersicht für Status, Sync-Läufe, Änderungen, Logs und Diagnose.</p>
  </header>
  <main>
    <div id="error" class="error-box" role="alert"></div>
    <nav class="tabs" aria-label="Dashboard Bereiche">
      <button class="tab" data-tab="overview" aria-selected="true">Übersicht</button>
      <button class="tab" data-tab="syncs" aria-selected="false">Synchronisationen</button>
      <button class="tab" data-tab="changes" aria-selected="false">Änderungen</button>
      <button class="tab" data-tab="logs" aria-selected="false">Logs</button>
      <button class="tab" data-tab="systems" aria-selected="false">Systeme</button>
      <button class="tab" data-tab="diagnostics" aria-selected="false">Diagnose</button>
    </nav>

    <section id="overview">
      <div class="metric-grid" id="metrics"></div>
      <div class="two-col">
        <div class="panel"><h2>Fehler und Warnungen</h2><div class="panel-body" id="problems"></div></div>
        <div class="panel"><h2>Letzte Synchronisationen</h2><div class="table-wrap"><table id="recent-syncs"></table></div></div>
      </div>
    </section>

    <section id="syncs" hidden>
      <div class="panel"><h2>Synchronisationshistorie</h2><div class="panel-body">
        <div class="filters">
          <label>Status <select id="sync-status"><option value="">Alle</option><option>succeeded</option><option>failed</option><option>running</option></select></label>
          <button class="primary" id="sync-refresh">Aktualisieren</button>
        </div>
        <div class="table-wrap"><table id="sync-table"></table></div>
        <div id="sync-detail" class="panel-body"></div>
      </div></div>
    </section>

    <section id="changes" hidden>
      <div class="panel"><h2>Erkannte Änderungen</h2><div class="panel-body">
        <div class="filters">
          <label>Sync-ID <input id="change-sync" placeholder="optional"></label>
          <label>Status <input id="change-status" placeholder="synced, failed, skipped"></label>
          <label>Typ <input id="change-type" placeholder="created, updated, deleted"></label>
          <label>Suche <input id="change-query" placeholder="Pfad, Name, Fehler"></label>
          <button class="primary" id="change-refresh">Filtern</button>
        </div>
        <div class="table-wrap"><table id="change-table"></table></div>
      </div></div>
    </section>

    <section id="logs" hidden>
      <div class="panel"><h2>Logs</h2><div class="panel-body">
        <div class="filters">
          <label>Level <select id="log-level"><option value="">Alle</option><option>debug</option><option>info</option><option>warning</option><option>error</option></select></label>
          <label>Sync-ID <input id="log-sync" placeholder="optional"></label>
          <label>Suche <input id="log-query" placeholder="Nachricht oder Komponente"></label>
          <button class="primary" id="log-refresh">Filtern</button>
        </div>
        <div class="table-wrap"><table id="log-table"></table></div>
        <div id="log-detail" class="detail" hidden></div>
      </div></div>
    </section>

    <section id="systems" hidden>
      <div class="two-col">
        <div class="panel"><h2>Quellen</h2><div class="table-wrap"><table id="source-table"></table></div></div>
        <div class="panel"><h2>Ziele</h2><div class="table-wrap"><table id="target-table"></table></div></div>
      </div>
    </section>

    <section id="diagnostics" hidden>
      <div class="panel"><h2>Technische Diagnose</h2><div class="panel-body"><pre id="diagnostics-json" class="detail"></pre></div></div>
    </section>
  </main>
  <script>
    const state = { activeTab: 'overview' };
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
    function status(value) {
      const span = document.createElement('span');
      span.className = 'status ' + String(value || 'unknown').toLowerCase();
      span.textContent = value || 'unbekannt';
      return span;
    }
    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
    function cell(row, value) {
      const td = document.createElement('td');
      if (value instanceof Node) td.appendChild(value); else td.textContent = value ?? '';
      row.appendChild(td);
    }
    function table(id, headers, rows, onClick) {
      const t = $(id); clear(t);
      const thead = document.createElement('thead'); const hr = document.createElement('tr');
      headers.forEach(h => { const th = document.createElement('th'); th.textContent = h; hr.appendChild(th); });
      thead.appendChild(hr); t.appendChild(thead);
      const tbody = document.createElement('tbody');
      if (!rows.length) {
        const tr = document.createElement('tr'); const td = document.createElement('td');
        td.colSpan = headers.length; td.className = 'empty'; td.textContent = 'Keine Einträge vorhanden.'; tr.appendChild(td); tbody.appendChild(tr);
      }
      rows.forEach(item => {
        const tr = document.createElement('tr');
        if (onClick) { tr.tabIndex = 0; tr.addEventListener('click', () => onClick(item)); tr.addEventListener('keydown', e => { if (e.key === 'Enter') onClick(item); }); }
        item.__cells.forEach(v => cell(tr, v));
        tbody.appendChild(tr);
      });
      t.appendChild(tbody);
    }
    function metric(label, value) {
      const node = document.createElement('div'); node.className = 'metric';
      const l = document.createElement('div'); l.className = 'label'; l.textContent = label;
      const v = document.createElement('div'); v.className = 'value'; v.textContent = value ?? '0';
      node.append(l, v); return node;
    }
    function fmtDate(value) { return value ? new Date(value).toLocaleString() : '-'; }
    function fmtDuration(ms) { return ms == null ? '-' : (ms / 1000).toFixed(1) + ' s'; }

    async function loadOverview() {
      const [statusData, syncs, logs] = await Promise.all([
        api('/api/status'),
        api('/api/sync-runs?limit=5'),
        api('/api/logs?level=error&limit=5')
      ]);
      const grid = $('metrics'); clear(grid);
      grid.append(
        metric('Zustand', statusData.state),
        metric('Laufzeit', Math.floor((statusData.uptime_seconds || 0) / 60) + ' min'),
        metric('Laufende Jobs', statusData.running_jobs || 0),
        metric('Geprüfte Objekte', statusData.objects_processed || 0),
        metric('Änderungen', statusData.changes_detected || 0),
        metric('Fehler/Warnungen', (statusData.errors_count || 0) + ' / ' + (statusData.warnings_count || 0))
      );
      const problems = $('problems'); clear(problems);
      if (!logs.items.length) { const e = document.createElement('div'); e.className = 'empty'; e.textContent = 'Keine aktuellen Fehler im Dashboard-Log.'; problems.appendChild(e); }
      logs.items.forEach(item => { const p = document.createElement('p'); p.textContent = fmtDate(item.occurred_at) + ' ' + item.message; problems.appendChild(p); });
      table('recent-syncs', ['Start', 'Status', 'Quelle', 'Ziel', 'Objekte'], syncs.items.map(s => ({...s, __cells: [fmtDate(s.started_at), status(s.status), s.source, s.target, s.objects_checked]})), showSyncDetail);
    }
    async function loadSyncs() {
      const statusValue = $('sync-status').value;
      const data = await api('/api/sync-runs?limit=100' + (statusValue ? '&status=' + encodeURIComponent(statusValue) : ''));
      table('sync-table', ['Sync-ID', 'Start', 'Dauer', 'Status', 'Geprüft', 'Neu', 'Aktualisiert', 'Gelöscht', 'Übersprungen'], data.items.map(s => ({...s, __cells: [s.sync_id, fmtDate(s.started_at), fmtDuration(s.duration_ms), status(s.status), s.objects_checked, s.objects_created, s.objects_updated, s.objects_deleted, s.objects_skipped]})), showSyncDetail);
    }
    async function showSyncDetail(run) {
      const data = await api('/api/sync-runs/' + encodeURIComponent(run.sync_id));
      const node = $('sync-detail'); clear(node);
      const pre = document.createElement('pre'); pre.className = 'detail';
      pre.textContent = JSON.stringify(data, null, 2); node.appendChild(pre);
    }
    async function loadChanges() {
      const params = new URLSearchParams({ limit: '100' });
      [['sync_id','change-sync'], ['status','change-status'], ['change_type','change-type'], ['q','change-query']].forEach(([key,id]) => { if ($(id).value) params.set(key, $(id).value); });
      const data = await api('/api/changes?' + params.toString());
      table('change-table', ['Zeit', 'Sync-ID', 'Aktion', 'Typ', 'Status', 'Objekt', 'Quelle', 'Ziel', 'Fehler'], data.items.map(c => ({...c, __cells: [fmtDate(c.occurred_at), c.sync_id, c.action, c.change_type, status(c.status), c.object_name, c.source_path, c.target_path, c.error_message]})));
    }
    async function loadLogs() {
      const params = new URLSearchParams({ limit: '100' });
      if ($('log-level').value) params.set('level', $('log-level').value);
      if ($('log-sync').value) params.set('sync_id', $('log-sync').value);
      if ($('log-query').value) params.set('q', $('log-query').value);
      const data = await api('/api/logs?' + params.toString());
      table('log-table', ['Zeit', 'Level', 'Komponente', 'Sync-ID', 'Nachricht'], data.items.map(l => ({...l, __cells: [fmtDate(l.occurred_at), status(l.level), l.component, l.sync_id, l.message]})), item => {
        const d = $('log-detail'); d.hidden = false; d.textContent = JSON.stringify(item, null, 2);
      });
    }
    async function loadSystems() {
      const data = await api('/api/systems');
      table('source-table', ['Repo-ID', 'Name', 'Status', 'Head Commit', 'Letzter Sync', 'Fehler'], (data.source.libraries || []).map(l => ({...l, __cells: [l.repo_id, l.name, status(l.status), l.head_commit_id, l.last_synced_commit_id, l.last_error]})));
      table('target-table', ['Repo-ID', 'Dataset-ID', 'Dataset-Name', 'Template Hash'], (data.target.datasets || []).map(d => ({...d, __cells: [d.repo_id, d.dataset_id, d.dataset_name, d.template_hash]})));
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
      } catch (err) { showError(err.message || String(err)); }
    }
    document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => b.setAttribute('aria-selected', 'false'));
      button.setAttribute('aria-selected', 'true');
      document.querySelectorAll('main > section').forEach(s => s.hidden = true);
      state.activeTab = button.dataset.tab;
      $(state.activeTab).hidden = false;
      loadActive();
    }));
    $('sync-refresh').addEventListener('click', loadSyncs);
    $('change-refresh').addEventListener('click', loadChanges);
    $('log-refresh').addEventListener('click', loadLogs);
    loadActive();
    setInterval(() => { if (state.activeTab === 'overview') loadOverview(); }, 30000);
  </script>
</body>
</html>
"""
