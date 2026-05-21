from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

import structlog
import typer

from seafile_ragflow_connector.app.logging import configure_logging
from seafile_ragflow_connector.app.runtime import (
    Runtime,
    build_dashboard_store,
    build_runtime,
    check_database,
    check_redis,
)
from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.server import (
    DashboardBindError,
    DashboardContext,
    DashboardServerHandle,
    serve_dashboard_forever,
    start_dashboard_server,
)
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.jobs.scheduler import PeriodicTask, SimpleScheduler
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner
from seafile_ragflow_connector.persistence.db import init_database

app = typer.Typer(help="Offline-first Seafile to RAGFlow connector")
PROCESS_STARTED_AT = datetime.now(UTC)
OpenWebUIMode = Literal["disabled", "dry-run", "sync", "repair"]


def _bootstrap() -> Settings:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        settings.log_format,
        dashboard_store=build_dashboard_store(settings),
    )
    return settings


@app.command()
def init_db() -> None:
    """Create or update connector state tables."""
    settings = _bootstrap()
    init_database(settings.database_url)
    typer.echo("database initialized")


@app.command("check-live")
def check_live() -> None:
    """Check live dependencies without mutating Seafile or RAGFlow."""
    settings = _bootstrap()
    check_database(settings.database_url)
    check_redis(settings.redis_url)
    runtime = build_runtime(settings)
    try:
        libraries = _retry_until(
            lambda: runtime.admin_client.list_libraries(per_page=1),
            "Seafile",
        )
        templates = _retry_until(
            lambda: runtime.ragflow_client.list_datasets(
                name=settings.ragflow_template_dataset_name,
            ),
            "RAGFlow",
        )
        typer.echo(
            {
                "database": "ok",
                "redis": "ok",
                "seafile_admin_libraries_visible": len(libraries),
                "ragflow_template_found": bool(templates),
                "template_name": settings.ragflow_template_dataset_name,
            }
        )
    finally:
        runtime.close()


@app.command("sync-once")
def sync_once(
    wait_parse_seconds: Annotated[
        int,
        typer.Option(
            "--wait-parse-seconds",
            help="Poll parse status for this many seconds after upload work.",
        ),
    ] = 0,
) -> None:
    """Run one full discovery and reconciliation pass."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        summary = runtime.orchestrator.sync_once()
        if wait_parse_seconds > 0:
            _wait_for_parse(runtime, wait_parse_seconds)
        payload: dict[str, Any] = dict(summary.__dict__)
        openwebui_summary = _sync_openwebui_if_enabled(runtime)
        if openwebui_summary is not None:
            payload["openwebui"] = openwebui_summary
        typer.echo(payload)
    finally:
        runtime.close()


@app.command("openwebui-sync-once")
def openwebui_sync_once(
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help="Override OpenWebUI sync mode: disabled, dry-run, sync or repair.",
        ),
    ] = None,
) -> None:
    """Run one OpenWebUI synchronization pass."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        if runtime.openwebui_sync_service is None:
            typer.echo({"status": "disabled"})
            return
        selected_mode = mode or settings.openwebui_effective_sync_mode
        if selected_mode not in {"disabled", "dry-run", "sync", "repair"}:
            raise typer.BadParameter("mode must be disabled, dry-run, sync or repair")
        summary = runtime.openwebui_sync_service.sync_once(
            mode_override=cast(OpenWebUIMode, selected_mode)
        )
        typer.echo(summary.__dict__)
    finally:
        runtime.close()


@app.command()
def controller() -> None:
    """Run the discovery and delta scheduling loop."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)
    dashboard_handle: DashboardServerHandle | None = None
    dashboard_required = (
        settings.connector_dashboard_enabled
        or settings.openwebui_effective_sync_mode != "disabled"
    )
    if dashboard_required and runtime.dashboard_store is not None:
        try:
            dashboard_handle = start_dashboard_server(
                DashboardContext(runtime.dashboard_store, settings, PROCESS_STARTED_AT)
            )
        except DashboardBindError as exc:
            log.error("dashboard.bind_failed", error=str(exc))
            runtime.close()
            raise typer.Exit(1) from exc
        log.info(
            "dashboard.started",
            host=settings.connector_dashboard_host,
            port=settings.connector_dashboard_port,
        )

    def discover() -> None:
        specs = _discover_job_specs(runtime)
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("controller.discovery.enqueued", count=len(specs))

    def delta() -> None:
        stale = runtime.job_store.requeue_stale_running_jobs()
        log.info("controller.stale_jobs.requeued", count=stale)

    def template() -> None:
        specs = [
            JobSpec(JobType.REFRESH_DATASET_SETTINGS, repo_id=library.repo_id)
            for library in runtime.orchestrator.discover_libraries()
        ]
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("controller.settings_refresh.enqueued", count=len(specs))

    def openwebui() -> None:
        if runtime.openwebui_sync_service is None:
            return
        runtime.openwebui_sync_service.sync_once()

    if (
        settings.openwebui_sync_on_startup
        and settings.openwebui_effective_sync_mode != "disabled"
        and runtime.openwebui_sync_service is not None
    ):
        openwebui()

    tasks = [
        PeriodicTask("discovery", settings.discovery_interval_seconds, discover),
        PeriodicTask("delta", settings.delta_sync_interval_seconds, delta),
        PeriodicTask("template", settings.ragflow_template_refresh_seconds, template),
    ]
    if settings.openwebui_effective_sync_mode != "disabled":
        tasks.append(PeriodicTask("openwebui", settings.openwebui_sync_interval_seconds, openwebui))
    scheduler = SimpleScheduler(tasks)
    log.info("controller.started")
    try:
        scheduler.run_forever()
    finally:
        if dashboard_handle is not None:
            dashboard_handle.stop()
        runtime.close()


@app.command()
def worker() -> None:
    """Run a connector worker process."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)
    log.info("worker.started")
    runtime.job_store.requeue_stale_running_jobs()
    WorkerRunner(
        runtime.job_store,
        handlers=_build_job_handlers(runtime),
        signal_queue=runtime.signal_queue,
    ).run_forever()


@app.command()
def reconciler() -> None:
    """Run the low-priority reconciliation loop."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)

    def reconcile() -> None:
        summary = runtime.orchestrator.sync_once()
        log.info("reconciler.synced", **summary.__dict__)

    scheduler = SimpleScheduler(
        [PeriodicTask("reconcile", settings.reconcile_interval_seconds, reconcile)]
    )
    log.info("reconciler.started")
    scheduler.run_forever()


@app.command("check-config")
def check_config() -> None:
    """Load and validate configuration without contacting external services."""
    settings = _bootstrap()
    typer.echo(
        {
            "app_env": settings.app_env,
            "seafile_base_url": settings.seafile_base_url,
            "ragflow_base_url": settings.ragflow_base_url,
            "allow_unknown_text_files": settings.allow_unknown_text_files,
            "dataset_settings_source": settings.dataset_settings_source,
            "connector_dashboard_enabled": settings.connector_dashboard_enabled,
            "connector_dashboard_host": settings.connector_dashboard_host,
            "connector_dashboard_port": settings.connector_dashboard_port,
            "openwebui_integration_enabled": settings.openwebui_integration_enabled,
            "openwebui_sync_mode": settings.openwebui_effective_sync_mode,
            "openwebui_base_url": settings.openwebui_base_url,
            "openwebui_create_tools": settings.openwebui_create_tools,
            "openwebui_create_pipes": settings.openwebui_create_pipes,
        }
    )


@app.command()
def dashboard() -> None:
    """Run the read-only HTTP dashboard as a foreground process."""
    settings = _bootstrap()
    log = structlog.get_logger(__name__)
    if not settings.connector_dashboard_enabled:
        log.info("dashboard.disabled")
        typer.echo("dashboard disabled; set CONNECTOR_DASHBOARD_ENABLED=true to start it")
        return
    init_database(settings.database_url)
    store = build_dashboard_store(settings)
    if store is None:
        typer.echo("dashboard disabled; set CONNECTOR_DASHBOARD_ENABLED=true to start it")
        return
    try:
        serve_dashboard_forever(DashboardContext(store, settings, PROCESS_STARTED_AT))
    except DashboardBindError as exc:
        log.error("dashboard.bind_failed", error=str(exc))
        raise typer.Exit(1) from exc


def _enqueue_specs(
    job_store: JobStore,
    signal_queue: JobSignalQueue,
    specs: list[JobSpec],
) -> None:
    log = structlog.get_logger(__name__)
    for spec in specs:
        job_id = job_store.enqueue(spec)
        try:
            signal_queue.signal(job_id)
        except Exception as exc:
            log.warning("job.signal_failed", job_id=job_id, job_type=spec.job_type, error=str(exc))


def _retry_until(action: Callable[[], Any], label: str, timeout_seconds: int = 180) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return action()
        except Exception as exc:
            last_error = exc
            time.sleep(5)
    if last_error:
        raise RuntimeError(
            f"{label} did not become ready within {timeout_seconds}s"
        ) from last_error
    raise RuntimeError(f"{label} did not become ready within {timeout_seconds}s")


def _build_job_handlers(runtime: Runtime) -> dict[JobType, Callable[[JobSpec], None]]:
    def ensure_dataset(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        runtime.orchestrator.ensure_dataset_for_repo(repo_id)

    def sync_full(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        scope = str(spec.payload.get("scope") or spec.file_path or "/")
        runtime.orchestrator.sync_library_full(repo_id, scope=scope)

    def upload_file(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        if not spec.file_path:
            raise ValueError("UPLOAD_FILE requires file_path")
        dataset_id = runtime.orchestrator.ensure_dataset_for_repo(repo_id)
        runtime.orchestrator.sync_file(repo_id, dataset_id, spec.file_path, force=True)

    def delete_file(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        if not spec.file_path:
            raise ValueError("DELETE_FILE requires file_path")
        dataset_id = runtime.orchestrator.ensure_dataset_for_repo(repo_id)
        if bool(spec.payload.get("recursive")):
            runtime.orchestrator.delete_missing_files(
                repo_id,
                dataset_id,
                set(),
                scope=spec.file_path,
            )
            return
        runtime.orchestrator.delete_file(repo_id, dataset_id, spec.file_path)

    def parse_documents(spec: JobSpec) -> None:
        dataset_id = str(spec.payload["dataset_id"])
        document_ids = [str(value) for value in spec.payload["document_ids"]]
        runtime.ragflow_client.parse_documents(dataset_id, document_ids)

    def check_parse(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        dataset_id = str(
            spec.payload.get("dataset_id")
            or runtime.orchestrator.ensure_dataset_for_repo(repo_id)
        )
        runtime.orchestrator.check_parse_status(repo_id, dataset_id)

    def sync_openwebui(spec: JobSpec) -> None:
        if runtime.openwebui_sync_service is None:
            return
        mode = spec.payload.get("mode")
        if mode is not None and str(mode) not in {"disabled", "dry-run", "sync", "repair"}:
            raise ValueError("SYNC_OPENWEBUI mode must be disabled, dry-run, sync or repair")
        mode_override = cast(OpenWebUIMode, str(mode)) if mode else None
        runtime.openwebui_sync_service.sync_once(mode_override=mode_override)

    return {
        JobType.DISCOVER_LIBRARIES: lambda spec: _enqueue_specs(
            runtime.job_store,
            runtime.signal_queue,
            _discover_job_specs(runtime),
        ),
        JobType.ENSURE_RAGFLOW_DATASET: ensure_dataset,
        JobType.REFRESH_DATASET_SETTINGS: ensure_dataset,
        JobType.SYNC_LIBRARY_FULL: sync_full,
        JobType.SYNC_LIBRARY_DELTA: sync_full,
        JobType.UPLOAD_FILE: upload_file,
        JobType.DELETE_FILE: delete_file,
        JobType.PARSE_DOCUMENTS: parse_documents,
        JobType.REPARSE_DOCUMENTS: parse_documents,
        JobType.CHECK_PARSE_STATUS: check_parse,
        JobType.RECONCILE_LIBRARY: sync_full,
        JobType.RECONCILE_RAGFLOW_DATASET: check_parse,
        JobType.SYNC_OPENWEBUI: sync_openwebui,
    }


def _discover_job_specs(runtime: Runtime) -> list[JobSpec]:
    specs = runtime.orchestrator.discover_job_specs()
    if _openwebui_sync_enabled(runtime):
        specs.append(JobSpec(JobType.SYNC_OPENWEBUI))
    return specs


def _sync_openwebui_if_enabled(runtime: Runtime) -> dict[str, Any] | None:
    if not _openwebui_sync_enabled(runtime) or runtime.openwebui_sync_service is None:
        return None
    summary = runtime.openwebui_sync_service.sync_once()
    return dict(summary.__dict__)


def _openwebui_sync_enabled(runtime: Runtime) -> bool:
    return runtime.settings.openwebui_effective_sync_mode != "disabled"


def _require_repo_id(spec: JobSpec) -> str:
    if not spec.repo_id:
        msg = f"{spec.job_type} requires repo_id"
        raise ValueError(msg)
    return spec.repo_id


def _wait_for_parse(runtime: Runtime, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        active = False
        for library in runtime.orchestrator.discover_libraries():
            dataset_id = runtime.orchestrator.ensure_dataset_for_repo(library.repo_id)
            updated = runtime.orchestrator.check_parse_status(library.repo_id, dataset_id)
            if updated:
                documents = runtime.ragflow_client.list_documents(dataset_id)
                active = any(
                    document.get("run") in {"RUNNING", "UNSTART"} for document in documents
                )
        if not active:
            return
        time.sleep(5)


if __name__ == "__main__":
    app()
