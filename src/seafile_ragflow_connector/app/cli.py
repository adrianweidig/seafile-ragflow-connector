from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
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
from seafile_ragflow_connector.clients import OpenWebUIClient
from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.server import (
    DashboardBindError,
    DashboardContext,
    DashboardServerHandle,
    serve_dashboard_forever,
    start_dashboard_server,
)
from seafile_ragflow_connector.demo.lifecycle import (
    bootstrap_demo_environment,
    cleanup_demo_environment,
    dumps_summary,
    write_demo_testset,
)
from seafile_ragflow_connector.i18n import localizer_for, t
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.jobs.scheduler import PeriodicTask, SimpleScheduler
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner
from seafile_ragflow_connector.persistence.db import init_database
from seafile_ragflow_connector.sync.target_cleanup import LibrarySourceLike, TargetCleanupService

app = typer.Typer(help=t("cli.app_help"))
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
    """Connector-State-Tabellen anlegen oder aktualisieren."""
    settings = _bootstrap()
    init_database(settings.database_url)
    typer.echo(localizer_for(settings).text("cli.init_db.done"))


@app.command("check-live")
def check_live(
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Live-Abhängigkeiten prüfen, ohne Seafile oder RAGFlow zu verändern."""
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
        _emit_payload(
            {
                "database": "ok",
                "redis": "ok",
                "seafile_admin_libraries_visible": len(libraries),
                "ragflow_template_found": bool(templates),
                "template_name": settings.ragflow_template_dataset_name,
            },
            json_output=json_output,
        )
    finally:
        runtime.close()


@app.command("sync-once")
def sync_once(
    wait_parse_seconds: Annotated[
        int,
        typer.Option(
            "--wait-parse-seconds",
            help=t("cli.sync_once.wait_parse"),
        ),
    ] = 0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Einen vollständigen Discovery- und Sync-Lauf ausführen."""
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
        _emit_payload(payload, json_output=json_output)
    finally:
        runtime.close()


@app.command("cleanup-orphans")
def cleanup_orphans(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help=t("cli.cleanup_orphans.execute"),
        ),
    ] = False,
    run_sync: Annotated[
        bool,
        typer.Option(
            "--run-sync",
            help=t("cli.cleanup_orphans.run_sync"),
        ),
    ] = False,
    wait_parse_seconds: Annotated[
        int,
        typer.Option(
            "--wait-parse-seconds",
            help=t("cli.sync_once.wait_parse"),
        ),
    ] = 0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Verwaiste connector-eigene RAGFlow-/OpenWebUI-Artefakte planen oder löschen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    extra_openwebui_client: OpenWebUIClient | None = None
    try:
        current_libraries = runtime.orchestrator.discover_libraries()
        openwebui_client = runtime.openwebui_client
        if openwebui_client is None and settings.openwebui_admin_api_key:
            extra_openwebui_client = OpenWebUIClient(
                settings.openwebui_base_url,
                settings.openwebui_admin_api_key,
                timeout=settings.openwebui_request_timeout_seconds,
                verify=settings.openwebui_httpx_verify,
            )
            openwebui_client = extra_openwebui_client
        cleanup_service = TargetCleanupService(
            session_factory=runtime.orchestrator.session_factory,
            ragflow_client=runtime.ragflow_client,
            openwebui_client=openwebui_client,
            openwebui_namespace=settings.openwebui_function_namespace,
        )
        summary = cleanup_service.cleanup(
            cast(Sequence[LibrarySourceLike], current_libraries),
            execute=execute,
        )
        payload: dict[str, Any] = dict(summary.__dict__)
        if execute and run_sync:
            sync_summary = runtime.orchestrator.sync_once()
            if wait_parse_seconds > 0:
                _wait_for_parse(runtime, wait_parse_seconds)
            payload["sync"] = dict(sync_summary.__dict__)
            openwebui_summary = _sync_openwebui_if_enabled(runtime)
            if openwebui_summary is not None:
                payload["openwebui"] = openwebui_summary
        _emit_payload(payload, json_output=json_output)
    finally:
        if extra_openwebui_client is not None:
            extra_openwebui_client.close()
        runtime.close()


@app.command("openwebui-sync-once")
def openwebui_sync_once(
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help=t("cli.openwebui.mode"),
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Einen OpenWebUI-Synchronisationslauf ausführen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        if runtime.openwebui_sync_service is None:
            _emit_payload({"status": "disabled"}, json_output=json_output)
            return
        selected_mode = mode or settings.openwebui_effective_sync_mode
        if selected_mode not in {"disabled", "dry-run", "sync", "repair"}:
            raise typer.BadParameter(localizer_for(settings).text("cli.openwebui.mode_error"))
        summary = runtime.openwebui_sync_service.sync_once(
            mode_override=cast(OpenWebUIMode, selected_mode)
        )
        _emit_payload(summary.__dict__, json_output=json_output)
    finally:
        runtime.close()


@app.command("demo-fixtures")
def demo_fixtures(
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help=t("cli.demo.output_dir"),
        ),
    ] = Path("/cache/demo-fixtures"),
) -> None:
    """Reproduzierbare lokale Demo-Dateien erzeugen, ohne Dienste zu kontaktieren."""
    summary = {"fixtures": write_demo_testset(output_dir)}
    typer.echo(dumps_summary(summary))


@app.command("demo-cleanup")
def demo_cleanup(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help=t("cli.demo.execute_cleanup"),
        ),
    ] = False,
) -> None:
    """Nur klar benannte lokale Demo-Artefakte in Seafile, RAGFlow und OpenWebUI löschen."""
    settings = _bootstrap()
    typer.echo(dumps_summary(cleanup_demo_environment(settings, execute=execute)))


@app.command("demo-bootstrap")
def demo_bootstrap(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help=(
                t("cli.demo.execute_bootstrap")
            ),
        ),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help=t("cli.demo.output_dir"),
        ),
    ] = Path("/cache/demo-fixtures"),
    run_sync: Annotated[
        bool,
        typer.Option("--run-sync", help=t("cli.demo.run_sync")),
    ] = False,
    wait_parse_seconds: Annotated[
        int,
        typer.Option(
            "--wait-parse-seconds",
            help=t("cli.sync_once.wait_parse"),
        ),
    ] = 0,
) -> None:
    """Kanonische Demo-Libraries erstellen und optional den Connector-Sync-Pfad ausführen."""
    settings = _bootstrap()
    summary = bootstrap_demo_environment(settings, output_dir=output_dir, execute=execute)
    if execute and run_sync:
        runtime = build_runtime(settings)
        try:
            sync_summary = runtime.orchestrator.sync_once()
            if wait_parse_seconds > 0:
                _wait_for_parse(runtime, wait_parse_seconds)
            summary["sync"] = dict(sync_summary.__dict__)
            openwebui_summary = _sync_openwebui_if_enabled(runtime)
            if openwebui_summary is not None:
                summary["openwebui"] = openwebui_summary
        finally:
            runtime.close()
    typer.echo(dumps_summary(summary))


@app.command()
def controller() -> None:
    """Discovery- und Delta-Scheduling-Loop ausführen."""
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
    log.info(
        "controller.started",
        intervals_seconds={task.name: task.interval_seconds for task in tasks},
    )
    try:
        scheduler.run_forever()
    finally:
        if dashboard_handle is not None:
            dashboard_handle.stop()
        runtime.close()


@app.command()
def worker() -> None:
    """Connector-Worker-Prozess ausführen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)
    log.info("worker.started")
    try:
        runtime.job_store.requeue_stale_running_jobs()
        WorkerRunner(
            runtime.job_store,
            handlers=_build_job_handlers(runtime),
            signal_queue=runtime.signal_queue,
        ).run_forever()
    finally:
        runtime.close()


@app.command()
def reconciler() -> None:
    """Low-Priority-Reconciliation-Loop ausführen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)

    def reconcile() -> None:
        summary = runtime.orchestrator.sync_once()
        log.info("reconciler.synced", **summary.__dict__)

    scheduler = SimpleScheduler(
        [PeriodicTask("reconcile", settings.reconcile_interval_seconds, reconcile)]
    )
    log.info("reconciler.started", interval_seconds=settings.reconcile_interval_seconds)
    try:
        scheduler.run_forever()
    finally:
        runtime.close()


@app.command("check-config")
def check_config(
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Konfiguration laden und validieren, ohne externe Dienste zu kontaktieren."""
    settings = _bootstrap()
    _emit_payload(
        {
            "app_env": settings.app_env,
            "connector_language": localizer_for(settings).language,
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
        },
        json_output=json_output,
    )


@app.command()
def dashboard() -> None:
    """Lesendes HTTP-Dashboard als Vordergrundprozess starten."""
    settings = _bootstrap()
    l10n = localizer_for(settings)
    log = structlog.get_logger(__name__)
    if not settings.connector_dashboard_enabled:
        log.info("dashboard.disabled")
        typer.echo(l10n.text("cli.dashboard.disabled"))
        return
    init_database(settings.database_url)
    store = build_dashboard_store(settings)
    if store is None:
        typer.echo(l10n.text("cli.dashboard.disabled"))
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


def _emit_payload(payload: dict[str, Any], *, json_output: bool = False) -> None:
    typer.echo(_format_payload(payload, json_output=json_output))


def _format_payload(payload: dict[str, Any], *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    return str(payload)


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
            t("cli.check_live.not_ready", label=label, seconds=timeout_seconds)
        ) from last_error
    raise RuntimeError(t("cli.check_live.not_ready", label=label, seconds=timeout_seconds))


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
            raise ValueError(t("cli.jobs.upload_requires_file"))
        dataset_id = runtime.orchestrator.ensure_dataset_for_repo(repo_id)
        runtime.orchestrator.sync_file(repo_id, dataset_id, spec.file_path, force=True)

    def delete_file(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        if not spec.file_path:
            raise ValueError(t("cli.jobs.delete_requires_file"))
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
            raise ValueError(t("cli.jobs.sync_mode_error"))
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
        msg = t("cli.jobs.requires_repo_id", job_type=spec.job_type)
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
