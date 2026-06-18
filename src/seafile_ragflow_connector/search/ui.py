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
      --shadow: 0 24px 70px rgba(0, 0, 0, .34);
      --focus: 0 0 0 3px rgba(45, 212, 191, .28);
    }
    * { box-sizing: border-box; }
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
      grid-template-columns: minmax(260px, 310px) minmax(0, 1fr) minmax(280px, 340px);
      gap: 18px;
      align-items: start;
    }
    .panel {
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
    .profile-search, .query-input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-2);
      color: var(--text);
      outline: none;
    }
    .profile-search { min-height: 38px; padding: 0 11px; font-size: .92rem; }
    .query-input { min-height: 62px; padding: 0 17px; font-size: 1.08rem; background: var(--surface); }
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
    .mini-button:disabled { opacity: .52; cursor: not-allowed; }
    .profile-list { padding: 10px; display: grid; gap: 7px; overflow: auto; }
    .profile-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 11px 10px;
      border: 1px solid transparent;
      border-radius: 8px;
      cursor: pointer;
    }
    .profile-row:hover { background: var(--surface-3); }
    .profile-row:has(input:checked) { background: var(--selected); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
    .profile-row input { width: 17px; height: 17px; margin-top: 3px; accent-color: var(--accent); }
    .profile-name { display: block; color: var(--strong); font-weight: 800; overflow-wrap: anywhere; }
    .profile-kind { display: block; margin-top: 2px; color: var(--muted); font-size: .82rem; }
    .search-panel { overflow: hidden; }
    .query-area { padding: 18px; display: grid; gap: 14px; border-bottom: 1px solid var(--border); background: var(--surface); }
    .query-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
    .primary {
      min-height: 62px;
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 0 22px;
      background: var(--accent);
      color: #fff;
      font-weight: 900;
    }
    .primary:hover { background: color-mix(in srgb, var(--accent) 82%, #000); border-color: color-mix(in srgb, var(--accent) 82%, #000); }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .segments { display: inline-grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface-2); }
    .segment { min-height: 40px; border: 0; padding: 0 14px; background: transparent; color: var(--muted); font-weight: 780; }
    .segment[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent-text); }
    .topk { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: .9rem; }
    .topk input { width: 72px; height: 38px; border: 1px solid var(--border); border-radius: 8px; padding: 0 9px; background: var(--surface-2); color: var(--text); }
    .state { padding: 15px 18px; border-bottom: 1px solid var(--border); color: var(--muted); background: var(--surface-2); }
    .state.loading { color: var(--accent-text); background: var(--accent-soft); }
    .state.success { color: var(--accent-text); background: var(--accent-soft); }
    .state.error { color: var(--danger); background: var(--danger-soft); }
    .answer {
      padding: 18px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, var(--surface), var(--surface-2));
      display: grid;
      gap: 13px;
    }
    .answer h2 { margin: 0; color: var(--strong); font-size: 1.08rem; }
    .answer-text { margin: 0; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 1.02rem; }
    .citation-strip { display: flex; flex-wrap: wrap; gap: 8px; }
    .citation-button {
      min-height: 34px;
      border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
      border-radius: 999px;
      padding: 5px 10px;
      background: var(--accent-soft);
      color: var(--accent-text);
      font-weight: 850;
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }
    .results { padding: 16px; display: grid; gap: 13px; }
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
    .snippet mark { background: #fff4b8; color: #172033; padding: 1px 3px; border-radius: 4px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
    html[data-theme="dark"] .snippet mark { background: #5b4b15; color: var(--strong); }
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
      padding: 11px;
      background: var(--surface);
      color: var(--text);
      display: grid;
      gap: 5px;
    }
    .source-card:hover, .source-card.is-active { border-color: var(--accent); background: var(--accent-soft); }
    .source-card strong { color: var(--strong); overflow-wrap: anywhere; }
    .source-card span { color: var(--muted); font-size: .84rem; overflow-wrap: anywhere; }
    .source-card p { margin: 2px 0 0; color: var(--text); font-size: .88rem; overflow-wrap: anywhere; }
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
    @media (max-width: 1180px) {
      main { grid-template-columns: minmax(250px, 300px) minmax(0, 1fr); }
      .sources-panel { position: static; grid-column: 1 / -1; max-height: none; }
      .source-rail { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); max-height: none; }
    }
    @media (max-width: 820px) {
      header { padding: 12px 16px; align-items: flex-start; }
      main { grid-template-columns: 1fr; padding: 16px; }
      .library-panel, .sources-panel { position: static; max-height: none; }
      .query-form { grid-template-columns: 1fr; }
      .primary { width: 100%; }
    }
    @media (max-width: 600px) {
      header { display: grid; }
      .header-actions, .theme-toggle { width: 100%; }
      .toolbar { display: grid; }
      .segments { width: 100%; }
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
            <span class="count-pill" id="selectionCount">0/0</span>
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
        <div class="query-area">
          <form class="query-form" id="queryForm">
            <input class="query-input" id="question" name="question" autocomplete="off" placeholder="Was möchtest du in deinen Bibliotheken wissen?" aria-label="Suchfrage">
            <button class="primary" type="submit"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.5 18a7.5 7.5 0 1 1 5.3-12.8A7.5 7.5 0 0 1 10.5 18Zm6-1.5 4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>Suchen</button>
          </form>
          <div class="toolbar">
            <div class="segments" role="group" aria-label="Suchmodus">
              <button class="segment" type="button" data-mode="retrieval" aria-pressed="true">Dokumente finden</button>
              <button class="segment" type="button" data-mode="chat" aria-pressed="false">Antwort mit Quellen</button>
            </div>
            <label class="topk">Treffer <input id="topK" type="number" min="1" max="20" value="8"></label>
          </div>
        </div>
        <div id="state" class="state" aria-live="polite">Wähle Bibliotheken aus und starte eine Suche.</div>
        <div id="answer" class="answer" hidden></div>
        <div id="results" class="results"></div>
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
  <script>
    const stateEl = document.getElementById('state');
    const resultsEl = document.getElementById('results');
    const answerEl = document.getElementById('answer');
    const profileListEl = document.getElementById('profileList');
    const profileSummaryEl = document.getElementById('profileSummary');
    const selectionCountEl = document.getElementById('selectionCount');
    const userLineEl = document.getElementById('userLine');
    const topKEl = document.getElementById('topK');
    const questionEl = document.getElementById('question');
    const sourceRailEl = document.getElementById('sourceRail');
    const sourceSummaryEl = document.getElementById('sourceSummary');
    const sourceCountEl = document.getElementById('sourceCount');
    const hoverEl = document.getElementById('sourceHover');
    let profiles = [];
    let mode = 'retrieval';
    let latestSources = [];

    function setState(text, kind = '') {
      stateEl.textContent = text;
      stateEl.className = 'state' + (kind ? ` ${kind}` : '');
      stateEl.hidden = false;
    }

    function selectedProfileIds() {
      return [...document.querySelectorAll('[data-profile-id]:checked')].map(item => item.value);
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
      answerEl.hidden = true;
      answerEl.innerHTML = '';
      resultsEl.innerHTML = '';
      renderSourceRail([]);
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
      setState(`Suche läuft in ${profile_ids.length} Bibliothek${profile_ids.length === 1 ? '' : 'en'} …`, 'loading');
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
        const denied = data.diagnostics && data.diagnostics.profiles_denied ? data.diagnostics.profiles_denied : 0;
        const allowed = data.diagnostics && data.diagnostics.profiles_allowed ? data.diagnostics.profiles_allowed : profile_ids.length;
        const resultText = `${results.length} Treffer aus ${allowed} Bibliothek${allowed === 1 ? '' : 'en'}.`;
        setState(denied ? `${resultText} ${denied} Bibliothek(en) wurden wegen fehlender Berechtigung ausgelassen.` : resultText, 'success');
      } catch (error) {
        setState(error.message || 'Suche fehlgeschlagen.', 'error');
      }
    }

    function renderAnswer(answer, sources = []) {
      const answerText = typeof answer === 'string' ? answer : (answer.text || '');
      const citations = typeof answer === 'object' && answer.citations ? answer.citations : sources.slice(0, 8).map(source => ({
        label: source.citation_label || source.source_id,
        source_id: source.source_id,
        document_name: source.document_name,
        preview_url: source.preview_url,
        open_url: source.open_url
      }));
      answerEl.hidden = false;
      answerEl.innerHTML = '';
      const title = document.createElement('h2');
      title.textContent = 'Antwort mit Quellen';
      const text = document.createElement('p');
      text.className = 'answer-text';
      text.textContent = answerText;
      answerEl.append(title, text);
      if (citations.length) {
        const strip = document.createElement('div');
        strip.className = 'citation-strip answer-sources';
        strip.setAttribute('aria-label', 'Zitierte Quellen');
        for (const citation of citations) {
          const source = sources.find(item => item.source_id === citation.source_id || item.citation_label === citation.label) || citation;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'citation-button answer-source-link';
          button.textContent = `${citation.label || source.source_id} · ${source.document_name || 'Quelle'}`;
          bindSourceInteractions(button, source);
          strip.appendChild(button);
        }
        answerEl.appendChild(strip);
      }
    }

    function renderResults(results, query) {
      resultsEl.innerHTML = '';
      if (!results.length) {
        resultsEl.innerHTML = '<div class="empty">Keine passenden Treffer in den ausgewählten Bibliotheken gefunden.</div>';
        return;
      }
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
            ${item.preview_url ? `<a class="secondary" href="${escapeAttr(item.preview_url)}" target="_blank" rel="noreferrer noopener" title="Vorschau im Evidence-Viewer öffnen">${iconEye()}Vorschau</a>` : '<span class="secondary" aria-disabled="true" title="Keine Vorschau verfügbar.">Vorschau</span>'}
            ${item.open_url ? `<a class="secondary" href="${escapeAttr(item.open_url)}" target="_blank" rel="noreferrer noopener" title="Originallink öffnen">${iconExternal()}${openLabel(item)}</a>` : '<span class="secondary" aria-disabled="true" title="Für diesen Treffer ist kein Originallink vorhanden.">Originallink</span>'}
          </div>`;
        bindSourceInteractions(card, item);
        resultsEl.appendChild(card);
      }
    }

    function renderSourceRail(sources) {
      sourceRailEl.innerHTML = '';
      sourceCountEl.textContent = String(sources.length);
      sourceSummaryEl.textContent = sources.length ? `${sources.length} Quellen aus den erlaubten Bibliotheken.` : 'Noch keine Treffer.';
      if (!sources.length) {
        sourceRailEl.innerHTML = '<div class="empty">Nach einer Suche erscheinen hier die wichtigsten Quellen mit Vorschau.</div>';
        return;
      }
      for (const source of sources) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'source-card';
        button.dataset.sourceId = source.source_id || '';
        const location = source.locator && source.locator.label ? source.locator.label : '';
        button.innerHTML = `
          <strong>${escapeHtml(source.citation_label || source.source_id || 'Quelle')} · ${escapeHtml(source.document_name || 'Dokument')}</strong>
          <span>${escapeHtml(source.dataset_name || 'Bibliothek')}${location ? ` · ${escapeHtml(location)}` : ''}</span>
          <p>${escapeHtml(compact(source.snippet || '', 150))}</p>`;
        bindSourceInteractions(button, source);
        button.addEventListener('click', () => focusSource(source));
        sourceRailEl.appendChild(button);
      }
    }

    function bindSourceInteractions(element, source) {
      element.addEventListener('mouseenter', event => showHover(event.currentTarget, source));
      element.addEventListener('focus', event => showHover(event.currentTarget, source));
      element.addEventListener('mouseleave', hideHover);
      element.addEventListener('blur', hideHover);
      if (element.tagName === 'BUTTON' && element.classList.contains('citation-button')) {
        element.addEventListener('click', () => openPreview(source));
      }
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

    function focusSource(source) {
      document.querySelectorAll('.result-card,.source-card').forEach(item => item.classList.remove('is-active'));
      const selector = `[data-source-id="${cssEscape(source.source_id || '')}"]`;
      document.querySelectorAll(selector).forEach(item => item.classList.add('is-active'));
      const result = document.getElementById(`result-${safeDomId(source.source_id || '')}`);
      if (result) result.scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    function openPreview(source) {
      const target = source.preview_url || source.open_url;
      if (target) window.open(target, '_blank', 'noopener,noreferrer');
    }

    function openLabel(item) {
      if (item.open_url_kind === 'page_anchor') return 'Seite öffnen';
      if (item.open_url_kind === 'text_fragment') return 'Passage suchen';
      return 'Quelle öffnen';
    }

    function highlightSnippet(snippet, query) {
      let html = escapeHtml(snippet || '');
      const terms = [...new Set(String(query || '').split(/\s+/).map(t => t.trim()).filter(t => t.length >= 3).slice(0, 5))];
      for (const term of terms) {
        const pattern = new RegExp(`(${escapeRegExp(escapeHtml(term))})`, 'ig');
        html = html.replace(pattern, '<mark>$1</mark>');
      }
      return html;
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
      });
    });
    document.getElementById('selectAllProfiles').addEventListener('click', () => setAllProfiles(true));
    document.getElementById('clearProfiles').addEventListener('click', () => setAllProfiles(false));
    document.getElementById('profileFilter').addEventListener('input', applyProfileFilter);
    document.getElementById('queryForm').addEventListener('submit', runSearch);
    applyTheme(initialTheme());
    loadProfiles();
  </script>
</body>
</html>"""
