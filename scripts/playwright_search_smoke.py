from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from seafile_ragflow_connector.search.ui import SEARCH_HTML

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output" / "playwright"


@dataclass(frozen=True)
class BrowserSmokeConfig:
    browser: str
    headed: bool
    output_dir: Path
    timeout_ms: int


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an opt-in Playwright smoke check against the knowledge search UI."
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright browser engine to use.",
    )
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for screenshots and browser artifacts.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=20_000,
        help="Per-step browser timeout in milliseconds.",
    )
    args = parser.parse_args()
    config = BrowserSmokeConfig(
        browser=args.browser,
        headed=args.headed,
        output_dir=args.output_dir,
        timeout_ms=args.timeout_ms,
    )
    try:
        run_browser_smoke(config)
    except Exception as exc:
        print(f"FAILED: search browser smoke: {exc}", file=sys.stderr)
        return 1
    return 0


def run_browser_smoke(config: BrowserSmokeConfig) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        raise RuntimeError(
            "Python package 'playwright' is not installed. "
            "Run 'uv run --extra dev python scripts/playwright_search_smoke.py' "
            "or sync dev dependencies with 'uv sync --locked --all-extras'."
        ) from exc

    config.output_dir.mkdir(parents=True, exist_ok=True)
    server = _start_fake_search_server()
    port = int(server.server_address[1])
    url = f"http://127.0.0.1:{port}/search"
    try:
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, config.browser)
            browser = browser_type.launch(headless=not config.headed)
            context = browser.new_context(viewport={"width": 1440, "height": 940})
            page = context.new_page()
            _assert_search_flow(page, url, config)
            context.close()
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            mobile_page = mobile.new_page()
            _assert_mobile_layout(mobile_page, url, config)
            mobile.close()
            browser.close()
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Playwright browser binaries are missing. "
                "Run 'uv run --extra dev python -m playwright install chromium'."
            ) from exc
        raise
    finally:
        server.shutdown()
        server.server_close()


def _start_fake_search_server() -> ThreadingHTTPServer:
    class SearchSmokeHandler(BaseHTTPRequestHandler):
        server_version = "ConnectorSearchSmoke/1.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/search"}:
                self._send_html(SEARCH_HTML)
                return
            if self.path == "/api/search/profiles":
                self._send_json(
                    {
                        "user_display": "adrian",
                        "profiles": [
                            {
                                "id": "testnetz-user",
                                "display_name": "Testnetz User Handbuch",
                                "repo_id": "repo-user",
                                "kind": "Bibliothek",
                            },
                            {
                                "id": "testnetz-admin",
                                "display_name": "Testnetz Admin Handbuch",
                                "repo_id": "repo-admin",
                                "kind": "Bibliothek",
                            },
                        ],
                    }
                )
                return
            if self.path.startswith("/api/search/source/document"):
                token = parse_qs(urlparse(self.path).query).get("token", ["S1"])[0]
                self._send_text(_DOCUMENTS.get(token, _DOCUMENTS["S1"]))
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/api/search/chat", "/api/search/query"}:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(_search_response())

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_html(self, text: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, text: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(
            self,
            payload: dict[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), SearchSmokeHandler)
    thread = threading.Thread(target=server.serve_forever, name="search-smoke", daemon=True)
    thread.start()
    return server


def _assert_search_flow(page: Any, url: str, config: BrowserSmokeConfig) -> None:
    page.goto(url, wait_until="networkidle", timeout=config.timeout_ms)
    page.get_by_role("heading", name="Wissenssuche").wait_for(timeout=config.timeout_ms)
    page.get_by_label("Suchfrage").fill(
        "Welche Testnetz-Handbücher gibt es und wer darf sie sehen?"
    )
    page.get_by_role("button", name="Antwort generieren").click(timeout=config.timeout_ms)
    page.get_by_role("heading", name="Antwort mit Quellen").wait_for(timeout=config.timeout_ms)
    page.get_by_text("[S1]").wait_for(timeout=config.timeout_ms)
    page.locator('.sources-panel [aria-label="S2 anzeigen"]').wait_for(timeout=config.timeout_ms)
    page.locator('.sources-panel [aria-label="S2 anzeigen"]').click(timeout=config.timeout_ms)
    page.locator(".viewer-title", has_text="admin-handbuch-test.md").wait_for(
        timeout=config.timeout_ms
    )
    page.locator(".viewer-text-preview mark").wait_for(timeout=config.timeout_ms)
    mark_count = page.locator(".viewer-text-preview mark").count()
    if mark_count != 1:
        raise AssertionError(f"expected one focused text highlight, got {mark_count}")
    highlighted = page.locator(".viewer-text-preview mark").inner_text(timeout=config.timeout_ms)
    if len(highlighted) > 120:
        raise AssertionError(f"highlight is too broad: {highlighted!r}")
    page.screenshot(path=str(config.output_dir / "search-desktop.png"), full_page=True)
    print(f"Search browser smoke passed: {config.output_dir / 'search-desktop.png'}")


def _assert_mobile_layout(page: Any, url: str, config: BrowserSmokeConfig) -> None:
    page.goto(url, wait_until="networkidle", timeout=config.timeout_ms)
    page.get_by_role("heading", name="Wissenssuche").wait_for(timeout=config.timeout_ms)
    page.get_by_role("heading", name="Bibliotheken").wait_for(timeout=config.timeout_ms)
    page.get_by_label("Suchfrage").fill("test")
    page.get_by_role("button", name="Antwort generieren").click(timeout=config.timeout_ms)
    page.locator(".inline-sources").get_by_text("Quellen", exact=True).wait_for(
        timeout=config.timeout_ms
    )
    page.get_by_text("Fundstellen prüfen").wait_for(timeout=config.timeout_ms)
    page.screenshot(path=str(config.output_dir / "search-mobile.png"), full_page=True)
    print(f"Search browser smoke passed: {config.output_dir / 'search-mobile.png'}")


def _search_response() -> dict[str, Any]:
    sources = [
        _source(
            "S1",
            "user-handbuch-test.md",
            "Testnetz User Handbuch",
            "Dieses Dokument dient normalen Testnetz-Nutzern. Der Suchbegriff "
            "USERFREIGABE-GRUPPE-20260617 muss für GS_Testnetz_User Treffer liefern.",
        ),
        _source(
            "S2",
            "admin-handbuch-test.md",
            "Testnetz Admin Handbuch",
            "Dieses Labor-Dokument ist nur für die Seafile-Gruppe GS_Testnetz_Admin "
            "freigegeben. Prüffrage: FI Typ B Wartungsintervall.",
        ),
    ]
    return {
        "question": "Welche Testnetz-Handbücher gibt es und wer darf sie sehen?",
        "answer": {
            "text": (
                "Es gibt ein User-Handbuch für normale Testnetz-Nutzer und "
                "Admin-Unterlagen für die Admin-Gruppe. Die Sichtbarkeit ist über "
                "Gruppen wie GS_Testnetz_User und GS_Testnetz_Admin geregelt [S1] [S2]."
            ),
            "mode": "openai_compatible",
            "citations": [
                {"marker": "S1", "source_ids": ["S1"]},
                {"marker": "S2", "source_ids": ["S2"]},
            ],
        },
        "results": sources,
        "diagnostics": {"profiles_allowed": 2, "profiles_denied": 0},
    }


def _source(source_id: str, file_name: str, dataset: str, passage: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "citation_label": source_id,
        "document_name": file_name,
        "dataset_name": dataset,
        "locator": {"label": "Seite 2"},
        "viewer_kind": "text",
        "viewer_url": f"/api/search/source/document?token={source_id}",
        "viewer_message": "Textdateien werden inline angezeigt.",
        "preview_url": f"/api/search/source/preview?token={source_id}",
        "open_url": f"https://seafile.example/{file_name}",
        "snippet": passage,
        "passageTextExact": passage,
        "score_percent": 96 if source_id == "S1" else 91,
        "source_path": f"/{file_name}",
    }


_DOCUMENTS = {
    "S1": """# Testnetz User Handbuch

Dieses Dokument dient normalen Testnetz-Nutzern.
Der Suchbegriff USERFREIGABE-GRUPPE-20260617 muss für GS_Testnetz_User Treffer liefern.
""",
    "S2": """# Testnetz Admin Handbuch

TESTNETZADMIN-HANDBUCH-20260617

Dieses Labor-Dokument ist nur für die Seafile-Gruppe GS_Testnetz_Admin freigegeben.
Prüffrage: FI Typ B Wartungsintervall.
""",
}


if __name__ == "__main__":
    raise SystemExit(main())
