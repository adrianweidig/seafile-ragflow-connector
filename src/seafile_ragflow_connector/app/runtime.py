from __future__ import annotations

import time
from dataclasses import dataclass

from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.clients import RAGFlowClient, SeafileAdminClient, SeafileSyncClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
from seafile_ragflow_connector.domain.file_classification import FilePolicy
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.persistence.db import get_session_factory, init_database
from seafile_ragflow_connector.sync.orchestrator import SyncOrchestrator


@dataclass
class Runtime:
    settings: Settings
    admin_client: SeafileAdminClient
    sync_client: SeafileSyncClient
    ragflow_client: RAGFlowClient
    orchestrator: SyncOrchestrator
    job_store: JobStore
    signal_queue: JobSignalQueue
    dashboard_store: DashboardEventStore | None = None

    def close(self) -> None:
        self.admin_client.close()
        self.sync_client.close()
        self.ragflow_client.close()


def build_file_policy(settings: Settings) -> FilePolicy:
    return FilePolicy(
        allow_unknown_text_files=settings.allow_unknown_text_files,
        allow_extensions=frozenset(settings.allow_extensions),
        deny_extensions=frozenset(settings.deny_extensions),
        text_extensions=frozenset(settings.text_extensions),
        binary_direct_extensions=frozenset(settings.binary_direct_extensions),
        default_text_ingestion_strategy=settings.default_text_ingestion_strategy,
        max_file_size_bytes=settings.max_file_size_mb * 1024 * 1024,
        exclude_regex=settings.exclude_regex,
    )


def build_runtime(settings: Settings, *, initialize_database: bool = True) -> Runtime:
    if initialize_database:
        _retry(lambda: init_database(settings.database_url), "database")
    _retry(lambda: check_redis(settings.redis_url), "redis")
    session_factory = get_session_factory(settings.database_url)
    dashboard_store = build_dashboard_store(settings, session_factory)
    admin_client = SeafileAdminClient(settings.seafile_base_url, settings.seafile_admin_token)
    sync_client = SeafileSyncClient(
        settings.seafile_base_url,
        settings.seafile_sync_user_token,
        rewrite_download_urls=settings.seafile_rewrite_download_urls,
        rewrite_from=settings.seafile_download_rewrite_from,
        rewrite_to=settings.seafile_download_rewrite_to,
    )
    ragflow_client = RAGFlowClient(settings.ragflow_base_url, settings.ragflow_api_key)
    orchestrator = SyncOrchestrator(
        session_factory,
        admin_client=admin_client,
        sync_client=sync_client,
        ragflow_client=ragflow_client,
        file_policy=build_file_policy(settings),
        template_dataset_name=settings.ragflow_template_dataset_name,
        skip_encrypted_libraries=settings.seafile_skip_encrypted_libraries,
        skip_virtual_repos=settings.seafile_skip_virtual_repos,
        delete_ragflow_docs_on_seafile_delete=settings.delete_ragflow_docs_on_seafile_delete,
        refresh_dataset_settings=settings.ragflow_refresh_dataset_settings,
        dashboard_store=dashboard_store,
    )
    return Runtime(
        settings=settings,
        admin_client=admin_client,
        sync_client=sync_client,
        ragflow_client=ragflow_client,
        orchestrator=orchestrator,
        job_store=JobStore(
            session_factory,
            retry_base_seconds=settings.job_retry_base_seconds,
            retry_max_seconds=settings.job_retry_max_seconds,
        ),
        signal_queue=JobSignalQueue(settings.redis_url),
        dashboard_store=dashboard_store,
    )


def build_dashboard_store(
    settings: Settings,
    session_factory: sessionmaker[Session] | None = None,
) -> DashboardEventStore | None:
    if not settings.connector_dashboard_enabled:
        return None
    if session_factory is None:
        session_factory = get_session_factory(settings.database_url)
    return DashboardEventStore(
        session_factory,
        DashboardLimits(
            max_sync_runs=settings.connector_dashboard_max_sync_runs,
            max_event_entries=settings.connector_dashboard_max_event_entries,
            max_log_entries=settings.connector_dashboard_max_log_entries,
            page_size=settings.connector_dashboard_log_page_size,
            max_field_length=settings.connector_dashboard_max_field_length,
        ),
    )


def check_database(database_url: str) -> None:
    session_factory = get_session_factory(database_url)
    with session_factory() as session:
        session.execute(text("select 1"))


def check_redis(redis_url: str) -> None:
    Redis.from_url(redis_url).ping()


def _retry(operation, name: str, *, timeout_seconds: int = 120, sleep_seconds: int = 2) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            operation()
            return
        except Exception as exc:  # pragma: no cover - exercised by container startup timing
            last_error = exc
            time.sleep(sleep_seconds)
    if last_error:
        raise RuntimeError(f"{name} did not become ready within {timeout_seconds}s") from last_error
