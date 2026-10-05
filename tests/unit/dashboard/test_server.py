from __future__ import annotations

import base64
import json
import unittest
from dataclasses import dataclass
from hashlib import sha256
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import seafile_ragflow_connector.dashboard.server as dashboard_server
    from seafile_ragflow_connector.clients.http import ApiError
    from seafile_ragflow_connector.config.settings import Settings
    from seafile_ragflow_connector.dashboard.server import (
        DashboardContext,
        _clean_source_snippet,
        _handle_openwebui_chat,
        _load_mapping,
        _preview_html,
        start_dashboard_server,
    )
    from seafile_ragflow_connector.dashboard.store import (
        DashboardEventStore,
        DashboardLimits,
        utcnow,
    )
    from seafile_ragflow_connector.jobs.job_store import EnqueueResult, JobStore
    from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
    from seafile_ragflow_connector.openwebui.sources import sign_preview_payload
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.file import File
    from seafile_ragflow_connector.persistence.models.job import SyncJob
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping
    from seafile_ragflow_connector.persistence.models.search import (
        LibraryACLEffectiveUser,
        SearchProfile,
    )
    from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "sqlalchemy"}:
        raise
    create_engine = None  # type: ignore[assignment]


def _settings(port: int) -> Settings:
    settings = Settings(
        seafile_base_url="http://127.0.0.1:1",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://127.0.0.1:1",
        ragflow_api_key="ragflow-token",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
        connector_dashboard_enabled=True,
        connector_dashboard_host="127.0.0.1",
        connector_dashboard_port=1,
        openwebui_proxy_shared_secret="proxy-secret",
        openwebui_authz_enabled=False,
    )
    settings.connector_dashboard_port = port
    return settings


def _admin_settings(port: int) -> Settings:
    settings = _settings(port)
    settings.connector_dashboard_auth_username = "admin"
    settings.connector_dashboard_auth_password = "secret"
    settings.connector_dashboard_control_enabled = True
    return settings


def _store(test_case: unittest.TestCase) -> DashboardEventStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return DashboardEventStore(session_factory, DashboardLimits(page_size=10))


def _add_search_profile_with_acl(store: DashboardEventStore, *, user_email: str) -> None:
    now = utcnow()
    with store.session_factory() as session:
        session.add(
            SearchProfile(
                repo_id="repo-1",
                ragflow_dataset_id="dataset-1",
                ragflow_dataset_name="Anleitungen",
                display_name="Anleitungen",
                kind="documents",
                enabled=True,
                status="ready",
                last_acl_sync_at=now,
            )
        )
        session.add(
            LibraryACLEffectiveUser(
                repo_id="repo-1",
                user_email=user_email,
                permission="r",
                sources=["user_share"],
                last_seen_at=now,
            )
        )
        session.commit()


@unittest.skipIf(
    create_engine is None,
    "pydantic or sqlalchemy is not installed in this Python environment",
)
class DashboardServerTests(unittest.TestCase):
    def test_interactive_ragflow_config_is_safe_and_client_selection_is_split(self) -> None:
        settings = _settings(0)
        settings.ragflow_generated_dataset_permission = "team"
        settings.ragflow_interactive_api_key = "interactive-token"
        settings.ragflow_interactive_owner_id = "owner-1"
        settings.ragflow_interactive_chat_model_id = "model@provider"

        safe = dashboard_server._safe_config(settings)  # type: ignore[attr-defined]

        self.assertEqual(safe["ragflow_generated_dataset_permission"], "team")
        self.assertTrue(safe["ragflow_interactive_api_key_configured"])
        self.assertEqual(safe["ragflow_interactive_owner_id"], "owner-1")
        self.assertEqual(
            safe["ragflow_interactive_chat_model_id"],
            "model@provider",
        )
        self.assertNotIn("ragflow_interactive_api_key", safe)

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.init_calls = []
        try:
            dashboard_server._ragflow_client(  # type: ignore[attr-defined]
                settings,
                interactive=True,
            ).close()
            dashboard_server._ragflow_client(settings).close()  # type: ignore[attr-defined]
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        interactive_args, interactive_kwargs = _FakeRAGFlowClient.init_calls[0]
        primary_args, primary_kwargs = _FakeRAGFlowClient.init_calls[1]
        self.assertEqual(interactive_args[1], "interactive-token")
        self.assertEqual(interactive_kwargs["artifact_owner_id"], "owner-1")
        self.assertEqual(primary_args[1], "ragflow-token")
        self.assertIsNone(primary_kwargs["artifact_owner_id"])

    def test_liveness_and_prometheus_metrics_do_not_require_dashboard_auth(self) -> None:
        store = _store(self)
        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        settings.connector_dashboard_control_enabled = True
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
            )
        )
        port = handle.server.server_address[1]
        try:
            live = json.loads(_get_text(port, "/livez"))
            metrics = _get_text(port, "/metrics")
        finally:
            handle.stop()

        self.assertEqual(live["status"], "alive")
        self.assertIn("sync_jobs_deduplicated_total", metrics)
        self.assertNotIn("user_email", metrics)

    def test_health_status_and_log_endpoints_return_bounded_json(self) -> None:
        store = _store(self)
        store.record_log(level="info", message="server-log", component="unit", sync_id="sync-a")
        original_dashboard_health = dashboard_server.collect_dashboard_health
        original_tls_health = dashboard_server.collect_tls_health
        dashboard_server.collect_dashboard_health = lambda **kwargs: {
            "status": "degraded",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "redis", "status": "error"},
                {"name": "seafile", "status": "error"},
                {"name": "ragflow", "status": "error"},
            ],
        }
        dashboard_server.collect_tls_health = lambda settings: {
            "seafile": {"tls": "failed", "hint": "SEAFILE_CA_BUNDLE prüfen"},
            "ragflow": {"tls": "failed", "hint": "RAGFLOW_CA_BUNDLE prüfen"},
        }
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=_settings(0), started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            health = _get_json(port, "/api/health")
            tls_health = _get_json(port, "/health/tls")
            status = _get_json(port, "/api/status")
            logs = _get_json(port, "/api/logs?limit=1&sync_id=sync-a")
        finally:
            handle.stop()
            dashboard_server.collect_dashboard_health = original_dashboard_health
            dashboard_server.collect_tls_health = original_tls_health

        self.assertEqual(health["status"], "degraded")
        self.assertIn("checks", health)
        checks = {str(item["name"]): item for item in health["checks"]}
        self.assertEqual(checks["database"]["status"], "ok")
        self.assertEqual(checks["redis"]["status"], "error")
        self.assertEqual(checks["seafile"]["status"], "error")
        self.assertEqual(checks["ragflow"]["status"], "error")
        self.assertEqual(tls_health["seafile"]["tls"], "failed")
        self.assertEqual(tls_health["ragflow"]["tls"], "failed")
        self.assertIn("SEAFILE_CA_BUNDLE", tls_health["seafile"]["hint"])
        self.assertIn("RAGFLOW_CA_BUNDLE", tls_health["ragflow"]["hint"])
        self.assertIn("state", status)
        self.assertEqual(logs["limit"], 1)
        self.assertEqual(logs["items"][0]["message"], "server-log")

    def test_audit_export_endpoint_returns_xlsx(self) -> None:
        store = _store(self)
        store.create_sync_run(
            sync_id="sync-export",
            source="seafile:repo",
            target="ragflow:dataset",
            summary="export test",
        )
        store.finish_sync_run(
            sync_id="sync-export",
            status="succeeded",
            objects_checked=1,
            objects_created=1,
            objects_updated=0,
            objects_deleted=0,
            objects_skipped=0,
        )
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=_settings(0), started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            body, content_type, disposition = _get_bytes(port, "/api/audit.xlsx")
        finally:
            handle.stop()

        self.assertTrue(body.startswith(b"PK"))
        self.assertEqual(
            content_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("connector-audit-", disposition)
        self.assertIn(".xlsx", disposition)

    def test_dashboard_basic_auth_challenges_and_accepts_configured_credentials(self) -> None:
        store = _store(self)
        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as missing:
                _get_json(port, "/api/status")
            self.assertEqual(missing.exception.code, 401)
            self.assertIn("Basic", missing.exception.headers.get("WWW-Authenticate", ""))

            with self.assertRaises(HTTPError) as wrong:
                _get_json(port, "/api/status", username="admin", password="wrong")
            self.assertEqual(wrong.exception.code, 401)

            status = _get_json(port, "/api/status", username="admin", password="secret")
        finally:
            handle.stop()

        self.assertIn("state", status)

    def test_dashboard_admin_guard_rejects_unsafe_requests_and_audits_them(self) -> None:
        store = _store(self)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=_admin_settings(0),
                started_at=utcnow(),
                orchestrator=object(),
                job_store=JobStore(store.session_factory),
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as missing_auth:
                _post_json(port, "/api/jobs/dead/cleanup", {})
            with self.assertRaises(HTTPError) as wrong_content_type:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                    content_type="text/plain",
                )
            with self.assertRaises(HTTPError) as missing_header:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                    admin_action=None,
                )
            with self.assertRaises(HTTPError) as same_site:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                    fetch_site="same-site",
                )
            with self.assertRaises(HTTPError) as invalid_fetch_site:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                    fetch_site="unexpected",
                )
            with self.assertRaises(HTTPError) as invalid_json:
                _post_raw(
                    port,
                    "/api/jobs/dead/cleanup",
                    b"{",
                    username="admin",
                    password="secret",
                )
            accepted = _post_json(
                port,
                "/api/jobs/dead/cleanup",
                {},
                username="admin",
                password="secret",
                content_type="application/json; charset=utf-8",
                fetch_site="same-origin",
            )
        finally:
            handle.stop()

        self.assertEqual(missing_auth.exception.code, 401)
        self.assertEqual(wrong_content_type.exception.code, 415)
        self.assertEqual(missing_header.exception.code, 403)
        self.assertEqual(same_site.exception.code, 403)
        self.assertEqual(invalid_fetch_site.exception.code, 403)
        self.assertEqual(invalid_json.exception.code, 400)
        self.assertEqual(accepted["cleaned_jobs"], 0)
        changes = store.list_changes(
            sync_id=None,
            status=None,
            change_type=None,
            query=None,
            limit=100,
            offset=0,
        )["items"]
        details = [item["details"] for item in changes]
        self.assertFalse(any(item.get("actor") == "anonymous" for item in details))
        self.assertTrue(any(item.get("result") == "success" for item in details))
        self.assertNotIn("secret", json.dumps(details))

    def test_dashboard_admin_control_flag_is_fail_closed(self) -> None:
        store = _store(self)
        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as disabled:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                )
        finally:
            handle.stop()

        self.assertEqual(disabled.exception.code, 403)
        change = store.list_changes(
            sync_id=None,
            status=None,
            change_type=None,
            query=None,
            limit=1,
            offset=0,
        )["items"][0]
        self.assertEqual(change["details"]["actor"], "admin")
        self.assertEqual(change["details"]["result"], "rejected")

    def test_authz_check_route_allows_and_denies_without_dashboard_enabled(self) -> None:
        store = _store(self)
        now = utcnow()
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Anleitungen",
                    name_slug="anleitungen",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Anleitungen",
                )
            )
            session.add(
                SearchProfile(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Anleitungen",
                    display_name="Anleitungen",
                    kind="documents",
                    enabled=True,
                    status="ready",
                    last_acl_sync_at=now,
                )
            )
            session.add(
                LibraryACLEffectiveUser(
                    repo_id="repo-1",
                    user_email="olaf@example.local",
                    permission="rw",
                    sources=["user_share"],
                    last_seen_at=now,
                )
            )
            session.commit()
        settings = _settings(0)
        settings.connector_dashboard_enabled = False
        settings.authz_api_enabled = True
        settings.authz_api_shared_secret = "authz-secret"
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            allowed = _post_json_bearer(
                port,
                "/api/authz/check",
                {
                    "user": {"username": "olaf", "email": "OLAF@EXAMPLE.LOCAL"},
                    "resource": {"ragflow_dataset_id": "dataset-1"},
                    "operation": "search",
                },
                "authz-secret",
            )
            denied = _post_json_bearer(
                port,
                "/api/authz/check",
                {
                    "user": {"username": "alfred", "email": "alfred@example.local"},
                    "resource": {"repo_id": "repo-1"},
                    "operation": "search",
                },
                "authz-secret",
            )
        finally:
            handle.stop()

        self.assertEqual(allowed["decision"], "allow")
        self.assertEqual(allowed["permission"], "rw")
        self.assertEqual(denied["decision"], "deny")
        self.assertEqual(denied["reason"], "user_not_in_library_acl")

    def test_authz_filter_profiles_returns_user_facing_profile_fields(self) -> None:
        store = _store(self)
        now = utcnow()
        with store.session_factory() as session:
            session.add(
                SearchProfile(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Anleitungen",
                    display_name="Anleitungen",
                    kind="documents",
                    enabled=True,
                    status="ready",
                    last_acl_sync_at=now,
                )
            )
            session.add(
                LibraryACLEffectiveUser(
                    repo_id="repo-1",
                    user_email="olaf@example.local",
                    permission="rw",
                    sources=["user_share"],
                    last_seen_at=now,
                )
            )
            session.commit()
        settings = _settings(0)
        settings.connector_dashboard_enabled = False
        settings.authz_api_enabled = True
        settings.authz_api_shared_secret = "authz-secret"
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            result = _post_json_bearer(
                port,
                "/api/authz/filter-profiles",
                {
                    "user": {"username": "olaf", "email": "olaf@example.local"},
                    "profile_ids": ["repo-1"],
                },
                "authz-secret",
            )
        finally:
            handle.stop()

        self.assertEqual(result["denied"], [])
        self.assertEqual(result["allowed"][0]["profile_id"], "repo-1")
        self.assertEqual(result["allowed"][0]["id"], "repo-1")
        self.assertEqual(result["allowed"][0]["display_name"], "Anleitungen")
        self.assertEqual(result["allowed"][0]["kind"], "documents")
        self.assertEqual(result["allowed"][0]["status"], "ready")
        self.assertEqual(result["allowed"][0]["permission"], "rw")

    def test_search_document_proxy_does_not_call_seafile_on_authz_deny(self) -> None:
        store = _store(self)
        _add_search_profile_with_acl(store, user_email="olaf@example.local")
        settings = _settings(0)
        settings.authz_api_shared_secret = "authz-secret"
        original_client = dashboard_server.SeafileSyncClient
        dashboard_server.SeafileSyncClient = _FakeDocumentSeafileClient  # type: ignore[assignment]
        _FakeDocumentSeafileClient.downloads = []
        try:
            body, status, _headers = dashboard_server._handle_search_document(
                DashboardContext(store=store, settings=settings, started_at=utcnow()),
                {"repo_id": ["repo-1"], "path": ["/report.pdf"]},
                "Bearer authz-secret",
                "127.0.0.1",
                "alfred",
                "alfred@example.local",
            )
        finally:
            dashboard_server.SeafileSyncClient = original_client  # type: ignore[assignment]

        self.assertEqual(status.value, 403)
        self.assertIn(b"forbidden", body)
        self.assertEqual(_FakeDocumentSeafileClient.downloads, [])

    def test_search_document_proxy_serves_pdf_inline_after_authz_allow(self) -> None:
        store = _store(self)
        _add_search_profile_with_acl(store, user_email="olaf@example.local")
        settings = _settings(0)
        settings.authz_api_shared_secret = "authz-secret"
        original_client = dashboard_server.SeafileSyncClient
        dashboard_server.SeafileSyncClient = _FakeDocumentSeafileClient  # type: ignore[assignment]
        _FakeDocumentSeafileClient.downloads = []
        _FakeDocumentSeafileClient.body = b"%PDF-1.7"
        try:
            body, status, headers = dashboard_server._handle_search_document(
                DashboardContext(store=store, settings=settings, started_at=utcnow()),
                {"repo_id": ["repo-1"], "path": ["/report.pdf"]},
                "Bearer authz-secret",
                "127.0.0.1",
                "olaf",
                "olaf@example.local",
            )
        finally:
            dashboard_server.SeafileSyncClient = original_client  # type: ignore[assignment]

        self.assertEqual(status.value, 200)
        self.assertEqual(body, b"%PDF-1.7")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("inline", headers["Content-Disposition"])
        self.assertEqual(_FakeDocumentSeafileClient.downloads, [("repo-1", "/report.pdf")])

    def test_search_document_proxy_serves_html_as_plain_text(self) -> None:
        store = _store(self)
        _add_search_profile_with_acl(store, user_email="olaf@example.local")
        settings = _settings(0)
        settings.authz_api_shared_secret = "authz-secret"
        original_client = dashboard_server.SeafileSyncClient
        dashboard_server.SeafileSyncClient = _FakeDocumentSeafileClient  # type: ignore[assignment]
        _FakeDocumentSeafileClient.downloads = []
        _FakeDocumentSeafileClient.body = b"<html><script>alert(1)</script></html>"
        try:
            body, status, headers = dashboard_server._handle_search_document(
                DashboardContext(store=store, settings=settings, started_at=utcnow()),
                {"repo_id": ["repo-1"], "path": ["/index.html"]},
                "Bearer authz-secret",
                "127.0.0.1",
                "olaf",
                "olaf@example.local",
            )
        finally:
            dashboard_server.SeafileSyncClient = original_client  # type: ignore[assignment]

        self.assertEqual(status.value, 200)
        self.assertEqual(body, b"<html><script>alert(1)</script></html>")
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("inline", headers["Content-Disposition"])

    def test_workflow_libraries_lists_api_visible_libraries_with_control_state(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            library = Library(
                repo_id="repo-1",
                name="Demo",
                name_slug="demo",
                status="active",
                ragflow_dataset_id="dataset-1",
                ragflow_dataset_name="Demo Dataset",
                head_commit_id="head-old",
                last_synced_commit_id="head-old",
            )
            session.add(library)
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                    sync_status="synced",
                )
            )
            first_file = File(
                repo_id="repo-1",
                path="/done.pdf",
                normalized_path="/done.pdf",
                ingestion_strategy="direct",
            )
            second_file = File(
                repo_id="repo-1",
                path="/pending.pdf",
                normalized_path="/pending.pdf",
                ingestion_strategy="direct",
            )
            session.add_all([first_file, second_file])
            session.flush()
            session.add_all(
                [
                    FileDocumentVersion(
                        file_id=first_file.id,
                        repo_id="repo-1",
                        normalized_path="/done.pdf",
                        dataset_id="dataset-1",
                        document_name="done-old.pdf",
                        state="dead",
                    ),
                    FileDocumentVersion(
                        file_id=first_file.id,
                        repo_id="repo-1",
                        normalized_path="/done.pdf",
                        dataset_id="dataset-1",
                        document_name="done.pdf",
                        state="current",
                    ),
                    FileDocumentVersion(
                        file_id=second_file.id,
                        repo_id="repo-1",
                        normalized_path="/pending.pdf",
                        dataset_id="dataset-1",
                        document_name="pending.pdf",
                        state="parsing",
                    ),
                ]
            )
            session.commit()
        orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
        job_store = JobStore(store.session_factory)
        settings = _admin_settings(0)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
                orchestrator=orchestrator,
                openwebui_sync_service=_FakeWorkflowOpenWebUI(),
                job_store=job_store,
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            data = _get_json(
                port,
                "/api/workflow/libraries",
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()

        self.assertTrue(data["enabled"])
        self.assertEqual(data["summary"]["visible"], 2)
        self.assertEqual(data["summary"]["selectable"], 1)
        libraries = {str(item["repo_id"]): item for item in data["libraries"]}
        self.assertEqual(libraries["repo-1"]["ragflow_dataset_id"], "dataset-1")
        self.assertEqual(libraries["repo-1"]["openwebui"]["openwebui_pipe_id"], "pipe-1")
        self.assertEqual(libraries["repo-1"]["admin_state"], "active")
        self.assertEqual(libraries["repo-1"]["admin_control"]["state"], "active")
        self.assertEqual(
            libraries["repo-1"]["parsing"],
            {
                "tracked": 2,
                "total": 2,
                "done": 1,
                "completed": 1,
                "pending": 1,
                "running": 1,
                "failed": 0,
                "percent": 50.0,
            },
        )
        self.assertFalse(libraries["repo-2"]["selectable"])
        self.assertEqual(libraries["repo-2"]["skip_reason"], "encrypted")

    def test_workflow_global_and_library_control_actions_are_persistent_and_audited(self) -> None:
        store = _store(self)
        orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
        job_store = JobStore(store.session_factory)
        signal_queue = _FakeWorkflowSignalQueue()
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=_admin_settings(0),
                started_at=utcnow(),
                orchestrator=orchestrator,
                job_store=job_store,
                signal_queue=signal_queue,
            )
        )
        port = handle.server.server_address[1]
        try:
            initial = _get_json(
                port,
                "/api/workflow/control",
                username="admin",
                password="secret",
            )
            started = _post_json(
                port,
                "/api/workflow/control/start",
                {},
                username="admin",
                password="secret",
            )
            paused = _post_json(
                port,
                "/api/workflow/control/pause",
                {},
                username="admin",
                password="secret",
            )
            resumed = _post_json(
                port,
                "/api/workflow/control/resume",
                {},
                username="admin",
                password="secret",
            )
            library_paused = _post_json(
                port,
                "/api/workflow/libraries/repo-1/pause",
                {},
                username="admin",
                password="secret",
            )
            library_resumed = _post_json(
                port,
                "/api/workflow/libraries/repo-1/resume",
                {},
                username="admin",
                password="secret",
            )
            deactivated = _post_json(
                port,
                "/api/workflow/control/deactivate",
                {},
                username="admin",
                password="secret",
            )
            with self.assertRaises(HTTPError) as missing_confirmation:
                _post_json(
                    port,
                    "/api/workflow/control/stop",
                    {},
                    username="admin",
                    password="secret",
                )
            stopped = _post_json(
                port,
                "/api/workflow/control/stop",
                {"confirm": "STOP"},
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()

        self.assertTrue(initial["control_enabled"])
        self.assertEqual(
            set(initial["active_jobs"]),
            {"queued", "retrying", "running", "paused"},
        )
        self.assertEqual(started["jobs"][0]["job_type"], JobType.DISCOVER_LIBRARIES.value)
        discovery_job = job_store.get(int(started["jobs"][0]["job_id"]))
        self.assertIsNotNone(discovery_job)
        assert discovery_job is not None
        self.assertEqual(discovery_job.payload["trigger"], "admin_start")
        self.assertEqual(paused["state"], "paused")
        self.assertEqual(resumed["state"], "running")
        self.assertEqual(library_paused["admin_state"], "paused")
        self.assertEqual(library_resumed["admin_state"], "active")
        self.assertEqual(deactivated["state"], "deactivated")
        self.assertEqual(missing_confirmation.exception.code, 400)
        self.assertEqual(stopped["state"], "stopped")
        details = [
            item["details"]
            for item in store.list_changes(
                sync_id=None,
                status=None,
                change_type=None,
                query=None,
                limit=100,
                offset=0,
            )["items"]
        ]
        self.assertTrue(
            any(
                item.get("actor") == "admin"
                and item.get("action") == "stop"
                and item.get("result") == "success"
                for item in details
            )
        )

    def test_workflow_run_enqueues_selected_library_and_returns_parent_status(self) -> None:
        store = _store(self)
        orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
        openwebui = _FakeWorkflowOpenWebUI()
        job_store = JobStore(store.session_factory)
        signal_queue = _FakeWorkflowSignalQueue()
        settings = _admin_settings(0)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
                orchestrator=orchestrator,
                openwebui_sync_service=openwebui,
                job_store=job_store,
                signal_queue=signal_queue,
            )
        )
        port = handle.server.server_address[1]
        try:
            data = _post_json(
                port,
                "/api/workflow/runs",
                {
                    "repo_ids": ["repo-1"],
                    "create_dataset": True,
                    "sync_openwebui": True,
                    "mode": "delta",
                    "scope": "/Admin",
                },
                username="admin",
                password="secret",
            )
            status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            child_run_id = dashboard_server.SyncStateStore(
                store.session_factory
            ).create_run(
                repo_id="repo-1",
                mode="delta",
                parent_run_id=data["run_id"],
                job_id=data["jobs"][0]["job_id"],
                progress={
                    "phase": "syncing",
                    "changes": 10,
                    "processed": 3,
                    "total": 10,
                    "completed": 3,
                    "percent": 30.0,
                },
            )
            progressing_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            dashboard_server.SyncStateStore(store.session_factory).update_run(
                child_run_id,
                status="succeeded",
                progress={
                    "phase": "completed",
                    "changes": 10,
                    "processed": 10,
                    "total": 10,
                    "completed": 10,
                    "percent": 100.0,
                },
                finished=True,
            )
            terminal_child_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            paused = _post_json(
                port,
                f"{data['status_url']}/pause",
                {},
                username="admin",
                password="secret",
            )
            paused_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            resumed = _post_json(
                port,
                f"{data['status_url']}/resume",
                {},
                username="admin",
                password="secret",
            )
            with self.assertRaises(HTTPError) as missing_cancel_confirmation:
                _post_json(
                    port,
                    f"{data['status_url']}/cancel",
                    {},
                    username="admin",
                    password="secret",
                )
            cancelled = _post_json(
                port,
                f"{data['status_url']}/cancel",
                {"confirm": "STOP"},
                username="admin",
                password="secret",
            )
            cancelled_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            with self.assertRaises(HTTPError) as terminal_pause:
                _post_json(
                    port,
                    f"{data['status_url']}/pause",
                    {},
                    username="admin",
                    password="secret",
                )
            retried = _post_json(
                port,
                f"{data['status_url']}/retry",
                {},
                username="admin",
                password="secret",
            )
            retried_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            with self.assertRaises(HTTPError) as missing_stop_confirmation:
                _post_json(
                    port,
                    f"{data['status_url']}/stop",
                    {},
                    username="admin",
                    password="secret",
                )
            stopped = _post_json(
                port,
                f"{data['status_url']}/stop",
                {"confirm": "STOP"},
                username="admin",
                password="secret",
            )
            stopped_status = _get_json(
                port, data["status_url"], username="admin", password="secret"
            )
            with self.assertRaises(HTTPError) as stopped_resume:
                _post_json(
                    port,
                    f"{data['status_url']}/resume",
                    {},
                    username="admin",
                    password="secret",
                )
        finally:
            handle.stop()

        self.assertEqual(data["status"], "queued")
        self.assertEqual(status["status"], "queued")
        self.assertEqual(
            status["progress"],
            {"completed": 0, "total": 1, "percent": 0.0},
        )
        self.assertEqual(status["phase"], "files")
        self.assertIsInstance(status["phases"], list)
        self.assertEqual(status["phases"][0]["name"], "files")
        self.assertEqual(status["libraries"][0]["repo_id"], "repo-1")
        self.assertEqual(
            progressing_status["libraries"][0]["progress"],
            {"completed": 3, "total": 10, "percent": 30.0},
        )
        self.assertEqual(progressing_status["progress"]["percent"], 30.0)
        self.assertEqual(
            terminal_child_status["libraries"][0]["progress"],
            {"completed": 10, "total": 10, "percent": 100.0},
        )
        self.assertEqual(terminal_child_status["progress"]["percent"], 100.0)
        self.assertEqual(status["jobs"][0]["phase"], "files")
        self.assertEqual(status["jobs"][0]["percent"], 0.0)
        self.assertEqual(data["trigger"], "manual")
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused_status["status"], "paused")
        self.assertTrue(paused_status["paused"])
        self.assertIn(resumed["status"], {"queued", "running"})
        self.assertEqual(missing_cancel_confirmation.exception.code, 400)
        self.assertEqual(cancelled["action"], "cancel")
        self.assertEqual(cancelled_status["status"], "cancelled")
        self.assertEqual(terminal_pause.exception.code, 409)
        self.assertEqual(retried["action"], "retry")
        self.assertEqual(retried_status["status"], "queued")
        self.assertEqual(missing_stop_confirmation.exception.code, 400)
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped_status["status"], "stopped")
        self.assertEqual(stopped_resume.exception.code, 409)
        self.assertEqual(orchestrator.synced, [])
        self.assertEqual(openwebui.repo_ids, [])
        self.assertGreaterEqual(signal_queue.job_ids.count(data["jobs"][0]["job_id"]), 3)
        job = job_store.get(data["jobs"][0]["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.job_type, JobType.SYNC_LIBRARY_DELTA.value)
        self.assertEqual(job.payload["scope"], "/Admin")
        self.assertTrue(job.payload["sync_openwebui"])
        self.assertEqual(job.payload["trigger"], "manual")

    def test_workflow_run_maps_every_manual_mode_to_the_expected_job_spec(self) -> None:
        store = _store(self)
        job_store = JobStore(store.session_factory)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=_admin_settings(0),
                started_at=utcnow(),
                orchestrator=_FakeWorkflowOrchestrator(store.session_factory),
                openwebui_sync_service=_FakeWorkflowOpenWebUI(),
                job_store=job_store,
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        expected_types = {
            "delta": JobType.SYNC_LIBRARY_DELTA,
            "full": JobType.SYNC_LIBRARY_FULL,
            "reconcile": JobType.RECONCILE_LIBRARY,
        }
        try:
            for mode, expected_type in expected_types.items():
                with self.subTest(mode=mode):
                    response = _post_json(
                        port,
                        "/api/workflow/runs",
                        {
                            "repo_ids": ["repo-1"],
                            "create_dataset": True,
                            "sync_openwebui": False,
                            "mode": mode,
                            "scope": f"/{mode}",
                        },
                        username="admin",
                        password="secret",
                    )
                    job = job_store.get(int(response["jobs"][0]["job_id"]))
                    self.assertIsNotNone(job)
                    assert job is not None
                    self.assertEqual(job.job_type, expected_type.value)
                    self.assertEqual(job.repo_id, "repo-1")
                    self.assertEqual(job.payload["scope"], f"/{mode}")
                    self.assertEqual(job.payload["workflow_run_id"], response["run_id"])
                    self.assertFalse(job.payload["sync_openwebui"])
        finally:
            handle.stop()

    def test_workflow_status_keeps_controls_when_dead_and_active_jobs_are_mixed(self) -> None:
        store = _store(self)
        orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
        orchestrator.raw_libraries.append(
            {
                "id": "repo-3",
                "name": "Weitere Bibliothek",
                "head_commit_id": "head-3",
            }
        )
        job_store = JobStore(store.session_factory)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=_admin_settings(0),
                started_at=utcnow(),
                orchestrator=orchestrator,
                openwebui_sync_service=_FakeWorkflowOpenWebUI(),
                job_store=job_store,
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            response = _post_json(
                port,
                "/api/workflow/runs",
                {
                    "repo_ids": ["repo-1", "repo-3"],
                    "create_dataset": True,
                    "sync_openwebui": False,
                    "mode": "delta",
                },
                username="admin",
                password="secret",
            )
            failed_job_id = int(response["jobs"][0]["job_id"])
            acquired = job_store.acquire_next("failure-worker")
            self.assertIsNotNone(acquired)
            assert acquired is not None
            self.assertEqual(acquired.id, failed_job_id)
            self.assertEqual(
                job_store.mark_failed(
                    failed_job_id,
                    "injected failure",
                    worker_id="failure-worker",
                    retryable=False,
                ),
                JobStatus.DEAD,
            )
            status = _get_json(
                port,
                response["status_url"],
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()

        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["phase"], "files")
        self.assertEqual(status["phases"][0]["status"], "queued")
        self.assertEqual(
            status["capabilities"]["run_actions"],
            ["pause", "stop", "cancel"],
        )
        self.assertIsNone(status["finished_at"])

    def test_partial_multi_library_scheduling_failure_is_visible_and_aborted(self) -> None:
        for failure_operation in ("enqueue", "subscribe"):
            with self.subTest(failure_operation=failure_operation):
                store = _store(self)
                orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
                orchestrator.raw_libraries.append(
                    {
                        "id": "repo-3",
                        "name": "Weitere Bibliothek",
                        "head_commit_id": "head-3",
                    }
                )
                job_store = _FailingWorkflowJobStore(
                    store.session_factory,
                    operation=failure_operation,
                    fail_on_call=2,
                )
                signal_queue = _FakeWorkflowSignalQueue()
                handle = start_dashboard_server(
                    DashboardContext(
                        store=store,
                        settings=_admin_settings(0),
                        started_at=utcnow(),
                        orchestrator=orchestrator,
                        openwebui_sync_service=_FakeWorkflowOpenWebUI(),
                        job_store=job_store,
                        signal_queue=signal_queue,
                    )
                )
                port = handle.server.server_address[1]
                try:
                    with self.assertRaises(HTTPError) as raised:
                        _post_json(
                            port,
                            "/api/workflow/runs",
                            {
                                "repo_ids": ["repo-1", "repo-3"],
                                "create_dataset": True,
                                "sync_openwebui": False,
                                "mode": "full",
                            },
                            username="admin",
                            password="secret",
                        )
                    error_payload = json.loads(
                        raised.exception.read().decode("utf-8")
                    )
                    run_status = _get_json(
                        port,
                        error_payload["status_url"],
                        username="admin",
                        password="secret",
                    )
                finally:
                    handle.stop()

                self.assertEqual(raised.exception.code, 500)
                self.assertEqual(error_payload["status"], "failed")
                self.assertEqual(run_status["status"], "failed")
                self.assertEqual(run_status["capabilities"]["run_actions"], [])
                self.assertTrue(run_status["finished_at"])
                self.assertTrue(run_status["jobs"])
                self.assertEqual(signal_queue.job_ids, [])
                for item in error_payload["jobs"]:
                    job = job_store.get(int(item["job_id"]))
                    self.assertIsNotNone(job)
                    assert job is not None
                    self.assertEqual(job.status, JobStatus.CANCELLED.value)
                audit_details = [
                    item["details"]
                    for item in store.list_changes(
                        sync_id=None,
                        status=None,
                        change_type=None,
                        query=None,
                        limit=100,
                        offset=0,
                    )["items"]
                ]
                self.assertTrue(
                    any(
                        item.get("target") == f"workflow:{error_payload['run_id']}"
                        and item.get("action") == "start"
                        and item.get("result") == "failed"
                        for item in audit_details
                    )
                )

    def test_cleanup_terminal_outbox_states_are_successful_workflow_steps(self) -> None:
        for status in ("completed", "cancelled", "superseded"):
            with self.subTest(status=status):
                self.assertEqual(
                    dashboard_server._workflow_cleanup_status(status),
                    JobStatus.SUCCEEDED.value,
                )

    def test_cleanup_retry_stays_accepted_when_queue_signal_fails(self) -> None:
        store = _store(self)
        orchestrator = _FakeWorkflowOrchestrator(store.session_factory)
        job_store = JobStore(store.session_factory)
        settings = _admin_settings(0)
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
                orchestrator=orchestrator,
                openwebui_sync_service=_FakeWorkflowOpenWebUI(),
                job_store=job_store,
                signal_queue=_FailingWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            response = _post_json(
                port,
                "/api/cleanup-outbox/42/retry",
                {},
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()

        self.assertTrue(response["retried"])
        self.assertEqual(response["signal_warning"], "ConnectionError")
        job = job_store.get(int(response["job_id"]))
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.status, JobStatus.QUEUED.value)

    def test_dead_job_cleanup_endpoint_requires_dashboard_auth_and_clears_dead_jobs(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                SyncJob(
                    job_type=JobType.SYNC_LIBRARY_FULL.value,
                    repo_id="repo-1",
                    dedup_key="test:dead:server",
                    payload={},
                    status=JobStatus.DEAD.value,
                    error_message="old failure",
                )
            )
            session.commit()
        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        settings.connector_dashboard_control_enabled = True
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
                orchestrator=object(),
                job_store=JobStore(store.session_factory),
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as missing_auth:
                _post_json(port, "/api/jobs/dead/cleanup", {})
            self.assertEqual(missing_auth.exception.code, 401)
            data = _post_json(
                port,
                "/api/jobs/dead/cleanup",
                {},
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()

        self.assertEqual(data["cleaned_jobs"], 1)
        self.assertEqual(data["remaining_dead_jobs"], 0)
        with store.session_factory() as session:
            job = session.query(SyncJob).one()
            self.assertEqual(job.status, JobStatus.CANCELLED.value)

    def test_standalone_dashboard_rejects_authorized_admin_mutation_without_side_effects(
        self,
    ) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                SyncJob(
                    job_type=JobType.SYNC_LIBRARY_FULL.value,
                    repo_id="repo-standalone",
                    dedup_key="test:dead:standalone",
                    payload={},
                    status=JobStatus.DEAD.value,
                )
            )
            session.commit()
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=_admin_settings(0),
                started_at=utcnow(),
            )
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as unavailable:
                _post_json(
                    port,
                    "/api/jobs/dead/cleanup",
                    {},
                    username="admin",
                    password="secret",
                )
        finally:
            handle.stop()

        self.assertEqual(unavailable.exception.code, 503)
        with store.session_factory() as session:
            job = session.query(SyncJob).one()
            self.assertEqual(job.status, JobStatus.DEAD.value)

    def test_openwebui_delete_pipe_endpoint_requires_auth_and_resets_mapping(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                )
            )
            mapping = OpenWebUIDatasetMapping(
                repo_id="repo-1",
                ragflow_dataset_id="dataset-1",
                ragflow_dataset_name="Dataset",
                ragflow_chat_id="chat-1",
                openwebui_pipe_id="ragflow_pipe_demo_dataset1",
                openwebui_model_name="ragflow/demo",
                pipe_definition_hash="hash",
                openwebui_pipe_payload={"id": "ragflow_pipe_demo_dataset1"},
                sync_status="synced",
            )
            session.add(mapping)
            session.commit()
            mapping_id = int(mapping.id)

        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        settings.connector_dashboard_control_enabled = True
        settings.openwebui_admin_api_key = "admin-key"
        original_openwebui = dashboard_server.OpenWebUIClient
        dashboard_server.OpenWebUIClient = _FakeOpenWebUIAdminClient  # type: ignore[assignment]
        _FakeOpenWebUIAdminClient.functions = {
            "ragflow_pipe_demo_dataset1": {
                "id": "ragflow_pipe_demo_dataset1",
                "type": "pipe",
                "meta": {
                    "manifest": {
                        "owner": "seafile-ragflow-connector",
                        "artifact_version": "25",
                    }
                },
            }
        }
        _FakeOpenWebUIAdminClient.deleted_functions = []
        handle = start_dashboard_server(
            DashboardContext(
                store=store,
                settings=settings,
                started_at=utcnow(),
                orchestrator=object(),
                job_store=JobStore(store.session_factory),
                signal_queue=_FakeWorkflowSignalQueue(),
            )
        )
        port = handle.server.server_address[1]
        try:
            with self.assertRaises(HTTPError) as missing_auth:
                _post_json(
                    port,
                    "/api/openwebui/artifacts/delete",
                    {"mapping_id": mapping_id, "target": "pipe"},
                )
            self.assertEqual(missing_auth.exception.code, 401)
            data = _post_json(
                port,
                "/api/openwebui/artifacts/delete",
                {"mapping_id": mapping_id, "target": "pipe"},
                username="admin",
                password="secret",
            )
        finally:
            handle.stop()
            dashboard_server.OpenWebUIClient = original_openwebui  # type: ignore[assignment]

        self.assertEqual(data["status"], "deleted")
        self.assertFalse(data["library_deleted"])
        self.assertEqual(
            _FakeOpenWebUIAdminClient.deleted_functions,
            ["ragflow_pipe_demo_dataset1"],
        )
        with store.session_factory() as session:
            stored = session.get(OpenWebUIDatasetMapping, mapping_id)
            self.assertIsNotNone(stored)
            self.assertIsNone(stored.openwebui_pipe_id)
            self.assertIsNone(stored.openwebui_model_name)
            self.assertIsNone(stored.pipe_definition_hash)
            self.assertEqual(stored.openwebui_pipe_payload, {})
            self.assertEqual(stored.sync_status, "pending")

    def test_openwebui_delete_pipe_ownership_rejects_dataset_mismatch(self) -> None:
        artifact = {
            "id": "ragflow_pipe_demo_otherdataset",
            "type": "pipe",
            "meta": {
                "manifest": {
                    "owner": "seafile-ragflow-connector",
                    "artifact_version": "25",
                }
            },
        }
        self.assertFalse(
            dashboard_server._is_owned_openwebui_artifact(  # type: ignore[attr-defined]
                artifact,
                expected_kind="pipe",
                dataset_id="dataset-1",
            )
        )

    def test_openwebui_delete_chat_endpoint_clears_chat_without_library_delete(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                )
            )
            mapping = OpenWebUIDatasetMapping(
                repo_id="repo-1",
                ragflow_dataset_id="dataset-1",
                ragflow_dataset_name="Dataset",
                ragflow_chat_id="chat-1",
                openwebui_pipe_id="pipe-1",
                pipe_definition_hash="hash",
                sync_status="synced",
            )
            session.add(mapping)
            session.commit()
            mapping_id = int(mapping.id)

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.deleted_chats = []
        short_id = sha256(b"dataset-1").hexdigest()[:8]
        _FakeRAGFlowClient.chats = {
            "chat-1": {
                "id": "chat-1",
                "name": f"RAG_dataset_{short_id}",
                "dataset_ids": ["dataset-1"],
            }
        }
        try:
            handle = start_dashboard_server(
                DashboardContext(
                    store=store,
                    settings=_admin_settings(0),
                    started_at=utcnow(),
                    orchestrator=object(),
                    job_store=JobStore(store.session_factory),
                    signal_queue=_FakeWorkflowSignalQueue(),
                )
            )
            port = handle.server.server_address[1]
            try:
                data = _post_json(
                    port,
                    "/api/openwebui/artifacts/delete",
                    {"mapping_id": mapping_id, "target": "chat"},
                    username="admin",
                    password="secret",
                )
            finally:
                handle.stop()
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(data["status"], "deleted")
        self.assertFalse(data["library_deleted"])
        self.assertEqual(_FakeRAGFlowClient.deleted_chats, [["chat-1"]])
        with store.session_factory() as session:
            library = session.get(Library, "repo-1")
            stored = session.get(OpenWebUIDatasetMapping, mapping_id)
            self.assertEqual(library.status, "active")
            self.assertEqual(library.ragflow_dataset_id, "dataset-1")
            self.assertIsNone(stored.ragflow_chat_id)
            self.assertIsNone(stored.pipe_definition_hash)
            self.assertEqual(stored.sync_status, "pending")

    def test_openwebui_delete_chat_ownership_rejects_dataset_mismatch(self) -> None:
        short_id = sha256(b"other-dataset").hexdigest()[:8]
        artifact = {
            "id": "chat-1",
            "name": f"RAG_dataset_{short_id}",
            "dataset_ids": ["other-dataset"],
        }
        self.assertFalse(
            dashboard_server._is_owned_ragflow_chat_artifact(  # type: ignore[attr-defined]
                artifact,
                dataset_id="dataset-1",
            )
        )

    def test_openwebui_delete_dataset_endpoint_clears_dataset_binding_not_library(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    last_synced_commit_id="head-1",
                    template_hash="template",
                )
            )
            mapping = OpenWebUIDatasetMapping(
                repo_id="repo-1",
                ragflow_dataset_id="dataset-1",
                ragflow_dataset_name="Dataset",
                ragflow_chat_id="chat-1",
                openwebui_pipe_id="pipe-1",
                sync_status="synced",
            )
            session.add(mapping)
            session.commit()
            mapping_id = int(mapping.id)

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.deleted_datasets = []
        try:
            handle = start_dashboard_server(
                DashboardContext(
                    store=store,
                    settings=_admin_settings(0),
                    started_at=utcnow(),
                    orchestrator=object(),
                    job_store=JobStore(store.session_factory),
                    signal_queue=_FakeWorkflowSignalQueue(),
                )
            )
            port = handle.server.server_address[1]
            try:
                data = _post_json(
                    port,
                    "/api/openwebui/artifacts/delete",
                    {"mapping_id": mapping_id, "target": "dataset"},
                    username="admin",
                    password="secret",
                )
            finally:
                handle.stop()
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(data["status"], "deleted")
        self.assertFalse(data["library_deleted"])
        self.assertEqual(_FakeRAGFlowClient.deleted_datasets, [["dataset-1"]])
        with store.session_factory() as session:
            library = session.get(Library, "repo-1")
            stored = session.get(OpenWebUIDatasetMapping, mapping_id)
            self.assertEqual(library.status, "active")
            self.assertIsNone(library.ragflow_dataset_id)
            self.assertIsNone(library.ragflow_dataset_name)
            self.assertIsNone(library.template_hash)
            self.assertIsNone(library.last_synced_commit_id)
            self.assertEqual(stored.ragflow_dataset_id, "dataset-1")
            self.assertEqual(stored.ragflow_chat_id, "chat-1")
            self.assertEqual(stored.openwebui_pipe_id, "pipe-1")
            self.assertEqual(stored.sync_status, "dataset_deleted")

    def test_openwebui_preview_route_uses_signed_token_without_dashboard_auth(self) -> None:
        store = _store(self)
        settings = _settings(0)
        settings.connector_dashboard_auth_username = "admin"
        settings.connector_dashboard_auth_password = "secret"
        token = sign_preview_payload(
            {
                "document_name": "report.pdf",
                "citation_label": "Quelle 1",
                "source_path": "/report.pdf",
                "original_url": "https://seafile.local/lib/repo-1/file/report.pdf#page=1",
                "snippet": "Signierter Treffer",
            },
            "proxy-secret",
        )
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            html = _get_text(port, f"/api/openwebui/sources/preview?token={token}")
            alias_html = _get_text(port, f"/api/sources/preview?token={token}")
        finally:
            handle.stop()

        self.assertIn("Signierter Treffer", html)
        self.assertIn("Original öffnen", html)
        self.assertIn("Signierter Treffer", alias_html)
        self.assertIn("Original öffnen", alias_html)

    def test_dashboard_and_preview_send_defensive_security_headers(self) -> None:
        store = _store(self)
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "report.pdf",
                "citation_label": "Quelle 1",
                "source_path": "/report.pdf",
                "snippet": "Signierter Treffer",
            },
            "proxy-secret",
        )
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=settings, started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            _, dashboard_headers = _get_text_with_headers(port, "/dashboard")
            _, preview_headers = _get_text_with_headers(
                port, f"/api/openwebui/sources/preview?token={token}"
            )
        finally:
            handle.stop()

        for headers in (dashboard_headers, preview_headers):
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            csp = headers.get("Content-Security-Policy", "")
            self.assertIn("default-src 'self'", csp)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertIn("object-src 'none'", csp)

    def test_openwebui_mapping_requires_assigned_tool_and_pipe(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        mapping = _load_mapping(store, dataset_id="dataset-1", tool_id="tool-1")

        self.assertEqual(mapping.openwebui_tool_id, "tool-1")
        with self.assertRaises(ValueError):
            _load_mapping(store, dataset_id="dataset-1", tool_id="other-tool")
        with self.assertRaises(ValueError):
            _load_mapping(store, dataset_id="dataset-1", chat_id="chat-1", pipe_id="other-pipe")

    def test_openwebui_mapping_rejects_deleted_library(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(
                Library(repo_id="repo-1", name="Demo", name_slug="demo", status="deleted")
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    openwebui_tool_id="tool-1",
                )
            )
            session.commit()

        with self.assertRaises(ValueError):
            _load_mapping(store, dataset_id="dataset-1", tool_id="tool-1")

    def test_openwebui_chat_proxy_uses_requested_openwebui_model(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.last_model = None
        _FakeRAGFlowClient.raise_chat_error = False
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=_settings(0), started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "model": "ragflow/openwebui-model-id",
                    "messages": [{"role": "user", "content": "Frage"}],
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(result["answer"], "RAGFlow liefert eine echte Antwort.")
        self.assertEqual(result["diagnostics"]["answer_path"], "choices[0].message.content")
        self.assertEqual(result["diagnostics"]["reference_path"], "choices[0].message.reference")
        self.assertEqual(_FakeRAGFlowClient.last_model, "ragflow/openwebui-model-id")

    def test_openwebui_chat_proxy_falls_back_to_retrieval_when_chat_fails(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo-1",
                    path="/demo.txt",
                    normalized_path="/demo.txt",
                    ragflow_document_id="doc-1",
                    ragflow_document_name="demo.txt",
                    ingestion_strategy="direct",
                    sync_status="synced",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.raise_chat_error = True
        _FakeRAGFlowClient.retrieve_calls = 0
        _FakeRAGFlowClient.retrieval_result = {
            "chunks": [
                {
                    "id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "Fallbacktext aus RAGFlow Retrieval",
                }
            ]
        }
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=_settings(0), started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "messages": [{"role": "user", "content": "Frage"}],
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]
            _FakeRAGFlowClient.raise_chat_error = False
            _FakeRAGFlowClient.retrieval_result = {"chunks": []}

        self.assertEqual(_FakeRAGFlowClient.retrieve_calls, 1)
        self.assertEqual(result["answer"], "")
        self.assertTrue(result["retrieval_only"])
        self.assertFalse(result["citations_emitted"])
        self.assertIn("Nachweise", result["source_markdown"])
        self.assertIn("Fallbacktext aus RAGFlow Retrieval", result["source_markdown"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["diagnostics"]["provider"], "ragflow")
        self.assertEqual(
            result["diagnostics"]["endpoint"],
            "/api/v1/openai/{chat_id}/chat/completions",
        )
        self.assertEqual(result["diagnostics"]["fallback"], "retrieval")
        self.assertEqual(result["diagnostics"]["fallback_reason"], "chat_completion_failed")
        self.assertEqual(result["diagnostics"]["answer_path"], "")
        self.assertEqual(result["diagnostics"]["reference_path"], "retrieval.chunks")
        self.assertEqual(result["diagnostics"]["http_status"], 200)
        self.assertTrue(result["diagnostics"]["chat_id_present"])
        self.assertTrue(result["diagnostics"]["dataset_id_present"])
        self.assertIn("code", result["diagnostics"]["redacted_response_hint"])

    def test_openwebui_chat_proxy_falls_back_to_retrieval_when_chat_times_out(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add(
                File(
                    repo_id="repo-1",
                    path="/timeout.txt",
                    normalized_path="/timeout.txt",
                    ragflow_document_id="doc-timeout",
                    ragflow_document_name="timeout.txt",
                    ingestion_strategy="direct",
                    sync_status="synced",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.chat_exception = dashboard_server.httpx.ReadTimeout("timed out")
        _FakeRAGFlowClient.retrieve_calls = 0
        _FakeRAGFlowClient.retrieval_result = {
            "chunks": [
                {
                    "id": "chunk-timeout",
                    "document_id": "doc-timeout",
                    "content": "Fallback nach Chat-Timeout",
                }
            ]
        }
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=_settings(0), started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "messages": [{"role": "user", "content": "Frage"}],
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]
            _FakeRAGFlowClient.chat_exception = None
            _FakeRAGFlowClient.retrieval_result = {"chunks": []}

        self.assertEqual(_FakeRAGFlowClient.retrieve_calls, 1)
        self.assertEqual(result["answer"], "")
        self.assertTrue(result["retrieval_only"])
        self.assertIn("Fallback nach Chat-Timeout", result["source_markdown"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["diagnostics"]["error_class"], "ReadTimeout")
        self.assertEqual(result["diagnostics"]["redacted_response_hint"], "request timed out")

    def test_openwebui_chat_proxy_enriches_answer_with_multiple_retrieval_chunks(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add_all(
                [
                    File(
                        repo_id="repo-1",
                        path="/demo-a.pdf",
                        normalized_path="/demo-a.pdf",
                        ragflow_document_id="doc-1",
                        ragflow_document_name="demo-a.pdf",
                        ingestion_strategy="direct",
                        sync_status="synced",
                    ),
                    File(
                        repo_id="repo-1",
                        path="/demo-b.pdf",
                        normalized_path="/demo-b.pdf",
                        ragflow_document_id="doc-2",
                        ragflow_document_name="demo-b.pdf",
                        ingestion_strategy="direct",
                        sync_status="synced",
                    ),
                ]
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.raise_chat_error = False
        _FakeRAGFlowClient.retrieve_calls = 0
        _FakeRAGFlowClient.retrieval_result = {
            "chunks": [
                {"id": "chunk-a", "document_id": "doc-1", "content": "Erster Treffer"},
                {"id": "chunk-b", "document_id": "doc-2", "content": "Zweiter Treffer"},
            ]
        }
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=_settings(0), started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "messages": [{"role": "user", "content": "Frage"}],
                    "top_k": 8,
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]
            _FakeRAGFlowClient.retrieval_result = {"chunks": []}

        self.assertEqual(_FakeRAGFlowClient.retrieve_calls, 1)
        self.assertEqual(len(result["sources"]), 2)
        self.assertIn("echte Antwort", result["answer"])
        self.assertNotIn("## Nachweise", result["answer"])
        self.assertFalse(result["retrieval_only"])
        self.assertFalse(result["citations_emitted"])
        self.assertIn("## Nachweise", result["source_markdown"])
        self.assertIn("demo-a.pdf", result["source_markdown"])
        self.assertIn("demo-b.pdf", result["source_markdown"])
        self.assertIn("### S1 -", result["source_markdown"])
        self.assertIn("- **Dokument:**", result["source_markdown"])
        self.assertNotIn("| # | Dokument", result["source_markdown"])
        self.assertNotIn("<details", result["source_markdown"])
        self.assertNotIn("<summary", result["source_markdown"])
        self.assertNotIn("<br>", result["source_markdown"])

    def test_openwebui_chat_proxy_sanitizes_html_answer_fragments(self) -> None:
        store = _store(self)
        with store.session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo", status="active"))
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.answer_content = (
            "<table><tr><td>Alpha</td><td>&Uuml;ber</td></tr></table>"
        )
        _FakeRAGFlowClient.retrieval_result = {"chunks": []}
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=_settings(0), started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "messages": [{"role": "user", "content": "HTML-Frage"}],
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]
            _FakeRAGFlowClient.answer_content = "RAGFlow liefert eine echte Antwort."

        self.assertIn("Alpha | Über", result["answer"])
        self.assertNotIn("<table", result["answer"])
        self.assertNotIn("<td>", result["answer"])

    def test_openwebui_chat_proxy_denies_before_ragflow_when_acl_blocks_user(self) -> None:
        store = _store(self)
        now = utcnow()
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                )
            )
            session.add(
                SearchProfile(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    display_name="Demo",
                    kind="library",
                    enabled=True,
                    status="ready",
                    last_acl_sync_at=now,
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        settings = _settings(0)
        settings.openwebui_authz_enabled = True
        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.retrieve_calls = 0
        _FakeRAGFlowClient.last_model = None
        try:
            with self.assertRaises(dashboard_server.AuthzDeniedError):
                _handle_openwebui_chat(
                    DashboardContext(store=store, settings=settings, started_at=utcnow()),
                    {
                        "artifact_id": "pipe-1",
                        "dataset_id": "dataset-1",
                        "chat_id": "chat-1",
                        "messages": [{"role": "user", "content": "Frage"}],
                        "user": {"username": "alfred", "email": "alfred@example.local"},
                    },
                    "Bearer proxy-secret",
                )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertEqual(_FakeRAGFlowClient.retrieve_calls, 0)
        self.assertIsNone(_FakeRAGFlowClient.last_model)

    def test_openwebui_chat_proxy_allows_authorized_user_before_ragflow(self) -> None:
        store = _store(self)
        now = utcnow()
        with store.session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    status="active",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                )
            )
            session.add(
                SearchProfile(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    display_name="Demo",
                    kind="library",
                    enabled=True,
                    status="ready",
                    last_acl_sync_at=now,
                )
            )
            session.add(
                LibraryACLEffectiveUser(
                    repo_id="repo-1",
                    user_email="olaf@example.local",
                    permission="rw",
                    sources=["user_share"],
                    last_seen_at=now,
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_pipe_id="pipe-1",
                )
            )
            session.commit()

        settings = _settings(0)
        settings.openwebui_authz_enabled = True
        original_client = dashboard_server.RAGFlowClient
        dashboard_server.RAGFlowClient = _FakeRAGFlowClient  # type: ignore[assignment]
        _FakeRAGFlowClient.retrieve_calls = 0
        try:
            result = _handle_openwebui_chat(
                DashboardContext(store=store, settings=settings, started_at=utcnow()),
                {
                    "artifact_id": "pipe-1",
                    "dataset_id": "dataset-1",
                    "chat_id": "chat-1",
                    "messages": [{"role": "user", "content": "Frage"}],
                    "user": {"username": "olaf", "email": "OLAF@EXAMPLE.LOCAL"},
                },
                "Bearer proxy-secret",
            )
        finally:
            dashboard_server.RAGFlowClient = original_client  # type: ignore[assignment]

        self.assertIn("RAGFlow liefert eine echte Antwort", result["answer"])
        self.assertEqual(_FakeRAGFlowClient.retrieve_calls, 1)

    def test_openwebui_preview_html_renders_source_card_and_original_link(self) -> None:
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "report.pdf",
                "dataset_name": "Dataset",
                "document_id": "doc-1",
                "chunk_id": "chunk-123456789",
                "citation_label": "Quelle 1, Seite 7",
                "page": 7,
                "repo_id": "repo-1",
                "source_path": "/report.pdf",
                "original_url": "http://seafile.local/lib/repo-1/file/report.pdf#page=7",
                "snippet": "Originaler PDF-Auszug",
                "score": 0.8731,
                "position": [[7, 10, 20, 30, 40]],
                "locator_quality": "page",
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertIn("RAGFlow-Evidenz", html)
        self.assertIn("class=\"hero source-card\"", html)
        self.assertIn("class=\"button primary original-action\"", html)
        self.assertIn("data-original-link=\"true\"", html)
        self.assertIn('href="http://seafile.local/lib/repo-1/file/report.pdf#page=7"', html)
        self.assertIn("Original öffnen", html)
        self.assertIn("Theme wechseln", html)
        self.assertIn("Verwendeter Kontext", html)
        self.assertIn("Technische Details", html)
        self.assertIn("Auszug kopieren", html)
        self.assertIn("Originaler PDF-Auszug", html)
        self.assertIn("87%", html)
        self.assertIn("relativer RAGFlow-Score", html)
        self.assertIn("Koordinaten vorhanden", html)
        self.assertIn("Position roh", html)
        self.assertIn("Fundstellenqualität", html)
        self.assertIn("page", html)
        self.assertIn("#page=7", html)

    def test_openwebui_preview_html_explains_missing_original_link(self) -> None:
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "report.pdf",
                "dataset_name": "Dataset",
                "document_id": "doc-1",
                "chunk_id": "chunk-123456789",
                "citation_label": "Quelle 1",
                "source_path": "/report.pdf",
                "snippet": "Originaler PDF-Auszug",
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertIn("Original-Link nicht verfügbar", html)
        self.assertIn("Repo-ID oder Pfad", html)
        self.assertNotIn("class=\"button primary original-action\"", html)

    def test_openwebui_preview_html_rejects_connector_original_links(self) -> None:
        settings = _settings(0)

        for original_url in (
            "https://connector.example/api/openwebui/sources/preview?token=x",
            "https://connector.example/api/openwebui/proxy",
            "https://connector.example/api/openwebui/proxy/source/x",
        ):
            with self.subTest(original_url=original_url):
                token = sign_preview_payload(
                    {
                        "document_name": "report.pdf",
                        "dataset_name": "Dataset",
                        "document_id": "doc-1",
                        "citation_label": "Quelle 1",
                        "source_path": "/report.pdf",
                        "original_url": original_url,
                        "snippet": "Originaler PDF-Auszug",
                    },
                    "proxy-secret",
                )

                html = _preview_html(settings, token)

                self.assertNotIn("data-original-link=\"true\"", html)
                self.assertNotIn("class=\"button primary original-action\"", html)
                self.assertIn("Connector-/Preview-Link", html)

    def test_openwebui_preview_html_rejects_non_http_original_links(self) -> None:
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "report.pdf",
                "dataset_name": "Dataset",
                "document_id": "doc-1",
                "citation_label": "Quelle 1",
                "source_path": "/report.pdf",
                "original_url": "javascript:alert(1)",
                "snippet": "Originaler PDF-Auszug",
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertNotIn("data-original-link=\"true\"", html)
        self.assertNotIn("class=\"button primary original-action\"", html)
        self.assertIn("keinen nutzbaren http(s)-Original-Link", html)

    def test_openwebui_preview_html_sanitizes_source_snippet(self) -> None:
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "html_fragmente</pre><script>alert(1)</script>.md",
                "dataset_name": "Dataset",
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "citation_label": "Quelle 1",
                "snippet": (
                    "<script>alert(1)</script>"
                    "<table><tr><td>Alpha</td><td>&uuml;</td></tr></table>"
                ),
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertIn("Alpha | ü", html)
        self.assertNotIn("&lt;td&gt;", html)
        self.assertNotIn("</pre><script>", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("id=\"raw-payload\"", html)
        self.assertIn("&lt;/pre&gt;&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_openwebui_preview_html_renders_invalid_token_fallback(self) -> None:
        settings = _settings(0)

        html = _preview_html(settings, "not-a-valid-token")

        self.assertIn("RAGFlow-Evidenz", html)
        self.assertIn("Die Vorschau ist nicht verfügbar", html)
        self.assertIn("OPENWEBUI_PROXY_SHARED_SECRET", html)
        self.assertNotIn("data-original-link=\"true\"", html)

    def test_source_snippet_cleaner_ignores_script_style_without_regex_backtracking(self) -> None:
        hostile_markup = "<style" * 4000 + "<table><tr><td>Alpha</td><td>&uuml;</td></tr></table>"

        cleaned = _clean_source_snippet(hostile_markup)

        self.assertIn("Alpha | ü", cleaned)
        self.assertNotIn("<td>", cleaned)
        self.assertNotIn("style", cleaned.lower())


@dataclass
class _FakeWorkflowSyncSummary:
    libraries_synced: int = 1
    files_seen: int = 2
    files_uploaded: int = 2
    files_deleted: int = 0
    files_skipped: int = 0


@dataclass
class _FakeWorkflowOpenWebUISummary:
    datasets_seen: int = 1
    chats_created: int = 1
    tools_created: int = 1
    pipes_created: int = 1
    failed: int = 0
    dry_run: bool = False


class _FakeDocumentSeafileClient:
    downloads: list[tuple[str, str]] = []
    body: bytes = b"%PDF-1.7"

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def download_file(self, repo_id: str, path: str) -> bytes:
        self.__class__.downloads.append((repo_id, path))
        return self.__class__.body

    def close(self) -> None:
        pass


class _FakeWorkflowOrchestrator:
    skip_encrypted_libraries = True
    skip_virtual_repos = True

    def __init__(self, session_factory: object) -> None:
        self.session_factory = session_factory
        self.admin_client = self
        self.synced: list[tuple[str, str]] = []
        self.raw_libraries = [
            {
                "id": "repo-1",
                "name": "Demo",
                "owner": "admin@example.invalid",
                "head_commit_id": "head-new",
            },
            {
                "id": "repo-2",
                "name": "Secret",
                "encrypted": True,
                "head_commit_id": "head-secret",
            },
        ]

    def iter_libraries(self) -> list[dict[str, object]]:
        return list(self.raw_libraries)

    def discover_libraries(self) -> list[dict[str, object]]:
        with self.session_factory() as session:  # type: ignore[operator]
            for raw in self.raw_libraries:
                if raw.get("encrypted"):
                    continue
                repo_id = str(raw["id"])
                library = session.get(Library, repo_id) or Library(
                    repo_id=repo_id,
                    name=str(raw["name"]),
                    name_slug=str(raw["name"]).lower(),
                    status="active",
                )
                library.name = str(raw["name"])
                library.status = "active"
                library.head_commit_id = str(raw.get("head_commit_id") or "")
                session.merge(library)
            session.commit()
        return [raw for raw in self.raw_libraries if not raw.get("encrypted")]

    def sync_library_full(self, repo_id: str, *, scope: str = "/") -> _FakeWorkflowSyncSummary:
        self.synced.append((repo_id, scope))
        with self.session_factory() as session:  # type: ignore[operator]
            library = session.get(Library, repo_id)
            if library is None:
                library = Library(
                    repo_id=repo_id,
                    name="Demo",
                    name_slug="demo",
                    status="active",
                )
                session.add(library)
            library.ragflow_dataset_id = f"dataset-{repo_id}"
            library.ragflow_dataset_name = f"Dataset {repo_id}"
            library.status = "active"
            session.commit()
        return _FakeWorkflowSyncSummary()

    def requeue_cleanup_outbox(self, outbox_id: int) -> str | None:
        _ = outbox_id
        return "repo-1"


class _FakeWorkflowOpenWebUI:
    def __init__(self) -> None:
        self.repo_ids: list[set[str]] = []

    def sync_once(self, *, repo_ids: set[str] | None = None) -> _FakeWorkflowOpenWebUISummary:
        self.repo_ids.append(set(repo_ids or set()))
        return _FakeWorkflowOpenWebUISummary()


class _FakeWorkflowSignalQueue:
    def __init__(self) -> None:
        self.job_ids: list[int] = []

    def signal(self, job_id: int) -> None:
        self.job_ids.append(job_id)


class _FailingWorkflowJobStore(JobStore):
    def __init__(
        self,
        session_factory: object,
        *,
        operation: str,
        fail_on_call: int,
    ) -> None:
        super().__init__(session_factory)  # type: ignore[arg-type]
        self.operation = operation
        self.fail_on_call = fail_on_call
        self.enqueue_calls = 0
        self.subscribe_calls = 0

    def enqueue_with_result(self, spec: JobSpec) -> EnqueueResult:
        self.enqueue_calls += 1
        if self.operation == "enqueue" and self.enqueue_calls == self.fail_on_call:
            raise RuntimeError("injected enqueue failure")
        return super().enqueue_with_result(spec)

    def subscribe_workflow(
        self,
        workflow_run_id: str,
        job_id: int,
        *,
        is_root: bool = False,
        owns_job: bool = False,
    ) -> None:
        self.subscribe_calls += 1
        if self.operation == "subscribe" and self.subscribe_calls == self.fail_on_call:
            raise RuntimeError("injected subscription failure")
        super().subscribe_workflow(
            workflow_run_id,
            job_id,
            is_root=is_root,
            owns_job=owns_job,
        )


class _FailingWorkflowSignalQueue(_FakeWorkflowSignalQueue):
    def signal(self, job_id: int) -> None:
        super().signal(job_id)
        raise ConnectionError("redis unavailable")


class _FakeOpenWebUIAdminClient:
    functions: dict[str, dict[str, object]] = {}
    deleted_functions: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def get_function(self, function_id: str) -> dict[str, object] | None:
        return self.__class__.functions.get(function_id)

    def delete_function(self, function_id: str) -> bool:
        self.__class__.deleted_functions.append(function_id)
        self.__class__.functions.pop(function_id, None)
        return True

    def close(self) -> None:
        pass


class _FakeRAGFlowClient:
    last_model: str | None = None
    raise_chat_error = False
    chat_exception: Exception | None = None
    retrieve_calls = 0
    retrieval_result: dict[str, object] = {"chunks": []}
    answer_content = "RAGFlow liefert eine echte Antwort."
    deleted_chats: list[list[str]] = []
    deleted_datasets: list[list[str]] = []
    chats: dict[str, dict[str, object]] = {}
    init_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.__class__.init_calls.append((args, kwargs))

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.__class__.last_model = str(kwargs.get("model"))
        if self.__class__.chat_exception is not None:
            raise self.__class__.chat_exception
        if self.__class__.raise_chat_error:
            raise ApiError("API returned an error code", status_code=200, payload={"code": 102})
        return {
            "choices": [
                {
                    "message": {
                        "content": self.__class__.answer_content,
                        "reference": {"chunks": []},
                    }
                }
            ]
        }

    def retrieve_chunks(self, **kwargs: object) -> dict[str, object]:
        self.__class__.retrieve_calls += 1
        return self.__class__.retrieval_result

    def get_chat(self, chat_id: str) -> dict[str, object] | None:
        return self.__class__.chats.get(chat_id)

    def delete_chats(self, chat_ids: list[str]) -> bool:
        self.__class__.deleted_chats.append(list(chat_ids))
        return True

    def delete_datasets(self, dataset_ids: list[str]) -> bool:
        self.__class__.deleted_datasets.append(list(dataset_ids))
        return True

    def close(self) -> None:
        pass


def _get_json(
    port: int,
    path: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, object]:
    request = Request(f"http://127.0.0.1:{port}{path}")
    if username is not None and password is not None:
        raw_credentials = f"{username}:{password}".encode()
        token = base64.b64encode(raw_credentials).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(
    port: int,
    path: str,
    payload: dict[str, object],
    *,
    username: str | None = None,
    password: str | None = None,
    content_type: str | None = "application/json",
    admin_action: str | None = "1",
    fetch_site: str | None = None,
) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    if content_type is not None:
        request.add_header("Content-Type", content_type)
    request.add_header("Accept", "application/json")
    if admin_action is not None:
        request.add_header("X-Connector-Admin-Action", admin_action)
    if fetch_site is not None:
        request.add_header("Sec-Fetch-Site", fetch_site)
    if username is not None and password is not None:
        raw_credentials = f"{username}:{password}".encode()
        token = base64.b64encode(raw_credentials).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json_bearer(
    port: int,
    path: str,
    payload: dict[str, object],
    token: str,
) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_raw(
    port: int,
    path: str,
    body: bytes,
    *,
    username: str,
    password: str,
    content_type: str = "application/json",
    admin_action: str = "1",
) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method="POST",
    )
    request.add_header("Content-Type", content_type)
    request.add_header("X-Connector-Admin-Action", admin_action)
    raw_credentials = f"{username}:{password}".encode()
    token = base64.b64encode(raw_credentials).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_bytes(port: int, path: str) -> tuple[bytes, str, str]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return (
            response.read(),
            response.headers.get("Content-Type", ""),
            response.headers.get("Content-Disposition", ""),
        )


def _get_text(port: int, path: str) -> str:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.read().decode("utf-8")


def _get_text_with_headers(port: int, path: str) -> tuple[str, dict[str, str]]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.read().decode("utf-8"), dict(response.headers.items())


if __name__ == "__main__":
    unittest.main()
