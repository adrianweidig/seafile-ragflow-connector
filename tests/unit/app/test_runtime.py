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

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        if self.fail:
            raise RuntimeError("database unavailable")


class _FakeEngine:
    def __init__(self, connection: _FakeConnection | None = None) -> None:
        self.connection = connection or _FakeConnection()
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


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
        create_all_calls: list[object] = []

        def create_all(target_engine: object) -> None:
            create_all_calls.append(target_engine)

        with (
            patch.object(db, "get_engine", return_value=engine),
            patch.object(db.Base.metadata, "create_all", side_effect=create_all),
        ):
            db.init_database("sqlite://")

        self.assertEqual(create_all_calls, [engine])
        self.assertTrue(engine.disposed)


if __name__ == "__main__":
    unittest.main()
