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
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
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


class _SmokeWorkflowOrchestrator:
    skip_encrypted_libraries = True
    skip_virtual_repos = True

    def __init__(self) -> None:
        self.admin_client = self

    @staticmethod
    def iter_libraries() -> list[dict[str, object]]:
        return [
            {
                "id": "smoke-library",
                "name": "Installationshandbuch",
                "owner": "admin@example.invalid",
                "head_commit_id": "head-smoke",
            }
        ]

    @staticmethod
    def list_cleanup_outbox(**_kwargs: object) -> list[object]:
        return []


class _SmokeSignalQueue:
    def __init__(self) -> None:
        self.job_ids: list[int] = []

    def signal(self, job_id: int) -> None:
        self.job_ids.append(job_id)


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
    try:
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, config.browser)
            browser = browser_type.launch(headless=not config.headed)
            try:
                _run_read_only_case(browser, config)
                _run_active_admin_case(browser, config)
            finally:
                browser.close()
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Playwright browser binaries are missing. "
                "Run 'uv run --extra dev python -m playwright install chromium'."
            ) from exc
        raise


def _run_read_only_case(browser: Any, config: BrowserSmokeConfig) -> None:
    with tempfile.TemporaryDirectory(prefix="connector-dashboard-read-only-") as temp_dir:
        store, engine = _store(Path(temp_dir) / "dashboard.sqlite3")
        handle = None
        try:
            _seed_dashboard_fixture(store)
            handle = start_dashboard_server(
                DashboardContext(
                    store=store,
                    settings=_settings(port=0),
                    started_at=utcnow(),
                )
            )
            port = int(handle.server.server_address[1])
            url = f"http://127.0.0.1:{port}/dashboard?lang=de"
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                _assert_read_only_dashboard_flow(context.new_page(), url, config)
            finally:
                context.close()
        finally:
            if handle is not None:
                handle.stop()
            engine.dispose()


def _run_active_admin_case(browser: Any, config: BrowserSmokeConfig) -> None:
    with tempfile.TemporaryDirectory(prefix="connector-dashboard-admin-") as temp_dir:
        store, engine = _store(Path(temp_dir) / "dashboard.sqlite3")
        handle = None
        try:
            _seed_dashboard_fixture(store)
            job_store = JobStore(store.session_factory)
            control_store = AdminControlStore(store.session_factory)
            handle = start_dashboard_server(
                DashboardContext(
                    store=store,
                    settings=_settings(port=0, admin_control=True),
                    started_at=utcnow(),
                    orchestrator=_SmokeWorkflowOrchestrator(),
                    openwebui_sync_service=object(),
                    job_store=job_store,
                    signal_queue=_SmokeSignalQueue(),
                    control_store=control_store,
                )
            )
            port = int(handle.server.server_address[1])
            url = f"http://127.0.0.1:{port}/dashboard?lang=de&tab=workflow"
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                http_credentials={"username": "admin", "password": "secret"},
            )
            try:
                _assert_active_admin_flow(context.new_page(), url, config)
            finally:
                context.close()
            workflow_control = control_store.workflow()
            library_control = control_store.library("smoke-library")
            if not workflow_control.automation_enabled or workflow_control.queue_paused:
                raise RuntimeError("global admin control was not persisted in running state")
            if not library_control.enabled or library_control.paused:
                raise RuntimeError("library admin control was not persisted in active state")
            if job_store.active_counts().get("queued", 0) < 1:
                raise RuntimeError("manual workflow did not persist a queued job")
        finally:
            if handle is not None:
                handle.stop()
            engine.dispose()


def _settings(*, port: int, admin_control: bool = False) -> Settings:
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
    if admin_control:
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        settings.connector_dashboard_control_enabled = True
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
    workflow_sync_id = "workflow-smoke-1"
    store.create_sync_run(
        sync_id=workflow_sync_id,
        source="dashboard",
        target="job-queue",
        summary="Administrative browser smoke workflow",
        status="succeeded",
        details={
            "kind": "workflow_parent",
            "mode": "delta",
            "scope": "/",
            "repo_ids": ["smoke-library", "knowledge-base"],
            "job_ids": [],
            "trigger": "manual",
        },
    )
    store.finish_sync_run(
        sync_id=workflow_sync_id,
        status="succeeded",
        objects_checked=2,
        objects_created=0,
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


def _assert_read_only_dashboard_flow(
    page: Any,
    url: str,
    config: BrowserSmokeConfig,
) -> None:
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

    for tab in ("workflow", "syncs", "changes", "logs", "systems", "openwebui", "diagnostics"):
        page.locator(f'[data-tab="{tab}"]').click(timeout=config.timeout_ms)
        page.wait_for_selector(f"#{tab}:not([hidden])", timeout=config.timeout_ms)
        if tab == "workflow":
            _require_text(page, "#view-title", "Administration")
            _require_text(page, "#workflow", "Connector-Steuerung")
            _require_visible(page, "#admin-control-card", "connector control card")
            _wait_for_attribute(
                page,
                "#admin-control-card",
                "aria-busy",
                "false",
                config.timeout_ms,
            )
            _wait_for_text_change(page, "#admin-control-state", "-", config.timeout_ms)
            _wait_for_text(
                page,
                "#admin-control-disabled",
                "deaktiviert",
                config.timeout_ms,
            )
            _require_hidden(page, "#admin-control-actions", "read-only admin actions")
            _require_hidden(page, "#workflow-run", "read-only manual run action")
            _require_visible(page, "#workflow-run-panel", "active workflow panel")
            _require_text(page, "#workflow-run-panel", "Aktiver Lauf")
            _require_text(page, "#workflow-run-empty", "Noch kein administrativer Lauf")
            _require_attached(page, "#workflow-progress-bar", "overall progress bar")
            _require_attached(page, "#workflow-phase-list", "workflow phase list")
            _require_attached(
                page,
                "#workflow-run-libraries",
                "workflow library progress table",
            )
            _wait_for_text(page, "#workflow-summary", "nicht verfügbar", config.timeout_ms)
            _require_text(page, "#workflow-table", "Keine Einträge")
            _require_text(page, "#workflow-history-panel", "Letzte administrative Läufe")
            _require_text(page, "#workflow-history-table", "workflow-smoke-1")
            _require_text(page, "#workflow-history-table", "smoke-library")
            _require_text(page, "#workflow-history-table", "Öffnen/Steuern")
            _require_attached(
                page,
                '[data-workflow-run-id="workflow-smoke-1"]',
                "administrative run opener",
            )
            _require_text(page, "#workflow", "Fehlgeschlagene Bereinigungen")
            _wait_for_text(
                page,
                "#cleanup-outbox-summary",
                "nicht verfügbar",
                config.timeout_ms,
            )
            page.screenshot(
                path=str(config.output_dir / "dashboard-workflow.png"),
                full_page=True,
            )
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
            _require_text(page, "#openwebui-table", "AKTIONEN")

    page.select_option("#language-select", "en", timeout=config.timeout_ms)
    page.locator('[data-tab="workflow"]').click(timeout=config.timeout_ms)
    page.wait_for_selector("#workflow:not([hidden])", timeout=config.timeout_ms)
    _require_text(page, "#view-title", "Administration")
    _require_text(page, "#workflow", "Connector control")
    _require_text(page, "#workflow-run-panel", "Active run")
    _require_text(page, "#workflow-run-empty", "No administrative run selected")
    _require_text(page, "#workflow-history-panel", "Recent administrative runs")
    _wait_for_text(page, "#workflow-history-table", "Open/control", config.timeout_ms)
    _wait_for_text(
        page,
        "#admin-control-disabled",
        "disabled in this process",
        config.timeout_ms,
    )
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
    mobile_workflow_screenshot = config.output_dir / "dashboard-workflow-mobile.png"
    page.screenshot(path=str(desktop_screenshot), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    _require_visible(page, "#nav-toggle", "mobile navigation toggle")
    _require_attribute(page, "#nav-toggle", "aria-expanded", "false")
    page.locator("#nav-toggle").click(timeout=config.timeout_ms)
    _require_attribute(page, "#nav-toggle", "aria-expanded", "true")
    page.locator('[data-tab="workflow"]').click(timeout=config.timeout_ms)
    _require_attribute(page, "#nav-toggle", "aria-expanded", "false")
    page.wait_for_selector("#workflow:not([hidden])", timeout=config.timeout_ms)
    _require_visible(page, "#admin-control-card", "mobile connector control card")
    _require_visible(page, "#workflow-history-panel", "mobile administrative run history")
    _require_text(page, "#workflow-history-table", "workflow-smoke-1")
    _require_visible(page, "#workflow-run-panel", "mobile active workflow panel")
    page.screenshot(path=str(mobile_workflow_screenshot), full_page=True)
    page.locator("#nav-toggle").click(timeout=config.timeout_ms)
    _require_attribute(page, "#nav-toggle", "aria-expanded", "true")
    page.locator('[data-tab="openwebui"]').click(timeout=config.timeout_ms)
    _require_attribute(page, "#nav-toggle", "aria-expanded", "false")
    page.wait_for_selector("#openwebui:not([hidden])", timeout=config.timeout_ms)
    _wait_for_text(page, "#openwebui-metrics", "known mappings", config.timeout_ms)
    _require_text(page, "#openwebui-summary", "ready")
    _require_text(page, "#openwebui-metrics", "DATASETS")
    _require_text(page, "#openwebui-metrics", "known mappings")
    _require_text(page, "#openwebui-table", "DATASET")
    _require_text(page, "#openwebui-table", "ACTIONS")
    _require_text(page, "#openwebui-metrics", "including dry-run planned")
    _require_text(page, "#openwebui-metrics", "API fallback")
    _require_text(page, "#openwebui-metrics", "none")
    page.screenshot(path=str(mobile_screenshot), full_page=True)
    print(f"Dashboard browser smoke passed: {desktop_screenshot}")
    print(f"Dashboard browser smoke passed: {mobile_workflow_screenshot}")
    print(f"Dashboard browser smoke passed: {mobile_screenshot}")


def _assert_active_admin_flow(page: Any, url: str, config: BrowserSmokeConfig) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=config.timeout_ms)
    page.wait_for_selector("#workflow:not([hidden])", timeout=config.timeout_ms)
    _wait_for_attribute(
        page,
        "#admin-control-card",
        "aria-busy",
        "false",
        config.timeout_ms,
    )
    _wait_for_text(page, "#admin-control-state", "aktiv", config.timeout_ms)
    _wait_for_text(page, "#admin-queue-state", "freigegeben", config.timeout_ms)
    _require_visible(page, "#admin-control-actions", "active admin actions")
    _require_hidden(page, "#admin-control-disabled", "active control warning")
    _wait_for_text(page, "#workflow-table", "smoke-library", config.timeout_ms)

    page.locator("#admin-pause").click(timeout=config.timeout_ms)
    _wait_for_text(page, "#admin-control-state", "pausiert", config.timeout_ms)
    _wait_for_text(page, "#admin-queue-state", "pausiert", config.timeout_ms)
    page.locator("#admin-resume").click(timeout=config.timeout_ms)
    _wait_for_text(page, "#admin-control-state", "aktiv", config.timeout_ms)
    _wait_for_text(page, "#admin-queue-state", "freigegeben", config.timeout_ms)

    library_row = _workflow_library_row(page)
    library_row.get_by_role(
        "button",
        name="Pausieren: Installationshandbuch",
        exact=True,
    ).click(timeout=config.timeout_ms)
    _wait_for_text(page, "#workflow-table", "pausiert", config.timeout_ms)
    library_row = _workflow_library_row(page)
    library_row.get_by_role(
        "button",
        name="Fortsetzen: Installationshandbuch",
        exact=True,
    ).click(timeout=config.timeout_ms)
    _wait_for_text(page, "#workflow-table", "aktiv", config.timeout_ms)

    library_row = _workflow_library_row(page)
    library_row.locator('input[type="checkbox"]').check(timeout=config.timeout_ms)
    _wait_for_enabled(page, "#workflow-run", config.timeout_ms)
    page.locator("#workflow-run").click(timeout=config.timeout_ms)

    page.wait_for_selector("#workflow-progress:not([hidden])", timeout=config.timeout_ms)
    _wait_for_text(page, "#workflow-progress-percent", "0 %", config.timeout_ms)
    _wait_for_text(page, "#workflow-progress-phase", "files", config.timeout_ms)
    _wait_for_text(page, "#workflow-run-libraries", "Installationshandbuch", config.timeout_ms)
    _wait_for_text(page, "#workflow-table", "Noch keine Parsing-Daten", config.timeout_ms)
    _require_visible(page, "#workflow-phase-list", "manual run phase progress")
    run_id = _wait_for_workflow_run_id(page, config.timeout_ms)

    page.locator("#workflow-load").click(timeout=config.timeout_ms)
    page.wait_for_selector(
        f'[data-workflow-run-id="{run_id}"]',
        state="attached",
        timeout=config.timeout_ms,
    )
    _wait_for_text(
        page,
        "#workflow-history-summary",
        "2 administrative Läufe",
        config.timeout_ms,
    )
    _wait_for_count_at_least(
        page,
        "#workflow-history-table [data-workflow-run-id]",
        2,
        config.timeout_ms,
    )
    _require_text(page, "#workflow-history-table", "smoke-library")
    _require_text(page, "#workflow-history-table", "Öffnen/Steuern")

    desktop_screenshot = config.output_dir / "dashboard-admin-active-desktop.png"
    mobile_screenshot = config.output_dir / "dashboard-admin-active-mobile.png"
    page.screenshot(path=str(desktop_screenshot), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    _require_visible(page, "#workflow-progress", "mobile manual run progress")
    _require_visible(page, "#workflow-history-panel", "mobile administrative run history")
    _require_attached(page, "#workflow-run-libraries", "mobile run library progress")
    page.screenshot(path=str(mobile_screenshot), full_page=True)
    print(f"Dashboard active admin smoke passed: {desktop_screenshot}")
    print(f"Dashboard active admin smoke passed: {mobile_screenshot}")


def _workflow_library_row(page: Any) -> Any:
    return page.locator("#workflow-table tbody tr").filter(has_text="smoke-library").first


def _require_visible(page: Any, selector: str, description: str) -> None:
    locator = page.locator(selector).first
    if not locator.is_visible(timeout=5_000):
        raise RuntimeError(f"{description} is not visible")


def _require_hidden(page: Any, selector: str, description: str) -> None:
    locator = page.locator(selector).first
    if not locator.is_hidden(timeout=5_000):
        raise RuntimeError(f"{description} is not hidden")


def _require_attached(page: Any, selector: str, description: str) -> None:
    if page.locator(selector).count() == 0:
        raise RuntimeError(f"{description} is not attached")


def _wait_for_text_change(page: Any, selector: str, initial_text: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_text = ""
    while time.monotonic() < deadline:
        current_text = _poll_inner_text(page, selector)
        if current_text is None:
            time.sleep(0.2)
            continue
        last_text = current_text.strip()
        if last_text and last_text != initial_text:
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} did not update before timeout: {last_text!r}")


def _wait_for_text(page: Any, selector: str, expected: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_text = ""
    while time.monotonic() < deadline:
        current_text = _poll_inner_text(page, selector)
        if current_text is None:
            time.sleep(0.2)
            continue
        last_text = current_text
        if expected in last_text:
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} did not contain {expected!r} before timeout: {last_text!r}")


def _wait_for_enabled(page: Any, selector: str, timeout_ms: int) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if page.locator(selector).first.is_enabled(timeout=1_000):
            return
        time.sleep(0.2)
    raise RuntimeError(f"{selector} did not become enabled before timeout")


def _wait_for_count_at_least(
    page: Any,
    selector: str,
    minimum: int,
    timeout_ms: int,
) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    count = 0
    while time.monotonic() < deadline:
        count = page.locator(selector).count()
        if count >= minimum:
            return
        time.sleep(0.2)
    raise RuntimeError(
        f"{selector} did not reach {minimum} elements before timeout: {count}"
    )


def _wait_for_workflow_run_id(page: Any, timeout_ms: int) -> str:
    deadline = time.monotonic() + (timeout_ms / 1000)
    run_id = ""
    while time.monotonic() < deadline:
        current_text = _poll_inner_text(page, "#workflow-run-summary")
        if current_text is None:
            time.sleep(0.2)
            continue
        run_id = current_text.strip()
        if run_id.startswith(("workflow-", "sync-workflow-")):
            return run_id
        time.sleep(0.2)
    raise RuntimeError(f"manual workflow run id did not appear before timeout: {run_id!r}")


def _poll_inner_text(page: Any, selector: str) -> str | None:
    try:
        return str(page.locator(selector).first.inner_text(timeout=1_000))
    except Exception as exc:
        if exc.__class__.__module__.startswith("playwright"):
            return None
        raise


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


def _wait_for_attribute(
    page: Any,
    selector: str,
    attribute: str,
    expected: str,
    timeout_ms: int,
) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000)
    value: str | None = None
    while time.monotonic() < deadline:
        value = page.locator(selector).first.get_attribute(attribute, timeout=1_000)
        if value == expected:
            return
        time.sleep(0.2)
    raise RuntimeError(
        f"{selector} {attribute} did not become {expected!r} before timeout: {value!r}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
