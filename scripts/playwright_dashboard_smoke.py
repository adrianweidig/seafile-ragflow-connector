from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.server import DashboardContext, start_dashboard_server
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits, utcnow
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import (
    OpenWebUIDatasetMapping,
    OpenWebUISyncState,
)

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
        description="Run an opt-in Playwright smoke check against the local dashboard."
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright browser engine to use.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window while the smoke check runs.",
    )
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
        print(f"FAILED: dashboard browser smoke: {exc}", file=sys.stderr)
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
            "Run 'uv run --extra dev python scripts/playwright_dashboard_smoke.py' "
            "or sync dev dependencies with 'uv sync --locked --all-extras'."
        ) from exc

    config.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="connector-dashboard-smoke-") as temp_dir:
        store, engine = _store(Path(temp_dir) / "dashboard.sqlite3")
        _seed_dashboard_fixture(store)
        settings = _settings(port=0)
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = int(handle.server.server_address[1])
        url = f"http://127.0.0.1:{port}/dashboard?lang=de"
        try:
            with sync_playwright() as playwright:
                browser_type = getattr(playwright, config.browser)
                browser = browser_type.launch(headless=not config.headed)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                _assert_dashboard_flow(page, url, config)
                context.close()
                browser.close()
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Playwright browser binaries are missing. "
                    "Run 'uv run --extra dev python -m playwright install chromium'."
                ) from exc
            raise
        finally:
            handle.stop()
            engine.dispose()


def _settings(*, port: int) -> Settings:
    settings = Settings(
        seafile_base_url="http://127.0.0.1:1",
        seafile_admin_token="smoke-seafile-admin",
        seafile_sync_user_token="smoke-seafile-sync",
        ragflow_base_url="http://127.0.0.1:1",
        ragflow_api_key="smoke-ragflow",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
        connector_dashboard_enabled=True,
        connector_dashboard_host="127.0.0.1",
        connector_dashboard_port=1,
        openwebui_proxy_shared_secret="smoke-proxy-secret",
    )
    settings.connector_dashboard_port = port
    return settings


def _store(db_path: Path) -> tuple[DashboardEventStore, Any]:
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return DashboardEventStore(session_factory, DashboardLimits(page_size=10)), engine


def _seed_dashboard_fixture(store: DashboardEventStore) -> None:
    sync_id = "smoke-sync-1"
    store.create_sync_run(
        sync_id=sync_id,
        source="seafile:smoke-library",
        target="ragflow:smoke-dataset",
        summary="Browser smoke fixture",
    )
    store.record_change(
        sync_id=sync_id,
        action="upload",
        change_type="created",
        status="synced",
        object_name="Installationshandbuch.pdf",
        source_path="/Admin/Installationshandbuch.pdf",
        target_path="Smoke Dataset/Installationshandbuch.pdf",
    )
    store.record_log(
        level="info",
        message="Dashboard browser smoke fixture loaded",
        component="playwright-smoke",
        sync_id=sync_id,
    )
    store.finish_sync_run(
        sync_id=sync_id,
        status="succeeded",
        objects_checked=1,
        objects_created=1,
        objects_updated=0,
        objects_deleted=0,
        objects_skipped=0,
    )
    with store.session_factory() as session:
        session.add(
            Library(
                repo_id="smoke-library",
                owner_email="admin@example.invalid",
                name="Installationshandbuch",
                name_slug="installationshandbuch",
                status="active",
                head_commit_id="head-smoke",
                last_synced_commit_id="head-smoke",
                ragflow_dataset_id="smoke-dataset",
                ragflow_dataset_name="Smoke Dataset",
            )
        )
        session.add(
            OpenWebUIDatasetMapping(
                repo_id="smoke-library",
                ragflow_dataset_id="smoke-dataset",
                ragflow_dataset_name="Smoke Dataset",
                ragflow_chat_id="smoke-chat",
                openwebui_tool_id="smoke-tool",
                openwebui_pipe_id="smoke-pipe",
                openwebui_model_name="ragflow-smoke-model",
                sync_status="synced",
            )
        )
        session.merge(
            OpenWebUISyncState(
                id="default",
                enabled=True,
                mode="dry-run",
                status="ready",
                base_url="http://openwebui.local",
                last_healthcheck_at=datetime.now(UTC),
                last_sync_started_at=datetime.now(UTC),
                last_sync_finished_at=datetime.now(UTC),
                last_successful_sync_at=datetime.now(UTC),
                dry_run_plan={"actions": [{"type": "noop", "dataset": "Smoke Dataset"}]},
                capabilities_snapshot={"functions_api": True, "pipes_api": True},
                summary={"datasets": 1, "tools": 1, "pipes": 1},
            )
        )
        session.commit()


def _assert_dashboard_flow(page: Any, url: str, config: BrowserSmokeConfig) -> None:
    page.goto(
        url.replace("lang=de", "lang=en"),
        wait_until="domcontentloaded",
        timeout=config.timeout_ms,
    )
    page.wait_for_selector("#state-value", state="visible", timeout=config.timeout_ms)
    _require_text(page, "#last-success", "Last success:")
    _require_text(page, "#last-failure", "Last error:")
    _require_text(page, "#problem-count", "entries")

    page.goto(url, wait_until="domcontentloaded", timeout=config.timeout_ms)
    page.wait_for_selector("#state-value", state="visible", timeout=config.timeout_ms)
    _wait_for_text_change(page, "#state-value", "-", config.timeout_ms)
    _require_visible(page, '[data-tab="overview"]', "overview tab")
    _require_visible(page, "#language-select", "language selector")
    _require_visible(page, "#audit-export", "audit export link")
    _require_text(page, "#recent-syncs", "succeeded")
    _require_text(page, "#recent-changes", "Installationshandbuch.pdf")
    _require_text(page, "#overview", "Systemzustand")
    _require_text(page, "#metrics", "BIBLIOTHEKEN")
    _require_text(page, "#metrics", "bekannter Zustand")
    _require_text(page, "#metrics", "erkannte Ereignisse")
    _require_text(page, "#metrics", "Warnungen im Log")
    _require_text(page, "#metrics", "Fehler im Log")

    page.select_option("#language-select", "en", timeout=config.timeout_ms)
    _require_text(page, "#state-value", "waiting")
    _require_text(page, "#dependency-health", "Dashboard responded.")
    _require_text(page, "#dependency-health", "Database")
    page.select_option("#language-select", "de", timeout=config.timeout_ms)
    _require_text(page, "#state-value", "wartend")
    _require_text(page, "#dependency-health", "Dashboard antwortet.")

    for tab in ("syncs", "changes", "logs", "systems", "openwebui", "diagnostics"):
        page.locator(f'[data-tab="{tab}"]').click(timeout=config.timeout_ms)
        page.wait_for_selector(f"#{tab}:not([hidden])", timeout=config.timeout_ms)
        if tab == "logs":
            _wait_for_text(page, "#log-total", "Logeinträge", config.timeout_ms)
            _require_text(page, "#log-table", "STUFE")
        if tab == "systems":
            _wait_for_text(page, "#source-table", "HEAD-COMMIT", config.timeout_ms)
            _require_text(page, "#target-table", "DATENSATZ-ID")
            _require_text(page, "#target-table", "TEMPLATE-HASH")
        if tab == "openwebui":
            _wait_for_text(page, "#openwebui-metrics", "DATENSÄTZE", config.timeout_ms)
            _require_text(page, "#openwebui-metrics", "erkannte Zuordnungen")
            _require_text(page, "#openwebui-table", "DATENSATZ")

    page.select_option("#language-select", "en", timeout=config.timeout_ms)
    page.locator('[data-tab="overview"]').click(timeout=config.timeout_ms)
    _require_text(page, "#view-title", "Overview")
    _wait_for_text(page, "#state-value", "waiting", config.timeout_ms)
    _wait_for_text(page, "#sidebar-state", "Status: waiting", config.timeout_ms)
    _require_text(page, "#sidebar-updated", "Updated:")
    _require_text(page, "#language-label", "LANGUAGE")
    _require_text(page, "#refresh-interval", "10 seconds")
    _wait_for_text(page, "#metrics", "detected events", config.timeout_ms)
    _require_text(page, "#overview", "CONNECTOR STATE")
    _require_text(page, "#overview", "Errors and warnings")
    _require_text(page, "#overview", "Recent sync runs")
    _require_text(page, "#metrics", "detected events")
    _require_text(page, "#metrics", "log-level warnings")
    _require_text(page, "#metrics", "log-level errors")
    _wait_for_text(page, "#dependency-health", "Dashboard responded.", config.timeout_ms)
    _require_text(page, "#dependency-health", "Database")
    _require_text(page, "#dependency-health", "SQL ping succeeded.")
    _require_text(page, "#dependency-health", "Integration disabled.")
    _require_text(page, "#dependency-health", "running jobs, no dead jobs.")
    page.locator('[data-tab="changes"]').click(timeout=config.timeout_ms)
    page.wait_for_selector("#changes:not([hidden])", timeout=config.timeout_ms)
    _require_text(page, "#changes .filters", "Type")
    _require_text(page, "#changes .filters", "Search")
    _require_attribute(page, "#change-query", "placeholder", "Path, name, error")
    page.locator('[data-tab="logs"]').click(timeout=config.timeout_ms)
    page.wait_for_selector("#logs:not([hidden])", timeout=config.timeout_ms)
    _require_text(page, "#logs .filters", "Search")
    _require_attribute(page, "#log-query", "placeholder", "Message or component")
    page.locator('[data-tab="systems"]').click(timeout=config.timeout_ms)
    page.wait_for_selector("#systems:not([hidden])", timeout=config.timeout_ms)
    _wait_for_text(page, "#source-table", "HEAD COMMIT", config.timeout_ms)
    _require_text(page, "#target-table", "DATASET ID")
    _require_text(page, "#target-table", "TEMPLATE HASH")
    page.locator('[data-tab="overview"]').click(timeout=config.timeout_ms)

    desktop_screenshot = config.output_dir / "dashboard-desktop.png"
    mobile_screenshot = config.output_dir / "dashboard-mobile.png"
    page.screenshot(path=str(desktop_screenshot), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('[data-tab="openwebui"]').click(timeout=config.timeout_ms)
    page.wait_for_selector("#openwebui:not([hidden])", timeout=config.timeout_ms)
    _wait_for_text(page, "#openwebui-metrics", "known mappings", config.timeout_ms)
    _require_text(page, "#openwebui-summary", "ready")
    _require_text(page, "#openwebui-metrics", "DATASETS")
    _require_text(page, "#openwebui-metrics", "known mappings")
    _require_text(page, "#openwebui-table", "DATASET")
    _require_text(page, "#openwebui-metrics", "including dry-run planned")
    _require_text(page, "#openwebui-metrics", "API fallback")
    _require_text(page, "#openwebui-metrics", "none")
    page.screenshot(path=str(mobile_screenshot), full_page=True)
    print(f"Dashboard browser smoke passed: {desktop_screenshot}")
    print(f"Dashboard browser smoke passed: {mobile_screenshot}")


def _require_visible(page: Any, selector: str, description: str) -> None:
    locator = page.locator(selector).first
    if not locator.is_visible(timeout=5_000):
        raise RuntimeError(f"{description} is not visible")


def _wait_for_text_change(page: Any, selector: str, initial_text: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_text = ""
    while time.monotonic() < deadline:
        last_text = page.locator(selector).first.inner_text(timeout=1_000).strip()
        if last_text and last_text != initial_text:
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} did not update before timeout: {last_text!r}")


def _wait_for_text(page: Any, selector: str, expected: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_text = ""
    while time.monotonic() < deadline:
        last_text = page.locator(selector).first.inner_text(timeout=1_000)
        if expected in last_text:
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} did not contain {expected!r} before timeout: {last_text!r}")


def _require_text(page: Any, selector: str, expected: str) -> None:
    locator = page.locator(selector).first
    text = locator.inner_text(timeout=5_000)
    if expected not in text:
        raise RuntimeError(f"{selector} does not contain {expected!r}: {text!r}")


def _require_attribute(page: Any, selector: str, attribute: str, expected: str) -> None:
    locator = page.locator(selector).first
    value = locator.get_attribute(attribute, timeout=5_000)
    if value != expected:
        raise RuntimeError(f"{selector} {attribute} is not {expected!r}: {value!r}")


if __name__ == "__main__":
    raise SystemExit(main())
