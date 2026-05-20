from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any

import structlog
import typer

from seafile_ragflow_connector.app.logging import configure_logging
from seafile_ragflow_connector.app.runtime import build_runtime, check_database, check_redis
from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.scheduler import PeriodicTask, SimpleScheduler
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner
from seafile_ragflow_connector.persistence.db import init_database

app = typer.Typer(help="Offline-first Seafile to RAGFlow connector")


def _bootstrap() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


@app.command()
def init_db() -> None:
    """Create or update connector state tables."""
    _bootstrap()
    settings = get_settings()
    init_database(settings.database_url)
    typer.echo("database initialized")


@app.command("check-live")
def check_live() -> None:
    """Check live dependencies without mutating Seafile or RAGFlow."""
    _bootstrap()
    settings = get_settings()
    check_database(settings.database_url)
    check_redis(settings.redis_url)
    runtime = build_runtime(settings)
    try:
        libraries = _retry_until(
            lambda: runtime.admin_client.list_libraries(per_page=1),
            "Seafile",
        )
        templates = _retry_until(
            lambda: runtime.ragflow_client.list_datasets(name=settings.ragflow_template_dataset_name),
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
    _bootstrap()
    settings = get_settings()
    runtime = build_runtime(settings)
    try:
        summary = runtime.orchestrator.sync_once()
        if wait_parse_seconds > 0:
            _wait_for_parse(runtime, wait_parse_seconds)
        typer.echo(summary.__dict__)
    finally:
        runtime.close()


@app.command()
def controller() -> None:
    """Run the discovery and delta scheduling loop."""
    _bootstrap()
    settings = get_settings()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)

    def discover() -> None:
        specs = runtime.orchestrator.discover_job_specs()
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

    scheduler = SimpleScheduler(
        [
            PeriodicTask("discovery", settings.discovery_interval_seconds, discover),
            PeriodicTask("delta", settings.delta_sync_interval_seconds, delta),
            PeriodicTask("template", settings.ragflow_template_refresh_seconds, template),
        ]
    )
    log.info("controller.started")
    scheduler.run_forever()


@app.command()
def worker() -> None:
    """Run a connector worker process."""
    _bootstrap()
    settings = get_settings()
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
    _bootstrap()
    settings = get_settings()
    runtime = build_runtime(settings)
    log = structlog.get_logger(__name__)

    def reconcile() -> None:
        summary = runtime.orchestrator.sync_once()
        log.info("reconciler.synced", **summary.__dict__)

    scheduler = SimpleScheduler([PeriodicTask("reconcile", settings.reconcile_interval_seconds, reconcile)])
    log.info("reconciler.started")
    scheduler.run_forever()


@app.command("check-config")
def check_config() -> None:
    """Load and validate configuration without contacting external services."""
    _bootstrap()
    settings = get_settings()
    typer.echo(
        {
            "app_env": settings.app_env,
            "seafile_base_url": settings.seafile_base_url,
            "ragflow_base_url": settings.ragflow_base_url,
            "allow_unknown_text_files": settings.allow_unknown_text_files,
            "dataset_settings_source": settings.dataset_settings_source,
        }
    )


def _enqueue_specs(job_store: JobStore, signal_queue, specs: list[JobSpec]) -> None:
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
        raise RuntimeError(f"{label} did not become ready within {timeout_seconds}s") from last_error
    raise RuntimeError(f"{label} did not become ready within {timeout_seconds}s")


def _build_job_handlers(runtime) -> dict[JobType, Callable[[JobSpec], None]]:
    def ensure_dataset(spec: JobSpec) -> None:
        _require_repo_id(spec)
        runtime.orchestrator.ensure_dataset_for_repo(spec.repo_id)

    def sync_full(spec: JobSpec) -> None:
        _require_repo_id(spec)
        scope = str(spec.payload.get("scope") or spec.file_path or "/")
        runtime.orchestrator.sync_library_full(spec.repo_id, scope=scope)

    def upload_file(spec: JobSpec) -> None:
        _require_repo_id(spec)
        if not spec.file_path:
            raise ValueError("UPLOAD_FILE requires file_path")
        dataset_id = runtime.orchestrator.ensure_dataset_for_repo(spec.repo_id)
        runtime.orchestrator.sync_file(spec.repo_id, dataset_id, spec.file_path, force=True)

    def delete_file(spec: JobSpec) -> None:
        _require_repo_id(spec)
        if not spec.file_path:
            raise ValueError("DELETE_FILE requires file_path")
        dataset_id = runtime.orchestrator.ensure_dataset_for_repo(spec.repo_id)
        runtime.orchestrator.delete_file(spec.repo_id, dataset_id, spec.file_path)

    def parse_documents(spec: JobSpec) -> None:
        dataset_id = str(spec.payload["dataset_id"])
        document_ids = [str(value) for value in spec.payload["document_ids"]]
        runtime.ragflow_client.parse_documents(dataset_id, document_ids)

    def check_parse(spec: JobSpec) -> None:
        _require_repo_id(spec)
        dataset_id = str(spec.payload.get("dataset_id") or runtime.orchestrator.ensure_dataset_for_repo(spec.repo_id))
        runtime.orchestrator.check_parse_status(spec.repo_id, dataset_id)

    return {
        JobType.DISCOVER_LIBRARIES: lambda spec: _enqueue_specs(
            runtime.job_store,
            runtime.signal_queue,
            runtime.orchestrator.discover_job_specs(),
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
    }


def _require_repo_id(spec: JobSpec) -> None:
    if not spec.repo_id:
        msg = f"{spec.job_type} requires repo_id"
        raise ValueError(msg)


def _wait_for_parse(runtime, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        active = False
        for library in runtime.orchestrator.discover_libraries():
            dataset_id = runtime.orchestrator.ensure_dataset_for_repo(library.repo_id)
            updated = runtime.orchestrator.check_parse_status(library.repo_id, dataset_id)
            if updated:
                documents = runtime.ragflow_client.list_documents(dataset_id)
                active = any(document.get("run") in {"RUNNING", "UNSTART"} for document in documents)
        if not active:
            return
        time.sleep(5)


if __name__ == "__main__":
    app()
