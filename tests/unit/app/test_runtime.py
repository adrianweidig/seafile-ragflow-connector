from __future__ import annotations

import unittest
from types import TracebackType
from unittest.mock import MagicMock, patch

from seafile_ragflow_connector.app import runtime
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.persistence import db


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "seafile_base_url": "https://files.example.local",
        "seafile_internal_url": "http://seafile.internal:8082",
        "seafile_admin_token": "admin-token",
        "seafile_sync_user_token": "sync-token",
        "ragflow_base_url": "https://ragflow.example.local",
        "ragflow_internal_url": "http://ragflow.internal:9380",
        "ragflow_api_key": "ragflow-token",
        "database_url": "sqlite://",
        "redis_url": "redis://127.0.0.1:1/0",
        "openwebui_integration_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


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
        self.close_calls = 0

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


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

    def test_close_closes_distinct_interactive_client_and_alias_only_once(self) -> None:
        for distinct_interactive in (False, True):
            with self.subTest(distinct_interactive=distinct_interactive):
                primary = _Closeable()
                interactive = _Closeable() if distinct_interactive else primary
                app_runtime = runtime.Runtime(
                    settings=object(),  # type: ignore[arg-type]
                    admin_client=_Closeable(),  # type: ignore[arg-type]
                    sync_client=_Closeable(),  # type: ignore[arg-type]
                    ragflow_client=primary,  # type: ignore[arg-type]
                    orchestrator=object(),  # type: ignore[arg-type]
                    job_store=object(),  # type: ignore[arg-type]
                    signal_queue=_Closeable(),  # type: ignore[arg-type]
                    interactive_ragflow_client=interactive,  # type: ignore[arg-type]
                )

                app_runtime.close()

                self.assertEqual(primary.close_calls, 1)
                self.assertEqual(interactive.close_calls, 1)


class RuntimeServiceRoutingTests(unittest.TestCase):
    def test_build_runtime_routes_interactive_artifacts_to_distinct_client(self) -> None:
        settings = _settings(
            ragflow_generated_dataset_permission="team",
            ragflow_interactive_api_key="interactive-token",
            ragflow_interactive_owner_id="owner-1",
            ragflow_interactive_chat_model_id="model@provider",
        )
        session_factory = MagicMock()
        primary_client = MagicMock()
        interactive_client = MagicMock()

        with (
            patch.object(runtime, "resolve_service_transports"),
            patch.object(runtime, "_warn_insecure_tls"),
            patch.object(runtime, "_retry"),
            patch.object(runtime, "get_session_factory", return_value=session_factory),
            patch.object(runtime, "AdminControlStore"),
            patch.object(runtime, "build_dashboard_store", return_value=None),
            patch.object(runtime, "SeafileAdminClient"),
            patch.object(runtime, "SeafileSyncClient"),
            patch.object(
                runtime,
                "RAGFlowClient",
                side_effect=[primary_client, interactive_client],
            ) as ragflow_client_class,
            patch.object(runtime, "SyncOrchestrator") as orchestrator_class,
            patch.object(runtime, "JobStore"),
            patch.object(runtime, "JobSignalQueue"),
            patch.object(runtime, "OpenWebUISyncService") as sync_service_class,
        ):
            built = runtime.build_runtime(settings, initialize_database=False)

        self.assertEqual(ragflow_client_class.call_count, 2)
        self.assertEqual(ragflow_client_class.call_args_list[0].args[1], "ragflow-token")
        self.assertEqual(
            ragflow_client_class.call_args_list[1].args[1],
            "interactive-token",
        )
        self.assertEqual(
            ragflow_client_class.call_args_list[1].kwargs["artifact_owner_id"],
            "owner-1",
        )
        self.assertIs(
            orchestrator_class.call_args.kwargs["ragflow_client"],
            primary_client,
        )
        self.assertIs(
            sync_service_class.call_args.kwargs["ragflow_client"],
            primary_client,
        )
        self.assertIs(
            sync_service_class.call_args.kwargs["interactive_ragflow_client"],
            interactive_client,
        )
        self.assertIs(built.ragflow_client, primary_client)
        self.assertIs(built.interactive_ragflow_client, interactive_client)

    def test_build_runtime_uses_internal_urls_for_service_clients(self) -> None:
        settings = _settings(
            ragflow_generated_dataset_permission="team",
            seafile_sync_user_auto_share_enabled=True,
            seafile_sync_user_email="sync@auth.local",
        )
        session_factory = MagicMock()

        with (
            patch.object(runtime, "resolve_service_transports"),
            patch.object(runtime, "_warn_insecure_tls"),
            patch.object(runtime, "_retry"),
            patch.object(runtime, "get_session_factory", return_value=session_factory),
            patch.object(runtime, "AdminControlStore") as control_store_class,
            patch.object(runtime, "build_dashboard_store", return_value=None),
            patch.object(runtime, "SeafileAdminClient") as admin_client_class,
            patch.object(runtime, "SeafileSyncClient") as sync_client_class,
            patch.object(runtime, "RAGFlowClient") as ragflow_client_class,
            patch.object(runtime, "SyncOrchestrator") as orchestrator_class,
            patch.object(runtime, "JobStore") as job_store_class,
            patch.object(runtime, "JobSignalQueue"),
            patch.object(runtime, "OpenWebUISyncService"),
        ):
            runtime.build_runtime(settings, initialize_database=False)

        self.assertEqual(admin_client_class.call_args.args[0], "http://seafile.internal:8082")
        self.assertEqual(sync_client_class.call_args.args[0], "http://seafile.internal:8082")
        self.assertEqual(ragflow_client_class.call_args.args[0], "http://ragflow.internal:9380")
        self.assertEqual(
            orchestrator_class.call_args.kwargs["generated_dataset_permission"],
            "team",
        )
        self.assertTrue(
            orchestrator_class.call_args.kwargs["sync_user_auto_share_enabled"]
        )
        self.assertEqual(
            orchestrator_class.call_args.kwargs["sync_user_email"],
            "sync@auth.local",
        )
        control_store_class.return_value.initialize_workflow.assert_not_called()
        self.assertIn(
            "https://files.example.local",
            sync_client_class.call_args.kwargs["allowed_download_origins"],
        )
        self.assertEqual(
            job_store_class.call_args.kwargs["default_max_attempts"],
            settings.job_max_attempts,
        )

    def test_warn_insecure_tls_uses_internal_service_routes(self) -> None:
        settings = _settings(
            seafile_verify_ssl=False,
            ragflow_verify_ssl=False,
        )
        logger = MagicMock()

        with patch.object(runtime.structlog, "get_logger", return_value=logger):
            runtime._warn_insecure_tls(settings)

        targets_by_route = {
            call.kwargs["route"]: call.kwargs["target"] for call in logger.warning.call_args_list
        }
        self.assertEqual(
            targets_by_route["Connector -> Seafile"],
            "http://seafile.internal:8082",
        )
        self.assertEqual(
            targets_by_route["Connector -> RAGFlow"],
            "http://ragflow.internal:9380",
        )


if __name__ == "__main__":
    unittest.main()
