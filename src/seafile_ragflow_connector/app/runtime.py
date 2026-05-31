from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.app.transport import resolve_service_transports
from seafile_ragflow_connector.clients import (
    OpenWebUIClient,
    RAGFlowClient,
    SeafileAdminClient,
    SeafileSyncClient,
)
from seafile_ragflow_connector.clients.tls import safe_url_for_logs
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
from seafile_ragflow_connector.domain.file_classification import FilePolicy
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.openwebui.sync import OpenWebUISyncService
from seafile_ragflow_connector.persistence.db import get_engine, get_session_factory, init_database
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
    openwebui_client: OpenWebUIClient | None = None
    openwebui_sync_service: OpenWebUISyncService | None = None
    dashboard_store: DashboardEventStore | None = None

    def close(self) -> None:
        self.admin_client.close()
        self.sync_client.close()
        self.ragflow_client.close()
        if self.openwebui_client is not None:
            self.openwebui_client.close()
        self.signal_queue.close()


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
    resolve_service_transports(settings)
    _warn_insecure_tls(settings)
    if initialize_database:
        _retry(lambda: init_database(settings.database_url), "database")
    _retry(lambda: check_redis(settings.redis_url), "redis")
    session_factory = get_session_factory(settings.database_url)
    dashboard_store = build_dashboard_store(settings, session_factory)
    admin_client = SeafileAdminClient(
        settings.seafile_base_url,
        settings.seafile_admin_token,
        verify=settings.seafile_httpx_verify,
    )
    sync_client = SeafileSyncClient(
        settings.seafile_base_url,
        settings.seafile_sync_user_token,
        verify=settings.seafile_httpx_verify,
        rewrite_download_urls=settings.seafile_rewrite_download_urls,
        rewrite_from=settings.seafile_download_rewrite_from,
        rewrite_to=settings.seafile_download_rewrite_to,
    )
    ragflow_client = RAGFlowClient(
        settings.ragflow_base_url,
        settings.ragflow_api_key,
        verify=settings.ragflow_httpx_verify,
    )
    openwebui_client = _build_openwebui_client(settings)
    orchestrator = SyncOrchestrator(
        session_factory,
        admin_client=admin_client,
        sync_client=sync_client,
        ragflow_client=ragflow_client,
        file_policy=build_file_policy(settings),
        template_dataset_name=settings.ragflow_template_dataset_name,
        template_auto_create=settings.ragflow_template_auto_create,
        template_required=settings.ragflow_template_required,
        skip_encrypted_libraries=settings.seafile_skip_encrypted_libraries,
        skip_virtual_repos=settings.seafile_skip_virtual_repos,
        delete_ragflow_docs_on_seafile_delete=settings.delete_ragflow_docs_on_seafile_delete,
        delete_dataset_when_library_deleted=settings.delete_dataset_when_library_deleted,
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
        openwebui_client=openwebui_client,
        openwebui_sync_service=OpenWebUISyncService(
            settings=settings,
            session_factory=session_factory,
            ragflow_client=ragflow_client,
            openwebui_client=openwebui_client,
            dashboard_store=dashboard_store,
        ),
        dashboard_store=dashboard_store,
    )


def build_dashboard_store(
    settings: Settings,
    session_factory: sessionmaker[Session] | None = None,
) -> DashboardEventStore | None:
    dashboard_not_needed = (
        not settings.connector_dashboard_enabled
        and settings.openwebui_effective_sync_mode == "disabled"
    )
    if dashboard_not_needed:
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


def _build_openwebui_client(settings: Settings) -> OpenWebUIClient | None:
    if settings.openwebui_effective_sync_mode == "disabled":
        return None
    if not settings.openwebui_admin_api_key:
        return None
    return OpenWebUIClient(
        settings.openwebui_base_url,
        settings.openwebui_admin_api_key,
        timeout=settings.openwebui_request_timeout_seconds,
        verify=settings.openwebui_httpx_verify,
    )


def _warn_insecure_tls(settings: Settings) -> None:
    logger = structlog.get_logger(__name__)
    checks = (
        ("Connector -> Seafile", settings.seafile_base_url, settings.seafile_verify_ssl),
        ("Connector -> RAGFlow", settings.ragflow_base_url, settings.ragflow_verify_ssl),
        ("Connector -> OpenWebUI", settings.openwebui_base_url, settings.openwebui_verify_ssl),
        (
            "OpenWebUI Pipe -> Connector Proxy",
            settings.openwebui_proxy_base_url_for_functions or "",
            settings.openwebui_proxy_verify_ssl,
        ),
    )
    for route, target_url, verify_ssl in checks:
        if verify_ssl:
            continue
        logger.warning(
            "tls.verify_disabled",
            route=route,
            target=safe_url_for_logs(target_url),
            hint="VERIFY_SSL=false ist nur für Debug/Dev vorgesehen.",
        )


def check_database(database_url: str) -> None:
    engine = get_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    finally:
        engine.dispose()


def check_redis(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        client.ping()
    finally:
        client.close()


def _retry(
    operation: Callable[[], Any],
    name: str,
    *,
    timeout_seconds: int = 120,
    sleep_seconds: int = 2,
) -> None:
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
