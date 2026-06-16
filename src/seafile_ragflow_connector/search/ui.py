from __future__ import annotations

# ruff: noqa: E501

SEARCH_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wissenssuche</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-soft: #f1f5f9;
      --text: #142033;
      --muted: #64748b;
      --border: #d8e2ec;
      --accent: #0f766e;
      --accent-strong: #0b5f58;
      --accent-soft: #e7f7f5;
      --danger: #b42318;
      --danger-soft: #fff1f0;
      --warning: #b45309;
      --shadow: 0 16px 44px rgba(15, 23, 42, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Segoe UI, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.45;
      letter-spacing: 0;
    }
    button, input { font: inherit; letter-spacing: 0; }
    .shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 68px;
      padding: 0 28px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .brand-mark {
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      font-weight: 800;
    }
    h1 { margin: 0; font-size: 1.15rem; line-height: 1.15; }
    .user-line { color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
    main {
      width: min(1480px, 100%);
      margin: 0 auto;
      padding: 28px;
      display: grid;
      grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }
    aside, .search-surface {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    aside { position: sticky; top: 20px; max-height: calc(100vh - 108px); overflow: auto; }
    .side-head { padding: 18px 18px 12px; border-bottom: 1px solid var(--border); }
    .side-head h2 { margin: 0; font-size: 1rem; }
    .side-head p { margin: 4px 0 0; color: var(--muted); font-size: .88rem; }
    .profile-list { padding: 10px; display: grid; gap: 4px; }
    .profile-row {
      display: grid;
      grid-template-columns: 20px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 10px 8px;
      border-radius: 7px;
      cursor: pointer;
    }
    .profile-row:hover { background: var(--surface-soft); }
    .profile-row input { margin-top: 3px; accent-color: var(--accent); }
    .profile-name { display: block; font-weight: 700; overflow-wrap: anywhere; }
    .profile-kind { display: block; margin-top: 2px; color: var(--muted); font-size: .82rem; }
    .search-surface { overflow: hidden; }
    .query-area {
      padding: 24px;
      display: grid;
      gap: 16px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, #fff 0%, #fbfdff 100%);
    }
    .query-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
    .query-input {
      min-height: 58px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 17px;
      background: #fff;
      color: var(--text);
      font-size: 1.05rem;
      outline: none;
    }
    .query-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(15, 118, 110, .16); }
    .primary {
      min-height: 58px;
      border: 1px solid var(--accent);
      border-radius: 8px;
      padding: 0 20px;
      background: var(--accent);
      color: #fff;
      font-weight: 800;
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
      background: #fff;
    }
    .segment {
      border: 0;
      min-height: 40px;
      padding: 0 14px;
      background: transparent;
      color: var(--muted);
      font-weight: 750;
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
    }
    .state { padding: 22px 24px; border-bottom: 1px solid var(--border); color: var(--muted); }
    .state.error { color: var(--danger); background: var(--danger-soft); }
    .state.loading { color: var(--accent-strong); background: var(--accent-soft); }
    .answer {
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);
      background: #fff;
    }
    .answer h2 { margin: 0 0 8px; font-size: 1rem; }
    .answer p { margin: 0; color: var(--text); white-space: pre-wrap; }
    .results { padding: 18px; display: grid; gap: 14px; }
    .result-card {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      padding: 16px;
      display: grid;
      gap: 12px;
    }
    .result-top { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .result-title { margin: 0; font-size: 1.02rem; overflow-wrap: anywhere; }
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
      font-weight: 700;
    }
    .snippet { margin: 0; color: #243244; white-space: pre-wrap; overflow-wrap: anywhere; }
    .path { color: var(--muted); font-size: .88rem; overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .secondary {
      min-height: 38px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0 12px;
      background: #fff;
      color: var(--text);
      font-weight: 750;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      cursor: pointer;
    }
    .secondary:hover { border-color: var(--accent); color: var(--accent-strong); }
    .empty { padding: 36px 24px; color: var(--muted); text-align: center; }
    dialog {
      width: min(760px, calc(100vw - 28px));
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0;
      box-shadow: 0 26px 80px rgba(15, 23, 42, .2);
    }
    dialog::backdrop { background: rgba(15, 23, 42, .32); }
    .modal-head { padding: 16px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; gap: 12px; }
    .modal-head strong { overflow-wrap: anywhere; }
    .modal-body { padding: 18px; white-space: pre-wrap; color: var(--text); }
    @media (max-width: 900px) {
      header { padding: 0 16px; }
      main { grid-template-columns: 1fr; padding: 16px; }
      aside { position: static; max-height: none; }
      .query-form { grid-template-columns: 1fr; }
      .primary { width: 100%; }
    }
    @media (max-width: 560px) {
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
    </header>
    <main>
      <aside aria-label="Bibliotheken">
        <div class="side-head">
          <h2>Bibliotheken</h2>
          <p id="profileSummary">Profile werden geladen …</p>
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
        <div id="state" class="state">Wähle Bibliotheken aus und starte eine Suche.</div>
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

    function renderProfiles() {
      profileListEl.innerHTML = '';
      if (!profiles.length) {
        profileListEl.innerHTML = '<div class="empty">Keine freigegebenen Bibliotheken verfügbar.</div>';
        profileSummaryEl.textContent = '0 Bibliotheken';
        return;
      }
      profileSummaryEl.textContent = `${profiles.length} verfügbare Bibliothek${profiles.length === 1 ? '' : 'en'}`;
      for (const profile of profiles) {
        const label = document.createElement('label');
        label.className = 'profile-row';
        label.innerHTML = `
          <input data-profile-id type="checkbox" value="${escapeHtml(profile.id)}" checked>
          <span>
            <span class="profile-name">${escapeHtml(profile.display_name || profile.repo_id)}</span>
            <span class="profile-kind">${escapeHtml(profile.kind || 'Bibliothek')}</span>
          </span>`;
        profileListEl.appendChild(label);
      }
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
        setState('Wähle mindestens eine Bibliothek aus.', 'error');
        return;
      }
      const endpoint = mode === 'chat' ? '/api/search/chat' : '/api/search/query';
      setState('Suche läuft …', 'loading');
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
          body: JSON.stringify({profile_ids, question, top_k: Number(topKEl.value || 8)})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || data.error || 'Suche fehlgeschlagen.');
        if (data.answer) renderAnswer(data.answer);
        renderResults(data.results || data.sources || []);
        const denied = data.diagnostics && data.diagnostics.profiles_denied ? data.diagnostics.profiles_denied : 0;
        setState(denied ? `${denied} Bibliothek(en) wurden wegen fehlender Berechtigung ausgelassen.` : 'Suche abgeschlossen.');
      } catch (error) {
        setState(error.message || 'Suche fehlgeschlagen.', 'error');
      }
    }

    function renderAnswer(answer) {
      answerEl.hidden = false;
      answerEl.innerHTML = `<h2>Antwort mit Quellen</h2><p>${escapeHtml(answer)}</p>`;
    }

    function renderResults(results) {
      resultsEl.innerHTML = '';
      if (!results.length) {
        resultsEl.innerHTML = '<div class="empty">Keine passenden Treffer gefunden.</div>';
        return;
      }
      for (const item of results) {
        const card = document.createElement('article');
        card.className = 'result-card';
        card.innerHTML = `
          <div class="result-top">
            <div>
              <h3 class="result-title">${escapeHtml(item.document_name || 'Dokument')}</h3>
              <div class="meta">
                <span>${escapeHtml(item.dataset_name || 'Bibliothek')}</span>
                ${item.page ? `<span>${escapeHtml(String(item.page))}</span>` : ''}
              </div>
            </div>
            ${item.score !== null && item.score !== undefined ? `<span class="pill">${formatScore(item.score)}</span>` : ''}
          </div>
          <p class="snippet">${escapeHtml(item.snippet || 'Kein Snippet verfügbar.')}</p>
          <div class="path">${escapeHtml(item.source_path || '')}</div>
          <div class="actions">
            ${item.open_url ? `<a class="secondary" href="${escapeAttr(item.open_url)}" target="_blank" rel="noreferrer noopener">Quelle öffnen</a>` : '<span class="secondary" aria-disabled="true">Quelle öffnen</span>'}
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

    document.querySelectorAll('.segment').forEach(button => {
      button.addEventListener('click', () => {
        mode = button.dataset.mode;
        document.querySelectorAll('.segment').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      });
    });
    document.getElementById('queryForm').addEventListener('submit', runSearch);
    document.getElementById('closePreview').addEventListener('click', () => dialog.close());
    loadProfiles();
  </script>
</body>
</html>"""
