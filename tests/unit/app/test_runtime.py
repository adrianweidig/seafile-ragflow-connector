from __future__ import annotations

import unittest
from types import TracebackType
from unittest.mock import patch

from seafile_ragflow_connector.app import runtime
from seafile_ragflow_connector.persistence import db


class _FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.statements: list[str] = []

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        _ = (exc_type, exc, traceback)
        return False

    def execute(self, statement: object, parameters: object | None = None) -> None:
        _ = parameters
        self.statements.append(str(statement))
        if self.fail:
            raise RuntimeError("database unavailable")


class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeEngine:
    def __init__(
        self,
        connection: _FakeConnection | None = None,
        *,
        dialect_name: str = "sqlite",
    ) -> None:
        self.connection = connection or _FakeConnection()
        self.dialect = _FakeDialect(dialect_name)
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def begin(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


class _FakeRedisClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ping_calls = 0
        self.closed = False

    def ping(self) -> None:
        self.ping_calls += 1
        if self.fail:
            raise RuntimeError("redis unavailable")

    def close(self) -> None:
        self.closed = True


class _Closeable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RuntimeDatabaseChecksTests(unittest.TestCase):
    def test_check_database_disposes_probe_engine(self) -> None:
        engine = _FakeEngine()

        with patch.object(runtime, "get_engine", return_value=engine):
            runtime.check_database("sqlite://")

        self.assertEqual(engine.connection.statements, ["select 1"])
        self.assertTrue(engine.disposed)

    def test_check_database_disposes_probe_engine_after_error(self) -> None:
        engine = _FakeEngine(_FakeConnection(fail=True))

        with (
            patch.object(runtime, "get_engine", return_value=engine),
            self.assertRaises(RuntimeError),
        ):
            runtime.check_database("sqlite://")

        self.assertTrue(engine.disposed)

    def test_init_database_disposes_setup_engine(self) -> None:
        engine = _FakeEngine()
        upgrade_calls: list[tuple[object, str]] = []

        def upgrade(config: object, revision: str) -> None:
            upgrade_calls.append((config, revision))

        with (
            patch.object(db, "get_engine", return_value=engine),
            patch.object(db.command, "upgrade", side_effect=upgrade),
            patch.object(db, "_stamp_legacy_schema_if_needed"),
        ):
            db.init_database("sqlite://")

        self.assertEqual(len(upgrade_calls), 1)
        self.assertEqual(upgrade_calls[0][1], "head")
        self.assertTrue(engine.disposed)

    def test_init_database_serializes_postgres_alembic_upgrade(self) -> None:
        engine = _FakeEngine(dialect_name="postgresql")
        upgrade_calls: list[tuple[object, str]] = []

        def upgrade(config: object, revision: str) -> None:
            upgrade_calls.append((config, revision))

        with (
            patch.object(db, "get_engine", return_value=engine),
            patch.object(db.command, "upgrade", side_effect=upgrade),
            patch.object(db, "_stamp_legacy_schema_if_needed"),
        ):
            db.init_database("postgresql://")

        self.assertEqual(len(upgrade_calls), 1)
        self.assertEqual(upgrade_calls[0][1], "head")
        self.assertIn("pg_advisory_lock", engine.connection.statements[0])
        self.assertIn("pg_advisory_unlock", engine.connection.statements[-1])
        self.assertTrue(engine.disposed)


class RuntimeRedisChecksTests(unittest.TestCase):
    def test_check_redis_closes_probe_client(self) -> None:
        client = _FakeRedisClient()

        with patch.object(runtime.Redis, "from_url", return_value=client):
            runtime.check_redis("redis://127.0.0.1:6379/0")

        self.assertEqual(client.ping_calls, 1)
        self.assertTrue(client.closed)

    def test_check_redis_closes_probe_client_after_error(self) -> None:
        client = _FakeRedisClient(fail=True)

        with (
            patch.object(runtime.Redis, "from_url", return_value=client),
            self.assertRaises(RuntimeError),
        ):
            runtime.check_redis("redis://127.0.0.1:6379/0")

        self.assertTrue(client.closed)


class RuntimeCloseTests(unittest.TestCase):
    def test_close_closes_signal_queue(self) -> None:
        admin_client = _Closeable()
        sync_client = _Closeable()
        ragflow_client = _Closeable()
        signal_queue = _Closeable()

        app_runtime = runtime.Runtime(
            settings=object(),  # type: ignore[arg-type]
            admin_client=admin_client,  # type: ignore[arg-type]
            sync_client=sync_client,  # type: ignore[arg-type]
            ragflow_client=ragflow_client,  # type: ignore[arg-type]
            orchestrator=object(),  # type: ignore[arg-type]
            job_store=object(),  # type: ignore[arg-type]
            signal_queue=signal_queue,  # type: ignore[arg-type]
        )

        app_runtime.close()

        self.assertTrue(admin_client.closed)
        self.assertTrue(sync_client.closed)
        self.assertTrue(ragflow_client.closed)
        self.assertTrue(signal_queue.closed)


if __name__ == "__main__":
    unittest.main()
