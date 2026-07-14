from __future__ import annotations

import argparse
import json
import sys
import threading
import time
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
            cancelled = list(getattr(server, "cancelled_requests", []))
            searched = list(getattr(server, "search_request_ids", []))
            if not cancelled or not set(cancelled).intersection(searched):
                raise AssertionError(
                    "browser cancel did not send the active search request_id"
                )
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
        retry_attempts = 0

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
                        "capabilities": {
                            "max_selected_profiles": 25,
                            "default_page_size": 20,
                            "max_page_size": 100,
                            "max_parallel_profiles": 4,
                            "cursor_pagination": True,
                            "snapshot_pagination": True,
                            "snapshot_ttl_seconds": 180,
                            "snapshot_max_results": 200,
                            "partial_results": True,
                            "source_dto_version": "v1",
                        },
                    }
                )
                return
            if self.path.startswith("/api/search/source/document"):
                token = parse_qs(urlparse(self.path).query).get("token", ["S1"])[0]
                self._send_text(_DOCUMENTS.get(token, _DOCUMENTS["S1"]))
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {
                "/api/search/chat",
                "/api/search/query",
                "/api/search/cancel",
            }:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(content_length) if content_length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            request_id = str(payload.get("request_id") or "")
            if self.path == "/api/search/cancel":
                self.server.cancelled_requests.append(request_id)  # type: ignore[attr-defined]
                self._send_json({"request_id": request_id, "cancelled": True})
                return
            self.server.search_request_ids.append(request_id)  # type: ignore[attr-defined]
            question = str(payload.get("question") or "")
            if question.startswith("Langsame Suche"):
                time.sleep(1.0)
            if question.startswith("Wiederholen"):
                type(self).retry_attempts += 1
                if type(self).retry_attempts == 1:
                    self._send_json(
                        {"message": "Temporärer Testfehler."},
                        status=HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
            cursor = str(payload.get("cursor") or "")
            self._send_json(_search_response(second_page=cursor == "page-2"))

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_html(self, text: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

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
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SearchSmokeHandler)
    server.cancelled_requests = []  # type: ignore[attr-defined]
    server.search_request_ids = []  # type: ignore[attr-defined]
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
    page.get_by_role("button", name="Weitere Treffer laden").click(
        timeout=config.timeout_ms
    )
    page.locator('.sources-panel [aria-label="S3 anzeigen"]').wait_for(
        timeout=config.timeout_ms
    )
    page.get_by_text("1 weiterer Treffer geladen.").wait_for(timeout=config.timeout_ms)

    page.get_by_label("Suchfrage").fill("Langsame Suche abbrechen")
    page.get_by_role("button", name="Antwort generieren").click(timeout=config.timeout_ms)
    page.get_by_role("button", name="Suche abbrechen").click(timeout=config.timeout_ms)
    page.get_by_text("Suche abgebrochen.", exact=False).wait_for(timeout=config.timeout_ms)
    page.get_by_text("Admin-Unterlagen für die Admin-Gruppe", exact=False).wait_for(
        timeout=config.timeout_ms
    )

    page.get_by_label("Suchfrage").fill("Wiederholen nach Fehler")
    page.get_by_role("button", name="Antwort generieren").click(timeout=config.timeout_ms)
    page.get_by_role("button", name="Erneut versuchen").wait_for(timeout=config.timeout_ms)
    page.get_by_role("button", name="Erneut versuchen").click(timeout=config.timeout_ms)
    page.get_by_text("2 Treffer aus 2 Bibliotheken.").wait_for(timeout=config.timeout_ms)
    page.screenshot(path=str(config.output_dir / "search-desktop.png"), full_page=True)
    print(f"Search browser smoke passed: {config.output_dir / 'search-desktop.png'}")


def _assert_mobile_layout(page: Any, url: str, config: BrowserSmokeConfig) -> None:
    page.goto(url, wait_until="networkidle", timeout=config.timeout_ms)
    page.get_by_role("heading", name="Wissenssuche").wait_for(timeout=config.timeout_ms)
    page.get_by_role("heading", name="Bibliotheken").wait_for(timeout=config.timeout_ms)
    page.get_by_label("Suchfrage").fill("test")
    page.get_by_role("button", name="Antwort generieren").click(timeout=config.timeout_ms)
    page.get_by_role("tab", name="Antwort").wait_for(timeout=config.timeout_ms)
    if page.get_by_role("tab", name="Antwort").get_attribute("aria-selected") != "true":
        raise AssertionError("mobile answer tab is not active after search")
    page.get_by_role("tab", name="Quellen").click(timeout=config.timeout_ms)
    page.locator(".inline-sources").get_by_text("Quellen", exact=True).wait_for(
        timeout=config.timeout_ms
    )
    page.locator('.inline-source-card[aria-label="S1 anzeigen"]').wait_for(
        timeout=config.timeout_ms
    )
    page.locator('.inline-source-card[aria-label="S2 anzeigen"]').click(
        timeout=config.timeout_ms
    )
    if page.get_by_role("tab", name="Dokument").get_attribute("aria-selected") != "true":
        raise AssertionError("selecting a mobile source did not open the document tab")
    page.locator(".viewer-title", has_text="admin-handbuch-test.md").wait_for(
        timeout=config.timeout_ms
    )
    page.screenshot(path=str(config.output_dir / "search-mobile.png"), full_page=True)
    print(f"Search browser smoke passed: {config.output_dir / 'search-mobile.png'}")


def _search_response(*, second_page: bool = False) -> dict[str, Any]:
    if second_page:
        sources = [
            _source(
                "S3",
                "betriebsrat-handbuch.md",
                "Testnetz User Handbuch",
                "Eine weitere paginierte Fundstelle für den Browser-Smoke-Test.",
            )
        ]
        return {
            "question": "Welche Testnetz-Handbücher gibt es und wer darf sie sehen?",
            "results": sources,
            "partial_failures": [],
            "pagination": {
                "next_cursor": None,
                "has_more": False,
                "snapshot": True,
                "snapshot_result_count": 3,
            },
            "diagnostics": {"profiles_allowed": 2, "profiles_denied": 0},
        }
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
        "partial_failures": [],
        "pagination": {
            "next_cursor": "page-2",
            "has_more": True,
            "snapshot": True,
            "snapshot_result_count": 3,
        },
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
