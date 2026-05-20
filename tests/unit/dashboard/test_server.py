from __future__ import annotations

import json
import unittest
from urllib.request import urlopen

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.config.settings import Settings
    from seafile_ragflow_connector.dashboard.server import DashboardContext, start_dashboard_server
    from seafile_ragflow_connector.dashboard.store import (
        DashboardEventStore,
        DashboardLimits,
        utcnow,
    )
    from seafile_ragflow_connector.persistence.db import Base
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "sqlalchemy"}:
        raise
    create_engine = None  # type: ignore[assignment]


def _settings(port: int) -> Settings:
    settings = Settings(
        seafile_base_url="http://seafile.local",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key="ragflow-token",
        database_url="sqlite://",
        redis_url="redis://redis.local:6379/0",
        connector_dashboard_enabled=True,
        connector_dashboard_host="127.0.0.1",
        connector_dashboard_port=1,
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

        self.assertEqual(health["status"], "ok")
        self.assertIn("state", status)
        self.assertEqual(logs["limit"], 1)
        self.assertEqual(logs["items"][0]["message"], "server-log")


def _get_json(port: int, path: str) -> dict[str, object]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
