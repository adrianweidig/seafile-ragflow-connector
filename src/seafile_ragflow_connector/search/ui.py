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
      --bg: #f5f7fa;
      --bg-pattern: #e7edf4;
      --surface: #ffffff;
      --surface-raised: #ffffff;
      --surface-soft: #f1f5f9;
      --surface-selected: #e6f4f1;
      --text: #142033;
      --text-strong: #0f172a;
      --muted: #627086;
      --border: #d6e0ea;
      --border-strong: #a9bacb;
      --accent: #0f766e;
      --accent-strong: #0b5f58;
      --accent-soft: #def3ef;
      --accent-contrast: #ffffff;
      --danger: #b42318;
      --danger-soft: #fff1f0;
      --warning: #b45309;
      --warning-soft: #fff7ed;
      --shadow: 0 18px 44px rgba(15, 23, 42, .09);
      --focus: 0 0 0 3px rgba(15, 118, 110, .18);
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --bg: #111827;
      --bg-pattern: #1f2937;
      --surface: #172033;
      --surface-raised: #1f2a3d;
      --surface-soft: #233149;
      --surface-selected: #123d3b;
      --text: #e5edf7;
      --text-strong: #f8fafc;
      --muted: #a8b3c5;
      --border: #334155;
      --border-strong: #52647a;
      --accent: #2dd4bf;
      --accent-strong: #5eead4;
      --accent-soft: #103c39;
      --accent-contrast: #082f2b;
      --danger: #fca5a5;
      --danger-soft: #3f1f23;
      --warning: #fbbf24;
      --warning-soft: #3d2f17;
      --shadow: 0 22px 54px rgba(0, 0, 0, .34);
      --focus: 0 0 0 3px rgba(45, 212, 191, .22);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background:
        linear-gradient(90deg, transparent 0, transparent 23px, var(--bg-pattern) 24px),
        linear-gradient(0deg, transparent 0, transparent 23px, var(--bg-pattern) 24px),
        var(--bg);
      background-size: 24px 24px;
      color: var(--text);
      font-family: Segoe UI, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.45;
      letter-spacing: 0;
    }
    button, input { font: inherit; letter-spacing: 0; }
    button:focus-visible, input:focus-visible, a:focus-visible { outline: none; box-shadow: var(--focus); }
    .shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 72px;
      padding: 0 28px;
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(12px);
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .brand-mark {
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent);
      color: var(--accent-contrast);
      font-weight: 850;
    }
    h1 { margin: 0; font-size: 1.16rem; line-height: 1.15; color: var(--text-strong); }
    .user-line { color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
    .header-actions { display: flex; align-items: center; gap: 10px; }
    .theme-toggle {
      display: inline-grid;
      grid-template-columns: 1fr 1fr;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface-raised);
      min-width: 148px;
    }
    .theme-option {
      min-height: 38px;
      border: 0;
      padding: 0 12px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-weight: 760;
    }
    .theme-option[aria-pressed="true"] {
      background: var(--accent-soft);
      color: var(--accent-strong);
    }
    main {
      width: min(1480px, 100%);
      margin: 0 auto;
      padding: 28px;
      display: grid;
      grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }
    aside, .search-surface {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    aside { position: sticky; top: 20px; max-height: calc(100vh - 112px); overflow: auto; }
    .side-head { padding: 18px 18px 12px; border-bottom: 1px solid var(--border); display: grid; gap: 10px; }
    .side-title { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
    .side-head h2 { margin: 0; font-size: 1rem; color: var(--text-strong); }
    .side-head p { margin: 4px 0 0; color: var(--muted); font-size: .88rem; }
    .selection-count {
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--surface-soft);
      color: var(--muted);
      font-size: .8rem;
      font-weight: 800;
      white-space: nowrap;
    }
    .profile-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .mini-button {
      min-height: 34px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 10px;
      background: var(--surface-raised);
      color: var(--text);
      font-weight: 760;
      cursor: pointer;
    }
    .mini-button:hover { border-color: var(--accent); color: var(--accent-strong); }
    .profile-list { padding: 10px; display: grid; gap: 6px; }
    .profile-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 11px 9px;
      border: 1px solid transparent;
      border-radius: 8px;
      cursor: pointer;
    }
    .profile-row:hover { background: var(--surface-soft); }
    .profile-row:has(input:checked) {
      background: var(--surface-selected);
      border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
    }
    .profile-row input { width: 17px; height: 17px; margin-top: 3px; accent-color: var(--accent); }
    .profile-name { display: block; font-weight: 780; color: var(--text-strong); overflow-wrap: anywhere; }
    .profile-kind { display: block; margin-top: 2px; color: var(--muted); font-size: .82rem; }
    .search-surface { overflow: hidden; }
    .query-area {
      padding: 24px;
      display: grid;
      gap: 16px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-raised);
    }
    .query-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
    .query-input {
      min-height: 58px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 17px;
      background: var(--surface);
      color: var(--text);
      font-size: 1.05rem;
      outline: none;
    }
    .query-input::placeholder { color: var(--muted); }
    .query-input:focus { border-color: var(--accent); box-shadow: var(--focus); }
    .primary {
      min-height: 58px;
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 0 20px;
      background: var(--accent);
      color: var(--accent-contrast);
      font-weight: 850;
      cursor: pointer;
    }
    .primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    .toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
    .segments {
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface);
    }
    .segment {
      border: 0;
      min-height: 40px;
      padding: 0 14px;
      background: transparent;
      color: var(--muted);
      font-weight: 760;
      cursor: pointer;
    }
    .segment[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent-strong); }
    .topk { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: .9rem; }
    .topk input {
      width: 72px;
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 9px;
      background: var(--surface);
      color: var(--text);
    }
    .state { padding: 18px 24px; border-bottom: 1px solid var(--border); color: var(--muted); background: color-mix(in srgb, var(--surface) 96%, var(--accent-soft)); }
    .state.error { color: var(--danger); background: var(--danger-soft); }
    .state.loading { color: var(--accent-strong); background: var(--accent-soft); }
    .state.success { color: var(--accent-strong); background: var(--accent-soft); }
    .answer {
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }
    .answer h2 { margin: 0 0 8px; font-size: 1rem; color: var(--text-strong); }
    .answer p { margin: 0; color: var(--text); white-space: pre-wrap; }
    .answer-sources {
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
    }
    .answer-source {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-raised);
      padding: 10px 12px;
      display: grid;
      gap: 5px;
    }
    .answer-source strong { color: var(--text-strong); overflow-wrap: anywhere; }
    .answer-source span { color: var(--muted); font-size: .86rem; overflow-wrap: anywhere; }
    .results { padding: 18px; display: grid; gap: 14px; }
    .result-card {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-raised);
      padding: 16px;
      display: grid;
      gap: 12px;
    }
    .result-top { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .result-title { margin: 0; font-size: 1.02rem; color: var(--text-strong); overflow-wrap: anywhere; }
    .meta { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: .86rem; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 3px 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--surface-soft);
      color: var(--muted);
      font-size: .82rem;
      font-weight: 760;
    }
    .pill.dataset {
      background: var(--accent-soft);
      color: var(--accent-strong);
      border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
    }
    .snippet { margin: 0; color: var(--text); white-space: pre-wrap; overflow-wrap: anywhere; }
    .path { color: var(--muted); font-size: .88rem; overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .secondary {
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 12px;
      background: var(--surface);
      color: var(--text);
      font-weight: 760;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .secondary:hover { border-color: var(--accent); color: var(--accent-strong); }
    .secondary[aria-disabled="true"] { opacity: .58; cursor: not-allowed; }
    .secondary[aria-disabled="true"]:hover { border-color: var(--border); color: var(--text); }
    .empty { padding: 36px 24px; color: var(--muted); text-align: center; }
    dialog {
      width: min(760px, calc(100vw - 28px));
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 26px 80px rgba(15, 23, 42, .28);
    }
    dialog::backdrop { background: rgba(15, 23, 42, .45); }
    .modal-head { padding: 16px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; gap: 12px; }
    .modal-head strong { color: var(--text-strong); overflow-wrap: anywhere; }
    .modal-body { padding: 18px; white-space: pre-wrap; color: var(--text); }
    @media (max-width: 900px) {
      header { padding: 12px 16px; align-items: flex-start; }
      main { grid-template-columns: 1fr; padding: 16px; }
      aside { position: static; max-height: none; }
      .query-form { grid-template-columns: 1fr; }
      .primary { width: 100%; }
    }
    @media (max-width: 620px) {
      header { display: grid; }
      .header-actions { justify-content: stretch; }
      .theme-toggle { width: 100%; }
      .toolbar { display: grid; }
      .segments { width: 100%; }
      .result-top { display: grid; }
      .actions .secondary { width: 100%; justify-content: center; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">W</div>
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
      <aside aria-label="Bibliotheken">
        <div class="side-head">
          <div class="side-title">
            <div>
              <h2>Bibliotheken</h2>
              <p id="profileSummary">Profile werden geladen …</p>
            </div>
            <span class="selection-count" id="selectionCount">0/0</span>
          </div>
          <div class="profile-actions" aria-label="Bibliotheksauswahl">
            <button class="mini-button" type="button" id="selectAllProfiles">Alle</button>
            <button class="mini-button" type="button" id="clearProfiles">Keine</button>
          </div>
        </div>
        <div class="profile-list" id="profileList"></div>
      </aside>
      <section class="search-surface" aria-label="Suche">
        <div class="query-area">
          <form class="query-form" id="queryForm">
            <input class="query-input" id="question" name="question" autocomplete="off" placeholder="FI Typ B Wartungsintervall" aria-label="Suchfrage">
            <button class="primary" type="submit">Suchen</button>
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
    </main>
  </div>
  <dialog id="previewDialog">
    <div class="modal-head">
      <strong id="previewTitle">Vorschau</strong>
      <button class="secondary" type="button" id="closePreview">Schließen</button>
    </div>
    <div class="modal-body" id="previewBody"></div>
  </dialog>
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
    const dialog = document.getElementById('previewDialog');
    let profiles = [];
    let mode = 'retrieval';

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
        item.checked = checked;
      });
      updateProfileSelectionState();
      if (!checked) {
        setState('Keine Bibliothek ausgewählt. Wähle mindestens eine Bibliothek für die Suche.');
      }
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
        if (data.answer) renderAnswer(data.answer, results);
        renderResults(results);
        const denied = data.diagnostics && data.diagnostics.profiles_denied ? data.diagnostics.profiles_denied : 0;
        const allowed = data.diagnostics && data.diagnostics.profiles_allowed ? data.diagnostics.profiles_allowed : profile_ids.length;
        const resultText = `${results.length} Treffer aus ${allowed} Bibliothek${allowed === 1 ? '' : 'en'}.`;
        setState(denied ? `${resultText} ${denied} Bibliothek(en) wurden wegen fehlender Berechtigung ausgelassen.` : resultText, 'success');
      } catch (error) {
        setState(error.message || 'Suche fehlgeschlagen.', 'error');
      }
    }

    function renderAnswer(answer, sources = []) {
      answerEl.hidden = false;
      const sourceItems = sources.slice(0, 4).map(item => `
        <li class="answer-source">
          <strong>${escapeHtml(item.document_name || 'Dokument')}</strong>
          <span>${escapeHtml(item.dataset_name || 'Bibliothek')}${item.source_path ? ` · ${escapeHtml(item.source_path)}` : ''}</span>
        </li>`).join('');
      answerEl.innerHTML = `
        <h2>Antwort mit Quellen</h2>
        <p>${escapeHtml(answer)}</p>
        ${sourceItems ? `<ul class="answer-sources">${sourceItems}</ul>` : ''}`;
    }

    function renderResults(results) {
      resultsEl.innerHTML = '';
      if (!results.length) {
        resultsEl.innerHTML = '<div class="empty">Keine passenden Treffer in den ausgewählten Bibliotheken gefunden.</div>';
        return;
      }
      for (const item of results) {
        const card = document.createElement('article');
        card.className = 'result-card';
        card.dataset.resultDataset = item.dataset_name || 'Bibliothek';
        card.innerHTML = `
          <div class="result-top">
            <div>
              <h3 class="result-title">${escapeHtml(item.document_name || 'Dokument')}</h3>
              <div class="meta">
                <span class="pill dataset">${escapeHtml(item.dataset_name || 'Bibliothek')}</span>
                ${item.page ? `<span class="pill">Seite ${escapeHtml(String(item.page))}</span>` : ''}
              </div>
            </div>
            ${item.score !== null && item.score !== undefined ? `<span class="pill">${formatScore(item.score)}</span>` : ''}
          </div>
          <p class="snippet">${escapeHtml(item.snippet || 'Kein Snippet verfügbar.')}</p>
          <div class="path">${escapeHtml(item.source_path || '')}</div>
          <div class="actions">
            ${item.open_url ? `<a class="secondary" href="${escapeAttr(item.open_url)}" target="_blank" rel="noreferrer noopener">Quelle öffnen</a>` : '<span class="secondary" aria-disabled="true" title="Für diesen Treffer ist kein Originallink vorhanden.">Quelle öffnen</span>'}
            <button class="secondary" type="button">Vorschau</button>
          </div>`;
        card.querySelector('button').addEventListener('click', () => showPreview(item));
        resultsEl.appendChild(card);
      }
    }

    function showPreview(item) {
      document.getElementById('previewTitle').textContent = item.document_name || 'Vorschau';
      document.getElementById('previewBody').textContent = item.snippet || 'Keine Vorschau verfügbar.';
      dialog.showModal();
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }

    function escapeAttr(value) { return escapeHtml(value).replace(/`/g, '&#96;'); }

    function formatScore(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 'Score';
      const scaled = number > 1 ? number : number * 100;
      return `${Math.round(scaled)}%`;
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
      });
    });
    document.getElementById('selectAllProfiles').addEventListener('click', () => setAllProfiles(true));
    document.getElementById('clearProfiles').addEventListener('click', () => setAllProfiles(false));
    document.getElementById('queryForm').addEventListener('submit', runSearch);
    document.getElementById('closePreview').addEventListener('click', () => dialog.close());
    applyTheme(initialTheme());
    loadProfiles();
  </script>
</body>
</html>"""
