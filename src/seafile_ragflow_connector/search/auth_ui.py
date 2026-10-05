from __future__ import annotations

from html import escape


def render_login_html(error: str | None = None) -> str:
    error_html = ""
    if error:
        error_html = (
            '<div class="error" role="alert">'
            f"{escape(error)}"
            "</div>"
        )
    return _LOGIN_HTML.replace("__ERROR__", error_html)


_LOGIN_HTML = r"""<!doctype html>
<html lang="de" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Anmelden · Wissenssuche</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #edf4f7;
      --grid: rgba(100, 116, 139, .16);
      --surface: #ffffff;
      --text: #172033;
      --strong: #0f172a;
      --muted: #64748b;
      --border: #d7e2ec;
      --accent: #0f766e;
      --accent-hover: #0b625c;
      --accent-soft: #dff7f2;
      --danger: #b42318;
      --danger-soft: #fff1f0;
      --shadow: 0 24px 70px rgba(15, 23, 42, .14);
      --focus: 0 0 0 3px rgba(20, 184, 166, .25);
    }
    * { box-sizing: border-box; }
    html, body { min-width: 320px; min-height: 100%; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background:
        linear-gradient(90deg, transparent 0, transparent 23px, var(--grid) 24px),
        linear-gradient(0deg, transparent 0, transparent 23px, var(--grid) 24px),
        radial-gradient(circle at 50% 0, var(--accent-soft), transparent 34rem),
        var(--bg);
      background-size: 24px 24px, 24px 24px, auto, auto;
      color: var(--text);
      font-family: Segoe UI, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.45;
    }
    .card {
      width: min(100%, 430px);
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .head { padding: 28px 30px 20px; border-bottom: 1px solid var(--border); }
    .brand { display: flex; align-items: center; gap: 13px; }
    .mark {
      width: 42px;
      height: 42px;
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      border-radius: 10px;
      background: var(--accent);
      color: #ecfeff;
    }
    .mark svg { width: 23px; height: 23px; fill: none; stroke: currentColor; stroke-width: 2.4; }
    h1 { margin: 0; color: var(--strong); font-size: 1.35rem; line-height: 1.15; }
    .subtitle { margin: 6px 0 0; color: var(--muted); font-size: .94rem; }
    form { display: grid; gap: 17px; padding: 24px 30px 30px; }
    label { display: grid; gap: 7px; color: var(--strong); font-size: .92rem; font-weight: 720; }
    input {
      width: 100%;
      min-height: 46px;
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 0 13px;
      background: #fbfdfe;
      color: var(--text);
      font: inherit;
      outline: none;
    }
    input:focus { border-color: var(--accent); box-shadow: var(--focus); }
    button {
      min-height: 47px;
      border: 0;
      border-radius: 9px;
      padding: 0 16px;
      background: var(--accent);
      color: #ffffff;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }
    button:hover { background: var(--accent-hover); }
    button:focus-visible { outline: none; box-shadow: var(--focus); }
    .error {
      border: 1px solid color-mix(in srgb, var(--danger) 30%, var(--border));
      border-radius: 9px;
      padding: 11px 12px;
      background: var(--danger-soft);
      color: var(--danger);
      font-size: .9rem;
      font-weight: 650;
    }
    .hint { margin: -4px 0 0; color: var(--muted); font-size: .86rem; }
    @media (max-width: 520px) {
      body { padding: 14px; place-items: start center; }
      .card { margin-top: 7vh; }
      .head { padding: 23px 22px 18px; }
      form { padding: 21px 22px 24px; }
    }
  </style>
</head>
<body>
  <main class="card">
    <div class="head">
      <div class="brand">
        <div class="mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="m21 21-4.3-4.3"></path>
            <circle cx="11" cy="11" r="7"></circle>
            <path d="m8.4 11.2 1.7 1.7 3.8-4"></path>
          </svg>
        </div>
        <div>
          <h1>Wissenssuche</h1>
          <p class="subtitle">Mit Ihrem AD-/LDAP-Konto anmelden</p>
        </div>
      </div>
    </div>
    <form method="post" action="/auth/login">
      __ERROR__
      <label>
        AD-Benutzername
        <input name="username" type="text" autocomplete="username"
               autocapitalize="none" spellcheck="false" required autofocus>
      </label>
      <label>
        Passwort
        <input name="password" type="password" autocomplete="current-password" required>
      </label>
      <button type="submit">Anmelden</button>
      <p class="hint">
        Zugelassen sind Benutzer der für die KI-Infrastruktur freigegebenen AD-Gruppen.
      </p>
    </form>
  </main>
</body>
</html>
"""
