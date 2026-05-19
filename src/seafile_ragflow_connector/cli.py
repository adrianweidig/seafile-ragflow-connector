from __future__ import annotations

import time

import structlog
import typer

from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.logging import configure_logging
from seafile_ragflow_connector.queue.scheduler import PeriodicTask, SimpleScheduler

app = typer.Typer(help="Offline-first Seafile to RAGFlow connector")


def _bootstrap() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


@app.command()
def controller() -> None:
    """Run the discovery and delta scheduling loop."""
    _bootstrap()
    settings = get_settings()
    log = structlog.get_logger(__name__)

    def discover() -> None:
        log.info("controller.discovery.tick")

    def delta() -> None:
        log.info("controller.delta.tick")

    def template() -> None:
        log.info("controller.template.tick")

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
    log = structlog.get_logger(__name__)
    log.info("worker.started")
    while True:
        time.sleep(30)
        log.info("worker.heartbeat")


@app.command()
def reconciler() -> None:
    """Run the low-priority reconciliation loop."""
    _bootstrap()
    settings = get_settings()
    log = structlog.get_logger(__name__)

    def reconcile() -> None:
        log.info("reconciler.tick")

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


if __name__ == "__main__":
    app()

