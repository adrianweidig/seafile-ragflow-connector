from __future__ import annotations

import json
import unittest
from urllib.request import urlopen

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.config.settings import Settings
    import seafile_ragflow_connector.dashboard.server as dashboard_server
    from seafile_ragflow_connector.dashboard.server import (
        DashboardContext,
        _load_mapping,
        _handle_openwebui_chat,
        start_dashboard_server,
    )
    from seafile_ragflow_connector.dashboard.store import (
        DashboardEventStore,
        DashboardLimits,
        utcnow,
    )
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "sqlalchemy"}:
        raise
    create_engine = None  # type: ignore[assignment]


def _settings(port: int) -> Settings:
    settings = Settings(
        seafile_base_url="http://127.0.0.1:9",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://127.0.0.1:9",
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
        handle = start_dashboard_server(
            DashboardContext(store=store, settings=_settings(0), started_at=utcnow())
        )
        port = handle.server.server_address[1]
        try:
            health = _get_json(port, "/api/health")
            status = _get_json(port, "/api/status")
            logs = _get_json(port, "/api/logs?limit=1&sync_id=sync-a")
        finally:
            handle.stop()

        self.assertEqual(health["status"], "degraded")
        self.assertIn("checks", health)
        checks = {str(item["name"]): item for item in health["checks"]}
        self.assertEqual(checks["database"]["status"], "ok")
        self.assertEqual(checks["redis"]["status"], "error")
        self.assertEqual(checks["seafile"]["status"], "error")
        self.assertEqual(checks["ragflow"]["status"], "error")
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

    def test_openwebui_chat_proxy_uses_ragflow_model_placeholder(self) -> None:
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
        self.assertEqual(_FakeRAGFlowClient.last_model, "model")


class _FakeRAGFlowClient:
    last_model: str | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.__class__.last_model = str(kwargs.get("model"))
        return {
            "choices": [
                {
                    "message": {
                        "content": "answer",
                        "reference": {"chunks": []},
                    }
                }
            ]
        }

    def retrieve_chunks(self, **kwargs: object) -> dict[str, object]:
        return {"chunks": []}

    def close(self) -> None:
        pass


def _get_json(port: int, path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
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
