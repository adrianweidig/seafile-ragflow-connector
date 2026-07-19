from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Never, cast

import structlog
import typer
from pydantic import ValidationError
from sqlalchemy import select

from seafile_ragflow_connector.app.logging import configure_logging
from seafile_ragflow_connector.app.runtime import (
    Runtime,
    build_dashboard_store,
    build_runtime,
    check_database,
    check_redis,
)
from seafile_ragflow_connector.clients import OpenWebUIClient
from seafile_ragflow_connector.config import get_search_service_settings, get_settings
from seafile_ragflow_connector.config.inventory import (
    configured_limited_settings,
    settings_inventory,
    settings_inventory_summary,
)
from seafile_ragflow_connector.config.settings import SearchServiceSettings, Settings
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
from seafile_ragflow_connector.domain.ragflow_defaults import build_search_answer_chat_payload
from seafile_ragflow_connector.domain.ragflow_search_settings import (
    config_from_settings,
    ensure_search_template,
)
from seafile_ragflow_connector.i18n import localizer_for, t
from seafile_ragflow_connector.jobs.context import (
    JobDeferredError,
    current_job_id,
    job_cancellation_requested,
)
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.jobs.scheduler import PeriodicTask, SimpleScheduler
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
from seafile_ragflow_connector.persistence.db import (
    database_revisions,
    get_session_factory,
    init_database,
)
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
from seafile_ragflow_connector.search.server import SearchServiceContext, serve_search_forever
from seafile_ragflow_connector.security.access_control import ACLSnapshotService
from seafile_ragflow_connector.sync.orchestrator import SyncCancelledError
from seafile_ragflow_connector.sync.target_cleanup import LibrarySourceLike, TargetCleanupService
from seafile_ragflow_connector.utils.redaction import redact_mapping

app = typer.Typer(help=t("cli.app_help"))
library_app = typer.Typer(help=t("cli.library.help"))
jobs_app = typer.Typer(help=t("cli.jobs.help"))
cleanup_app = typer.Typer(help=t("cli.cleanup.help"))
app.add_typer(library_app, name="library")
app.add_typer(jobs_app, name="jobs")
app.add_typer(cleanup_app, name="cleanup")
PROCESS_STARTED_AT = datetime.now(UTC)
OpenWebUIMode = Literal["disabled", "dry-run", "sync", "repair"]


def _bootstrap() -> Settings:
    try:
        settings = get_settings()
    except ValidationError as exc:
        _exit_for_invalid_configuration(exc)
    configure_logging(
        settings.log_level,
        settings.log_format,
        dashboard_store=build_dashboard_store(settings),
    )
    return settings


def _bootstrap_search() -> SearchServiceSettings:
    try:
        settings = get_search_service_settings()
    except ValidationError as exc:
        _exit_for_invalid_configuration(exc)
    configure_logging(settings.log_level, settings.log_format)
    return settings


def _exit_for_invalid_configuration(exc: ValidationError) -> Never:
    details: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        details.append(f"{location}: {message}" if location else message)
    typer.echo(
        t("cli.configuration_invalid", details="; ".join(details)),
        err=True,
    )
    raise typer.Exit(2)


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
    current_revision, expected_revision = database_revisions(settings.database_url)
    runtime = build_runtime(settings, initialize_database=False)
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
                "database_revision_current": current_revision,
                "database_revision_expected": expected_revision,
                "database_revision_match": current_revision == expected_revision,
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
        acl_summary = _sync_acl_snapshot_if_enabled(runtime)
        if acl_summary is not None:
            payload["acl_snapshot"] = acl_summary
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
        current_libraries = runtime.orchestrator.discover_libraries(full_visibility=True)
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
        or settings.authz_api_enabled
    )
    if dashboard_required and runtime.dashboard_store is not None:
        try:
            dashboard_handle = start_dashboard_server(
                DashboardContext(
                    runtime.dashboard_store,
                    settings,
                    PROCESS_STARTED_AT,
                    orchestrator=runtime.orchestrator,
                    openwebui_sync_service=runtime.openwebui_sync_service,
                    job_store=runtime.job_store,
                    signal_queue=runtime.signal_queue,
                    control_store=runtime.orchestrator.admin_control_store,
                )
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
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        specs = _discover_job_specs(runtime)
        if not _automatic_cycle_continues_guarded(runtime, log):
            return
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("controller.discovery.enqueued", count=len(specs))

    def delta() -> None:
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        specs = runtime.orchestrator.discover_job_specs()
        if not _automatic_cycle_continues_guarded(runtime, log):
            return
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("controller.delta.enqueued", count=len(specs))

    def maintenance() -> None:
        _maintain_job_queue(runtime, settings, log)

    def template() -> None:
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        libraries = runtime.orchestrator.discover_libraries(trigger="automatic")
        if not _automatic_cycle_continues_guarded(runtime, log):
            return
        specs = [
            JobSpec(JobType.REFRESH_DATASET_SETTINGS, repo_id=library.repo_id)
            for library in libraries
        ]
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("controller.settings_refresh.enqueued", count=len(specs))

    def search_template() -> None:
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        if not settings.ragflow_search_template_enabled:
            _ensure_search_answer_chat(
                runtime,
                log,
                checkpoint=lambda: _automatic_cycle_continues_guarded(runtime, log),
            )
            return
        resolved = ensure_search_template(
            runtime.ragflow_client,
            config_from_settings(settings),
        )
        log.info(
            "ragflow.search_template.ready",
            source=resolved.source,
            template_name=resolved.name,
            template_id=resolved.template_id,
            warnings=list(resolved.warnings),
        )
        if not _automatic_cycle_continues_guarded(runtime, log):
            return
        _ensure_search_answer_chat(
            runtime,
            log,
            checkpoint=lambda: _automatic_cycle_continues_guarded(runtime, log),
        )

    def openwebui() -> None:
        if (
            not _automatic_cycles_enabled_guarded(runtime, log)
            or not _openwebui_sync_enabled(runtime)
            or runtime.openwebui_sync_service is None
        ):
            return
        _enqueue_specs(
            runtime.job_store,
            runtime.signal_queue,
            [JobSpec(JobType.SYNC_OPENWEBUI, payload={"trigger": "automatic"})],
        )

    def acl_snapshot() -> None:
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        summary = _sync_acl_snapshot(
            runtime,
            checkpoint=lambda: _automatic_cycle_continues_guarded(runtime, log),
        )
        log.info("controller.acl_snapshot.synced", **summary)

    if _automatic_cycles_enabled_guarded(runtime, log):
        search_template()
        if (
            settings.openwebui_sync_on_startup
            and settings.openwebui_effective_sync_mode != "disabled"
            and runtime.openwebui_sync_service is not None
        ):
            openwebui()

    tasks = [
        PeriodicTask("discovery", settings.discovery_interval_seconds, discover),
        PeriodicTask("delta", settings.delta_sync_interval_seconds, delta),
        PeriodicTask("maintenance", settings.delta_sync_interval_seconds, maintenance),
        PeriodicTask("template", settings.ragflow_template_refresh_seconds, template),
        PeriodicTask(
            "search_template",
            settings.ragflow_search_template_refresh_seconds,
            search_template,
        ),
    ]
    if settings.search_acl_sync_enabled:
        tasks.append(
            PeriodicTask(
                "acl_snapshot",
                settings.search_acl_sync_interval_seconds,
                acl_snapshot,
            )
        )
    if settings.openwebui_effective_sync_mode != "disabled":
        tasks.append(PeriodicTask("openwebui", settings.openwebui_sync_interval_seconds, openwebui))
    scheduler = SimpleScheduler(tasks)
    try:
        control_state = runtime.orchestrator.admin_control_store.workflow().state
    except Exception as exc:
        log.warning(
            "controller.control_state_failed",
            error_class=type(exc).__name__,
        )
    else:
        log.info(
            "controller.control_state",
            configured_initial_state=settings.connector_automation_initial_state,
            effective_state=control_state,
        )
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
        runtime.job_store.requeue_stale_running_jobs(
            older_than_seconds=settings.job_lease_seconds
        )
        WorkerRunner(
            runtime.job_store,
            handlers=_build_job_handlers(runtime),
            signal_queue=runtime.signal_queue,
            heartbeat_seconds=settings.job_heartbeat_seconds,
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
        if not _automatic_cycles_enabled_guarded(runtime, log):
            return
        specs = [
            JobSpec(JobType.RECONCILE_LIBRARY, repo_id=library.repo_id)
            for library in runtime.orchestrator.discover_libraries(trigger="automatic")
        ]
        if not _automatic_cycle_continues_guarded(runtime, log):
            return
        _enqueue_specs(runtime.job_store, runtime.signal_queue, specs)
        log.info("reconciler.enqueued", count=len(specs))

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
            "connector_dashboard_control_enabled": (
                settings.connector_dashboard_control_enabled
            ),
            "connector_automation_initial_state": (
                settings.connector_automation_initial_state
            ),
            "connector_dashboard_host": settings.connector_dashboard_host,
            "connector_dashboard_port": settings.connector_dashboard_port,
            "authz_api_enabled": settings.authz_api_enabled,
            "authz_api_fail_closed": settings.authz_api_fail_closed,
            "authz_api_max_acl_age_seconds": settings.authz_api_max_acl_age_seconds,
            "search_acl_sync_enabled": settings.search_acl_sync_enabled,
            "search_acl_sync_interval_seconds": settings.search_acl_sync_interval_seconds,
            "openwebui_integration_enabled": settings.openwebui_integration_enabled,
            "openwebui_sync_mode": settings.openwebui_effective_sync_mode,
            "openwebui_base_url": settings.openwebui_base_url,
            "openwebui_create_tools": settings.openwebui_create_tools,
            "openwebui_create_pipes": settings.openwebui_create_pipes,
            "openwebui_authz_enabled": settings.openwebui_authz_enabled,
        },
        json_output=json_output,
    )


@app.command(help=t("cli.doctor.help"))
def doctor(
    effective: Annotated[
        bool,
        typer.Option("--effective", help=t("cli.doctor.effective")),
    ] = False,
    live: Annotated[
        bool,
        typer.Option("--live", help=t("cli.doctor.live")),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lokale Konfigurationswahrheit und optionale State-Dienste diagnostizieren."""
    settings = _bootstrap()
    inventory = settings_inventory(settings)
    checks: dict[str, dict[str, Any]] = {
        "configuration": {"status": "ok"},
        "database": {"status": "not_checked"},
        "redis": {"status": "not_checked"},
    }
    if live:
        try:
            check_database(settings.database_url)
            current, expected = database_revisions(settings.database_url)
            checks["database"] = {
                "status": "ok" if current == expected else "migration_required",
                "revision_current": current,
                "revision_expected": expected,
            }
        except Exception as exc:
            checks["database"] = {
                "status": "failed",
                "error_class": type(exc).__name__,
            }
        try:
            check_redis(settings.redis_url)
            checks["redis"] = {"status": "ok"}
        except Exception as exc:
            checks["redis"] = {
                "status": "failed",
                "error_class": type(exc).__name__,
            }
    payload: dict[str, Any] = {
        "ready": all(
            check["status"] in {"ok", "not_checked"} for check in checks.values()
        ),
        "checks": checks,
        "runtime": {
            "app_env": settings.app_env,
            "language": localizer_for(settings).language,
            "dashboard_enabled": settings.connector_dashboard_enabled,
            "dashboard_control_enabled": settings.connector_dashboard_control_enabled,
            "authz_enabled": settings.authz_api_enabled,
            "openwebui_mode": settings.openwebui_effective_sync_mode,
        },
        "configuration_statuses": settings_inventory_summary(inventory),
        "configured_limited_settings": configured_limited_settings(settings),
    }
    if effective:
        payload["effective_configuration"] = inventory
    _emit_payload(payload, json_output=json_output)
    if live and not payload["ready"]:
        raise typer.Exit(1)


@library_app.command("status", help=t("cli.library.status_help"))
def library_status(
    repo_id: Annotated[str | None, typer.Option("--repo-id")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Lokal bekannten Bibliotheks- und Cursorstatus anzeigen."""
    settings = _bootstrap()
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as session:
        stmt = select(Library).order_by(Library.name, Library.repo_id)
        if repo_id:
            stmt = stmt.where(Library.repo_id == repo_id)
        rows = list(session.scalars(stmt).all())
    _emit_payload(
        {
            "count": len(rows),
            "libraries": [_library_status_payload(row) for row in rows],
        },
        json_output=json_output,
    )


@library_app.command("plan", help=t("cli.library.plan_help"))
def library_plan(
    repo_id: Annotated[str, typer.Option("--repo-id")],
    scope: Annotated[str, typer.Option("--scope")] = "/",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reconcile-Plan ohne Remote-Mutationen erstellen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        plan = runtime.orchestrator.plan_library_reconcile(repo_id, scope=scope)
        _emit_payload(_reconcile_plan_payload(plan), json_output=json_output)
    finally:
        runtime.close()


@library_app.command("sync", help=t("cli.library.sync_help"))
def library_sync(
    repo_id: Annotated[str, typer.Option("--repo-id")],
    mode: Annotated[Literal["auto", "delta", "full"], typer.Option("--mode")] = "auto",
    scope: Annotated[str, typer.Option("--scope")] = "/",
    wait: Annotated[bool, typer.Option("--wait")] = False,
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1)] = 1800,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Bibliothek als persistentes Delta- oder Vollsync-Job einplanen."""
    job_type = JobType.SYNC_LIBRARY_FULL if mode == "full" else JobType.SYNC_LIBRARY_DELTA
    payload = _enqueue_cli_job(
        JobSpec(
            job_type,
            repo_id=repo_id,
            payload={"scope": scope, "trigger": "manual"},
        ),
        wait=wait,
        timeout_seconds=timeout_seconds,
    )
    _emit_job_result(payload, json_output=json_output)


@library_app.command("reconcile", help=t("cli.library.reconcile_help"))
def library_reconcile(
    repo_id: Annotated[str, typer.Option("--repo-id")],
    scope: Annotated[str, typer.Option("--scope")] = "/",
    execute: Annotated[bool, typer.Option("--execute")] = False,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1)] = 1800,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reconcile planen oder als gefencten Reparaturjob ausführen."""
    if not execute:
        library_plan(repo_id=repo_id, scope=scope, json_output=json_output)
        return
    payload = _enqueue_cli_job(
        JobSpec(
            JobType.RECONCILE_LIBRARY,
            repo_id=repo_id,
            payload={"scope": scope, "trigger": "manual"},
        ),
        wait=wait,
        timeout_seconds=timeout_seconds,
    )
    _emit_job_result(payload, json_output=json_output)


@jobs_app.command("list", help=t("cli.jobs.list_help"))
def jobs_list(
    status: Annotated[str | None, typer.Option("--status")] = None,
    repo_id: Annotated[str | None, typer.Option("--repo-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Jobs nach Status und Bibliothek filtern."""
    settings = _bootstrap()
    store = JobStore(get_session_factory(settings.database_url))
    statuses = _job_status_filter(status)
    rows = store.list_jobs(statuses=statuses, repo_id=repo_id, limit=limit)
    _emit_payload(
        {"count": len(rows), "jobs": [_job_payload(row) for row in rows]},
        json_output=json_output,
    )


@jobs_app.command("show", help=t("cli.jobs.show_help"))
def jobs_show(
    job_id: Annotated[int, typer.Argument(min=1)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Einen Job einschließlich Retry- und Fehlerzustand anzeigen."""
    settings = _bootstrap()
    row = JobStore(get_session_factory(settings.database_url)).get(job_id)
    if row is None:
        raise typer.BadParameter(t("cli.jobs.not_found", job_id=job_id))
    _emit_payload(_job_payload(row), json_output=json_output)


@jobs_app.command("cancel", help=t("cli.jobs.cancel_help"))
def jobs_cancel(
    job_id: Annotated[int, typer.Argument(min=1)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Queued Job abbrechen oder kooperativen Abbruch anfordern."""
    settings = _bootstrap()
    changed = JobStore(get_session_factory(settings.database_url)).request_cancel(job_id)
    _emit_payload(
        {"job_id": job_id, "cancel_requested": changed},
        json_output=json_output,
    )


@jobs_app.command("retry", help=t("cli.jobs.retry_help"))
def jobs_retry(
    job_id: Annotated[int, typer.Argument(min=1)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Dead- oder abgebrochenen Job erneut einplanen."""
    settings = _bootstrap()
    store = JobStore(get_session_factory(settings.database_url))
    changed = store.retry(job_id)
    signal_error: str | None = None
    if changed:
        signal_queue = JobSignalQueue(settings.redis_url)
        try:
            signal_queue.signal(job_id)
        except Exception as exc:
            # Der Worker pollt zusätzlich die Datenbank. Der persistierte Retry
            # bleibt deshalb gültig, auch wenn der Redis-Wake-up ausfällt.
            signal_error = type(exc).__name__
        finally:
            signal_queue.close()
    payload: dict[str, Any] = {"job_id": job_id, "retried": changed}
    if signal_error is not None:
        payload["signal_warning"] = signal_error
    _emit_payload(payload, json_output=json_output)


@cleanup_app.command("list", help=t("cli.cleanup.list_help"))
def cleanup_list(
    status: Annotated[str | None, typer.Option("--status")] = "dead",
    repo_id: Annotated[str | None, typer.Option("--repo-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Cleanup-Outbox nach Zustand und Bibliothek anzeigen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        statuses = _cleanup_status_filter(status)
        rows = runtime.orchestrator.list_cleanup_outbox(
            repo_id=repo_id,
            statuses=statuses,
            limit=limit,
        )
        _emit_payload(
            {
                "count": len(rows),
                "items": [_cleanup_outbox_payload(row) for row in rows],
            },
            json_output=json_output,
        )
    finally:
        runtime.close()


@cleanup_app.command("retry", help=t("cli.cleanup.retry_help"))
def cleanup_retry(
    outbox_id: Annotated[int, typer.Argument(min=1)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fehlgeschlagene Zielbereinigung als persistenten Job erneut einplanen."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        repo_id = runtime.orchestrator.requeue_cleanup_outbox(outbox_id)
        changed = repo_id is not None
        result = None
        signal_error: str | None = None
        if repo_id is not None:
            result = runtime.job_store.enqueue_with_result(
                JobSpec(
                    JobType.PROCESS_CLEANUP_OUTBOX,
                    repo_id=repo_id,
                    payload={"outbox_id": outbox_id, "trigger": "manual"},
                )
            )
            if not result.deduplicated:
                try:
                    runtime.signal_queue.signal(result.job_id)
                except Exception as exc:
                    signal_error = type(exc).__name__
    finally:
        runtime.close()
    payload: dict[str, Any] = {"outbox_id": outbox_id, "retried": changed}
    if result is not None:
        payload.update(
            {
                "job_id": result.job_id,
                "deduplicated": result.deduplicated,
            }
        )
    if signal_error is not None:
        payload["signal_warning"] = signal_error
    _emit_payload(payload, json_output=json_output)
    if not changed:
        raise typer.Exit(1)


def _standalone_dashboard_context(store: Any, settings: Settings) -> DashboardContext:
    control_store = AdminControlStore(store.session_factory)
    control_store.initialize_workflow(settings.connector_automation_initial_state)
    return DashboardContext(
        store,
        settings,
        PROCESS_STARTED_AT,
        control_store=control_store,
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
    context = _standalone_dashboard_context(store, settings)
    try:
        serve_dashboard_forever(context)
    except DashboardBindError as exc:
        log.error("dashboard.bind_failed", error=str(exc))
        raise typer.Exit(1) from exc


@app.command("authz-sync-once")
def authz_sync_once(
    json_output: Annotated[
        bool,
        typer.Option("--json", help=t("cli.output_json")),
    ] = False,
) -> None:
    """Seafile-Bibliotheksrechte einmal in den ACL-Snapshot spiegeln."""
    settings = _bootstrap()
    runtime = build_runtime(settings)
    try:
        _emit_payload(_sync_acl_snapshot(runtime), json_output=json_output)
    finally:
        runtime.close()


@app.command("search-server")
def search_server() -> None:
    """Nutzernahe Such-Webseite als separaten HTTP-Service starten."""
    settings = _bootstrap_search()
    log = structlog.get_logger(__name__)
    if not settings.search_service_enabled:
        log.info("search_service.disabled")
        typer.echo("Search-Service ist deaktiviert.")
        return
    serve_search_forever(SearchServiceContext(settings=settings, started_at=PROCESS_STARTED_AT))


def _enqueue_specs(
    job_store: JobStore,
    signal_queue: JobSignalQueue,
    specs: list[JobSpec],
) -> None:
    log = structlog.get_logger(__name__)
    for spec in specs:
        result = job_store.enqueue_with_result(spec)
        if result.deduplicated:
            log.info("job.enqueue_deduplicated", job_id=result.job_id, job_type=spec.job_type)
            continue
        try:
            signal_queue.signal(result.job_id)
        except Exception as exc:
            log.warning(
                "job.signal_failed",
                job_id=result.job_id,
                job_type=spec.job_type,
                error=str(exc),
            )


def _maintain_job_queue(runtime: Runtime, settings: Settings, log: Any) -> None:
    stale = runtime.job_store.requeue_stale_running_jobs(
        older_than_seconds=settings.job_lease_seconds
    )
    log.info(
        "controller.stale_jobs.requeued",
        count=stale.retrying,
        dead=stale.dead,
    )
    purged = runtime.job_store.purge_completed_jobs(
        older_than_days=settings.job_history_retention_days
    )
    log.info("controller.completed_jobs.purged", count=purged)


def _library_status_payload(library: Library) -> dict[str, Any]:
    return {
        "repo_id": library.repo_id,
        "name": library.name,
        "status": library.status,
        "deletion_state": library.deletion_state,
        "ragflow_dataset_id": library.ragflow_dataset_id,
        "head_commit_id": library.head_commit_id,
        "last_synced_commit_id": library.last_synced_commit_id,
        "last_seen_at": _iso_timestamp(library.last_seen_at),
        "missing_since": _iso_timestamp(library.missing_since),
        "missing_observations": library.missing_observations,
        "last_error": library.last_error,
        "updated_at": _iso_timestamp(library.updated_at),
    }


def _reconcile_plan_payload(plan: Any) -> dict[str, Any]:
    return {
        "repo_id": plan.repo_id,
        "dataset_id": plan.dataset_id,
        "scope": plan.scope,
        "commit_id": plan.commit_id,
        "snapshot_id": plan.snapshot_id,
        "has_drift": bool(plan.has_drift),
        "warnings": list(plan.warnings),
        "categories": dict(plan.categories),
        "jobs": [
            {
                "job_type": spec.job_type.value,
                "repo_id": spec.repo_id,
                "file_path": spec.file_path,
                "priority": spec.resolved_priority(),
                "payload": dict(redact_mapping(spec.payload)),
            }
            for spec in plan.jobs
        ],
    }


def _job_status_filter(raw: str | None) -> tuple[JobStatus, ...] | None:
    if raw is None or not raw.strip():
        return None
    values: list[JobStatus] = []
    invalid: list[str] = []
    for value in raw.split(","):
        normalized = value.strip().lower()
        if not normalized:
            continue
        try:
            status = JobStatus(normalized)
        except ValueError:
            invalid.append(value.strip())
            continue
        if status not in values:
            values.append(status)
    if invalid:
        allowed = ", ".join(status.value for status in JobStatus)
        raise typer.BadParameter(
            t(
                "cli.jobs.unknown_status",
                values=", ".join(invalid),
                allowed=allowed,
            )
        )
    return tuple(values) or None


def _cleanup_status_filter(raw: str | None) -> tuple[str, ...] | None:
    if raw is None or not raw.strip():
        return None
    allowed = {"pending", "retrying", "dead", "completed", "superseded"}
    values = list(
        dict.fromkeys(
            value.strip().lower() for value in raw.split(",") if value.strip()
        )
    )
    invalid = [value for value in values if value not in allowed]
    if invalid:
        raise typer.BadParameter(
            t(
                "cli.cleanup.unknown_status",
                values=", ".join(invalid),
                allowed=", ".join(sorted(allowed)),
            )
        )
    return tuple(values) or None


def _cleanup_outbox_payload(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "repo_id": row.repo_id,
        "run_id": row.run_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "dataset_id": row.dataset_id,
        "action": row.action,
        "status": row.status,
        "attempts": int(row.attempts),
        "run_after": _iso_timestamp(row.run_after),
        "error_message": row.error_message,
        "created_at": _iso_timestamp(row.created_at),
        "updated_at": _iso_timestamp(row.updated_at),
        "completed_at": _iso_timestamp(row.completed_at),
    }


def _job_payload(job: Any) -> dict[str, Any]:
    return {
        "id": int(job.id),
        "job_type": str(job.job_type),
        "repo_id": job.repo_id,
        "file_path": job.file_path,
        "status": str(job.status),
        "priority": int(job.priority),
        "attempts": int(job.attempts),
        "max_attempts": int(job.max_attempts),
        "run_id": job.run_id,
        "fence_token": job.fence_token,
        "cancel_requested_at": _iso_timestamp(job.cancel_requested_at),
        "run_after": _iso_timestamp(job.run_after),
        "locked_by": job.locked_by,
        "locked_at": _iso_timestamp(job.locked_at),
        "error_message": job.error_message,
        "payload": dict(redact_mapping(job.payload or {})),
        "created_at": _iso_timestamp(job.created_at),
        "updated_at": _iso_timestamp(job.updated_at),
    }


def _enqueue_cli_job(
    spec: JobSpec,
    *,
    wait: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    spec = _job_spec_with_trigger(spec, "manual")
    settings = _bootstrap()
    init_database(settings.database_url)
    session_factory = get_session_factory(settings.database_url)
    if spec.repo_id is not None:
        with session_factory() as session:
            if session.get(Library, spec.repo_id) is None:
                raise typer.BadParameter(t("cli.library.missing", repo_id=spec.repo_id))
        control = AdminControlStore(session_factory).library(spec.repo_id)
        if not control.runnable:
            raise typer.BadParameter(
                t(
                    "cli.library.controlled",
                    repo_id=spec.repo_id,
                    state=control.state,
                )
            )
    store = JobStore(
        session_factory,
        default_max_attempts=settings.job_max_attempts,
        retry_base_seconds=settings.job_retry_base_seconds,
        retry_max_seconds=settings.job_retry_max_seconds,
    )
    result = store.enqueue_with_result(spec)
    signal_error: str | None = None
    if not result.deduplicated:
        signal_queue = JobSignalQueue(settings.redis_url)
        try:
            signal_queue.signal(result.job_id)
        except Exception as exc:
            # Der Worker pollt zusätzlich die Datenbank; ein verlorenes Wake-up
            # darf den persistent angelegten Job daher nicht verwerfen.
            signal_error = type(exc).__name__
        finally:
            signal_queue.close()
    payload: dict[str, Any] = {
        "job_id": result.job_id,
        "deduplicated": result.deduplicated,
        "waited": wait,
    }
    if signal_error is not None:
        payload["signal_warning"] = signal_error
    if not wait:
        job = store.get(result.job_id)
        if job is not None:
            payload["job"] = _job_payload(job)
        return payload

    terminal = {
        JobStatus.SUCCEEDED.value,
        JobStatus.DEAD.value,
        JobStatus.CANCELLED.value,
    }
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = store.get(result.job_id)
        if job is None:
            raise RuntimeError(t("cli.jobs.disappeared", job_id=result.job_id))
        if job.status in terminal:
            payload["job"] = _job_payload(job)
            return payload
        time.sleep(1)
    job = store.get(result.job_id)
    payload["timed_out"] = True
    if job is not None:
        payload["job"] = _job_payload(job)
    return payload


def _iso_timestamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _emit_payload(payload: dict[str, Any], *, json_output: bool = False) -> None:
    typer.echo(_format_payload(payload, json_output=json_output))


def _emit_job_result(payload: dict[str, Any], *, json_output: bool = False) -> None:
    _emit_payload(payload, json_output=json_output)
    job = payload.get("job")
    status = job.get("status") if isinstance(job, dict) else None
    if payload.get("timed_out") or status in {
        JobStatus.DEAD.value,
        JobStatus.CANCELLED.value,
    }:
        raise typer.Exit(1)


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
    def maybe_sync_openwebui(spec: JobSpec) -> None:
        if not bool(spec.payload.get("sync_openwebui")):
            return
        if runtime.openwebui_sync_service is None or spec.repo_id is None:
            return
        if job_cancellation_requested():
            raise SyncCancelledError("OpenWebUI scheduling interrupted")
        trigger = str(spec.payload.get("trigger") or "automatic")
        payload: dict[str, Any] = {
            "repo_ids": [spec.repo_id],
            "trigger": trigger,
        }
        workflow_run_id = str(spec.payload.get("workflow_run_id") or "").strip()
        if workflow_run_id:
            payload["workflow_run_id"] = workflow_run_id
        child = runtime.job_store.enqueue_with_result(
            JobSpec(
                JobType.SYNC_OPENWEBUI,
                repo_id=spec.repo_id,
                payload=payload,
            )
        )
        parent_job_id = current_job_id()
        if parent_job_id is not None:
            runtime.job_store.inherit_workflow_subscriptions(
                parent_job_id,
                child.job_id,
                child_created=not child.deduplicated,
            )
        if child.deduplicated:
            return
        try:
            runtime.signal_queue.signal(child.job_id)
        except Exception as exc:
            structlog.get_logger(__name__).warning(
                "job.signal_failed",
                job_id=child.job_id,
                job_type=JobType.SYNC_OPENWEBUI,
                error=str(exc),
            )

    def ensure_dataset(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        runtime.orchestrator.ensure_dataset_for_repo(repo_id)

    def sync_full(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        scope = str(spec.payload.get("scope") or spec.file_path or "/")
        runtime.orchestrator.sync_library_full(repo_id, scope=scope)
        maybe_sync_openwebui(spec)

    def sync_delta(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        scope = str(spec.payload.get("scope") or spec.file_path or "/")
        runtime.orchestrator.sync_library_delta(repo_id, scope=scope)
        maybe_sync_openwebui(spec)

    def reconcile_library(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        scope = str(spec.payload.get("scope") or spec.file_path or "/")
        runtime.orchestrator.reconcile_library(repo_id, scope=scope, execute=True)
        maybe_sync_openwebui(spec)

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
        runtime.orchestrator.check_parse_status(repo_id, dataset_id, raise_if_pending=True)

    def process_cleanup_outbox(spec: JobSpec) -> None:
        repo_id = _require_repo_id(spec)
        runtime.orchestrator.process_cleanup_outbox(repo_id=repo_id)

    def sync_openwebui(spec: JobSpec) -> None:
        if runtime.openwebui_sync_service is None:
            return
        if job_cancellation_requested():
            raise SyncCancelledError("OpenWebUI sync interrupted")
        mode = spec.payload.get("mode")
        if mode is not None and str(mode) not in {"disabled", "dry-run", "sync", "repair"}:
            raise ValueError(t("cli.jobs.sync_mode_error"))
        mode_override = cast(OpenWebUIMode, str(mode)) if mode else None
        raw_repo_ids = spec.payload.get("repo_ids")
        repo_ids = (
            {str(value) for value in raw_repo_ids if str(value).strip()}
            if isinstance(raw_repo_ids, list)
            else ({spec.repo_id} if spec.repo_id else None)
        )
        runtime.openwebui_sync_service.sync_once(
            mode_override=mode_override,
            repo_ids=repo_ids,
        )

    handlers = {
        JobType.DISCOVER_LIBRARIES: lambda spec: _enqueue_specs(
            runtime.job_store,
            runtime.signal_queue,
            _discover_job_specs(runtime),
        ),
        JobType.ENSURE_RAGFLOW_DATASET: ensure_dataset,
        JobType.REFRESH_DATASET_SETTINGS: ensure_dataset,
        JobType.SYNC_LIBRARY_FULL: sync_full,
        JobType.SYNC_LIBRARY_DELTA: sync_delta,
        JobType.UPLOAD_FILE: upload_file,
        JobType.DELETE_FILE: delete_file,
        JobType.PARSE_DOCUMENTS: parse_documents,
        JobType.REPARSE_DOCUMENTS: parse_documents,
        JobType.CHECK_PARSE_STATUS: check_parse,
        JobType.PROCESS_CLEANUP_OUTBOX: process_cleanup_outbox,
        JobType.RECONCILE_LIBRARY: reconcile_library,
        JobType.RECONCILE_RAGFLOW_DATASET: check_parse,
        JobType.SYNC_OPENWEBUI: sync_openwebui,
    }
    return {
        job_type: _guard_job_handler(runtime, handler)
        for job_type, handler in handlers.items()
    }


def _ensure_search_answer_chat(
    runtime: Runtime,
    log: Any,
    *,
    checkpoint: Callable[[], bool] | None = None,
) -> None:
    settings = runtime.settings
    if settings.search_answer_generation_mode != "ragflow_chat":
        return
    if not settings.ragflow_search_answer_chat_auto_create:
        log.info(
            "ragflow.search_answer_chat.skipped",
            reason="auto_create_disabled",
            chat_name=settings.ragflow_search_answer_chat_name,
        )
        return
    payload = build_search_answer_chat_payload(settings.ragflow_search_answer_chat_name)
    if checkpoint is not None and not checkpoint():
        return
    try:
        existing = runtime.ragflow_client.list_chats(name=settings.ragflow_search_answer_chat_name)
    except Exception as exc:  # pragma: no cover - deployment-specific startup guard
        log.warning(
            "ragflow.search_answer_chat.lookup_failed",
            chat_name=settings.ragflow_search_answer_chat_name,
            error=str(exc),
            error_class=type(exc).__name__,
        )
        return
    matching = [
        item
        for item in existing
        if str(item.get("name") or "").strip() == settings.ragflow_search_answer_chat_name
    ]
    if len(matching) > 1:
        log.warning(
            "ragflow.search_answer_chat.ambiguous",
            chat_name=settings.ragflow_search_answer_chat_name,
            count=len(matching),
        )
        return
    if matching:
        log.info(
            "ragflow.search_answer_chat.ready",
            chat_name=settings.ragflow_search_answer_chat_name,
            chat_id=_mapping_id(matching[0]),
            created=False,
        )
        return
    if checkpoint is not None and not checkpoint():
        return
    try:
        created = runtime.ragflow_client.create_chat(payload)
    except Exception as exc:  # pragma: no cover - deployment-specific startup guard
        log.warning(
            "ragflow.search_answer_chat.create_failed",
            chat_name=settings.ragflow_search_answer_chat_name,
            error=str(exc),
            error_class=type(exc).__name__,
        )
        return
    log.info(
        "ragflow.search_answer_chat.ready",
        chat_name=settings.ragflow_search_answer_chat_name,
        chat_id=_mapping_id(created),
        created=True,
    )


def _mapping_id(value: dict[str, Any]) -> str | None:
    raw = value.get("id") or value.get("chat_id")
    if raw in (None, ""):
        return None
    return str(raw)


def _discover_job_specs(runtime: Runtime) -> list[JobSpec]:
    if not _automatic_cycles_enabled_guarded(runtime, structlog.get_logger(__name__)):
        return []
    specs = runtime.orchestrator.discover_job_specs()
    if _openwebui_sync_enabled(runtime):
        specs.append(JobSpec(JobType.SYNC_OPENWEBUI))
    return specs


def _sync_openwebui_if_enabled(runtime: Runtime) -> dict[str, Any] | None:
    if not _openwebui_sync_enabled(runtime) or runtime.openwebui_sync_service is None:
        return None
    summary = runtime.openwebui_sync_service.sync_once()
    return dict(summary.__dict__)


def _sync_openwebui_controller_guarded(runtime: Runtime, log: Any) -> None:
    if (
        not _automatic_cycles_enabled_guarded(runtime, log)
        or not _openwebui_sync_enabled(runtime)
        or runtime.openwebui_sync_service is None
    ):
        return
    try:
        runtime.openwebui_sync_service.sync_once()
    except Exception as exc:
        log.warning(
            "controller.openwebui_sync.failed",
            error=str(exc),
            error_class=type(exc).__name__,
        )


def _sync_acl_snapshot_if_enabled(runtime: Runtime) -> dict[str, Any] | None:
    if not runtime.settings.search_acl_sync_enabled:
        return None
    return _sync_acl_snapshot(runtime)


class _CheckpointingAdminClient:
    def __init__(self, client: Any, checkpoint: Callable[[], bool]) -> None:
        self._client = client
        self._checkpoint = checkpoint

    def iter_libraries(self) -> Iterator[dict[str, Any]]:
        libraries = iter(self._client.iter_libraries())
        while True:
            if not self._checkpoint():
                raise SyncCancelledError("automatic ACL snapshot interrupted")
            try:
                yield next(libraries)
            except StopIteration:
                return

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _sync_acl_snapshot(
    runtime: Runtime,
    *,
    checkpoint: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    admin_client = runtime.admin_client
    if checkpoint is not None:
        admin_client = cast(Any, _CheckpointingAdminClient(admin_client, checkpoint))
    summary = ACLSnapshotService(
        settings=runtime.settings,
        session_factory=runtime.orchestrator.session_factory,
        admin_client=admin_client,
    ).refresh_once()
    return dict(summary.__dict__)


def _openwebui_sync_enabled(runtime: Runtime) -> bool:
    return runtime.settings.openwebui_effective_sync_mode != "disabled"


def _automatic_cycles_enabled(runtime: Runtime) -> bool:
    workflow = runtime.orchestrator.admin_control_store.workflow()
    return workflow.automation_enabled and not workflow.queue_paused


def _automatic_cycles_enabled_guarded(runtime: Runtime, log: Any) -> bool:
    try:
        return _automatic_cycles_enabled(runtime)
    except Exception as exc:
        log.warning(
            "controller.automation_check_failed",
            error_class=type(exc).__name__,
        )
        return False


def _automatic_cycle_continues_guarded(runtime: Runtime, log: Any) -> bool:
    try:
        return not runtime.orchestrator.admin_control_store.workflow().queue_paused
    except Exception as exc:
        log.warning(
            "controller.automation_check_failed",
            error_class=type(exc).__name__,
        )
        return False


def _job_spec_with_trigger(spec: JobSpec, trigger: str) -> JobSpec:
    return JobSpec(
        spec.job_type,
        repo_id=spec.repo_id,
        file_path=spec.file_path,
        payload={**spec.payload, "trigger": trigger},
        priority=spec.priority,
        max_attempts=spec.max_attempts,
    )


def _guard_job_handler(
    runtime: Runtime,
    handler: Callable[[JobSpec], None],
) -> Callable[[JobSpec], None]:
    def guarded(spec: JobSpec) -> None:
        if spec.repo_id is not None:
            control = runtime.orchestrator.admin_control_store.library(spec.repo_id)
            if not control.runnable:
                raise JobDeferredError(
                    t(
                        "cli.library.controlled",
                        repo_id=spec.repo_id,
                        state=control.state,
                    )
                )
        handler(spec)

    return guarded


def _require_repo_id(spec: JobSpec) -> str:
    if not spec.repo_id:
        msg = t("cli.jobs.requires_repo_id", job_type=spec.job_type)
        raise ValueError(msg)
    return spec.repo_id


def _wait_for_parse(runtime: Runtime, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        active = False
        for repo_id, dataset_id in _active_dataset_bindings(runtime):
            runtime.orchestrator.check_parse_status(repo_id, dataset_id)
            pending, dead = _parse_work_state(runtime, repo_id, dataset_id)
            if dead:
                raise RuntimeError(
                    f"RAGFlow parsing failed for {dead} document(s) in {repo_id}"
                )
            active = active or pending > 0
        if not active:
            return
        time.sleep(5)
    raise TimeoutError(
        f"RAGFlow parsing did not finish within {timeout_seconds} seconds"
    )


def _parse_work_state(runtime: Runtime, repo_id: str, dataset_id: str) -> tuple[int, int]:
    with runtime.orchestrator.session_factory() as session:
        rows = session.execute(
            select(
                FileDocumentVersion.file_id,
                FileDocumentVersion.id,
                FileDocumentVersion.state,
            )
            .where(FileDocumentVersion.repo_id == repo_id)
            .where(FileDocumentVersion.dataset_id == dataset_id)
            .order_by(FileDocumentVersion.file_id, FileDocumentVersion.id.desc())
        ).all()
    latest_by_file: dict[int, str] = {}
    for file_id, _version_id, state in rows:
        latest_by_file.setdefault(int(file_id), str(state))
    pending = sum(
        state in {"uploaded", "parsing", "retryable_failed"}
        for state in latest_by_file.values()
    )
    dead = sum(state == "dead" for state in latest_by_file.values())
    return pending, dead


def _active_dataset_bindings(runtime: Runtime) -> list[tuple[str, str]]:
    with runtime.orchestrator.session_factory() as session:
        rows = session.execute(
            select(Library.repo_id, Library.ragflow_dataset_id)
            .where(Library.status == "active")
            .where(Library.ragflow_dataset_id.is_not(None))
        ).all()
    return [(str(repo_id), str(dataset_id)) for repo_id, dataset_id in rows if dataset_id]


if __name__ == "__main__":
    app()
