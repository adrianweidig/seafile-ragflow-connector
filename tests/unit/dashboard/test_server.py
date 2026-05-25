from __future__ import annotations

import base64
import json
import unittest
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
    from seafile_ragflow_connector.openwebui.sources import sign_preview_payload
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.file import File
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping
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
    )
    settings.connector_dashboard_port = port
    return settings


def _store() -> DashboardEventStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return DashboardEventStore(session_factory, DashboardLimits(page_size=10))


@unittest.skipIf(
    create_engine is None,
    "pydantic or sqlalchemy is not installed in this Python environment",
)
class DashboardServerTests(unittest.TestCase):
    def test_health_status_and_log_endpoints_return_bounded_json(self) -> None:
        store = _store()
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
        store = _store()
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
        store = _store()
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

    def test_openwebui_mapping_requires_assigned_tool_and_pipe(self) -> None:
        store = _store()
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
        store = _store()
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
        store = _store()
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

        self.assertEqual(result["answer"], "answer")
        self.assertEqual(_FakeRAGFlowClient.last_model, "ragflow/openwebui-model-id")

    def test_openwebui_chat_proxy_falls_back_to_retrieval_when_chat_fails(self) -> None:
        store = _store()
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
        self.assertIn("Gefundene Quellen", result["answer"])
        self.assertIn("Fallbacktext aus RAGFlow Retrieval", result["answer"])
        self.assertEqual(len(result["sources"]), 1)

    def test_openwebui_chat_proxy_enriches_answer_with_multiple_retrieval_chunks(self) -> None:
        store = _store()
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
        self.assertIn("answer", result["answer"])
        self.assertIn("## Gefundene Quellen", result["answer"])
        self.assertIn("demo-a.pdf", result["answer"])
        self.assertIn("demo-b.pdf", result["answer"])
        self.assertIn("### 1. demo-a.pdf", result["answer"])
        self.assertNotIn("| # | Dokument", result["answer"])
        self.assertNotIn("<details", result["answer"])
        self.assertNotIn("<summary", result["answer"])
        self.assertNotIn("<br>", result["answer"])

    def test_openwebui_chat_proxy_sanitizes_html_answer_fragments(self) -> None:
        store = _store()
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
            _FakeRAGFlowClient.answer_content = "answer"

        self.assertIn("Alpha | Über", result["answer"])
        self.assertNotIn("<table", result["answer"])
        self.assertNotIn("<td>", result["answer"])

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
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertIn("RAGFlow Quellenvorschau", html)
        self.assertIn("Original öffnen", html)
        self.assertIn("Theme wechseln", html)
        self.assertIn("data-tab=\"debug\"", html)
        self.assertIn("Auszug kopieren", html)
        self.assertIn("Originaler PDF-Auszug", html)
        self.assertIn("#page=7", html)

    def test_openwebui_preview_html_sanitizes_source_snippet(self) -> None:
        settings = _settings(0)
        token = sign_preview_payload(
            {
                "document_name": "html_fragmente.md",
                "dataset_name": "Dataset",
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "citation_label": "Quelle 1",
                "snippet": "<table><tr><td>Alpha</td><td>&uuml;</td></tr></table>",
            },
            "proxy-secret",
        )

        html = _preview_html(settings, token)

        self.assertIn("Alpha | ü", html)
        self.assertNotIn("&lt;td&gt;", html)

    def test_source_snippet_cleaner_ignores_script_style_without_regex_backtracking(self) -> None:
        hostile_markup = "<style" * 4000 + "<table><tr><td>Alpha</td><td>&uuml;</td></tr></table>"

        cleaned = _clean_source_snippet(hostile_markup)

        self.assertIn("Alpha | ü", cleaned)
        self.assertNotIn("<td>", cleaned)
        self.assertNotIn("style", cleaned.lower())


class _FakeRAGFlowClient:
    last_model: str | None = None
    raise_chat_error = False
    retrieve_calls = 0
    retrieval_result: dict[str, object] = {"chunks": []}
    answer_content = "answer"

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.__class__.last_model = str(kwargs.get("model"))
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


def _get_bytes(port: int, path: str) -> tuple[bytes, str, str]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return (
            response.read(),
            response.headers.get("Content-Type", ""),
            response.headers.get("Content-Disposition", ""),
        )


if __name__ == "__main__":
    unittest.main()
