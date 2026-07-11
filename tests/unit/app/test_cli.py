from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.app.cli import (
    _active_dataset_bindings,
    _discover_job_specs,
    _format_payload,
    _sync_openwebui_controller_guarded,
    _sync_openwebui_if_enabled,
    _wait_for_parse,
)
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.library import Library


class _FakeOrchestrator:
    def discover_job_specs(self) -> list[JobSpec]:
        return [JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo-1")]


class _FakeOpenWebUIService:
    def __init__(self) -> None:
        self.calls = 0

    def sync_once(self):
        self.calls += 1
        return SimpleNamespace(datasets_seen=1, tools_created=1, pipes_created=1)


class _FailingOpenWebUIService:
    def __init__(self) -> None:
        self.calls = 0

    def sync_once(self):
        self.calls += 1
        raise ConnectionError("ragflow unavailable")


class _FakeLog:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.warnings.append((event, kwargs))


class _ParseWaitOrchestrator:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.checked: list[tuple[str, str]] = []
        self.discover_called = False
        self.ensure_called = False

    def discover_libraries(self):
        self.discover_called = True
        return []

    def ensure_dataset_for_repo(self, repo_id: str) -> str:
        self.ensure_called = True
        return f"dataset-{repo_id}"

    def check_parse_status(self, repo_id: str, dataset_id: str) -> int:
        self.checked.append((repo_id, dataset_id))
        return 1


class _ParseWaitRAGFlow:
    def __init__(self, runs: dict[str, str] | None = None) -> None:
        self.runs = runs or {}

    def iter_documents(self, dataset_id: str):
        return iter(
            [
                {
                    "id": f"doc-{dataset_id}",
                    "run": self.runs.get(dataset_id, "DONE"),
                }
            ]
        )


def _runtime(mode: str, service: _FakeOpenWebUIService | None = None):
    return SimpleNamespace(
        settings=SimpleNamespace(openwebui_effective_sync_mode=mode),
        orchestrator=_FakeOrchestrator(),
        openwebui_sync_service=service,
    )


class CliSyncHelpersTests(unittest.TestCase):
    def test_format_payload_can_emit_stable_json(self) -> None:
        output = _format_payload({"message": "für", "count": 2}, json_output=True)

        self.assertEqual(json.loads(output), {"message": "für", "count": 2})
        self.assertEqual(output, '{"count": 2, "message": "für"}')

    def test_format_payload_keeps_legacy_dict_output_by_default(self) -> None:
        self.assertEqual(_format_payload({"status": "ok"}), "{'status': 'ok'}")

    def test_discovery_adds_openwebui_sync_job_when_enabled(self) -> None:
        specs = _discover_job_specs(_runtime("sync"))  # type: ignore[arg-type]

        self.assertEqual(
            [spec.job_type for spec in specs],
            [JobType.SYNC_LIBRARY_FULL, JobType.SYNC_OPENWEBUI],
        )

    def test_discovery_does_not_add_openwebui_sync_job_when_disabled(self) -> None:
        specs = _discover_job_specs(_runtime("disabled"))  # type: ignore[arg-type]

        self.assertEqual([spec.job_type for spec in specs], [JobType.SYNC_LIBRARY_FULL])

    def test_sync_once_runs_openwebui_summary_when_enabled(self) -> None:
        service = _FakeOpenWebUIService()
        summary = _sync_openwebui_if_enabled(_runtime("sync", service))  # type: ignore[arg-type]

        self.assertEqual(summary, {"datasets_seen": 1, "tools_created": 1, "pipes_created": 1})
        self.assertEqual(service.calls, 1)

    def test_sync_once_skips_openwebui_when_disabled(self) -> None:
        service = _FakeOpenWebUIService()
        summary = _sync_openwebui_if_enabled(
            _runtime("disabled", service)  # type: ignore[arg-type]
        )

        self.assertIsNone(summary)
        self.assertEqual(service.calls, 0)

    def test_controller_guard_runs_openwebui_sync_when_enabled(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("sync", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 1)
        self.assertEqual(log.warnings, [])

    def test_controller_guard_logs_openwebui_sync_failure(self) -> None:
        service = _FailingOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("sync", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 1)
        self.assertEqual(log.warnings[0][0], "controller.openwebui_sync.failed")
        self.assertEqual(log.warnings[0][1]["error_class"], "ConnectionError")

    def test_controller_guard_skips_openwebui_when_disabled(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("disabled", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 0)
        self.assertEqual(log.warnings, [])

    def test_wait_for_parse_only_checks_active_dataset_bindings(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-active",
                        name="Active",
                        name_slug="active",
                        status="active",
                        ragflow_dataset_id="dataset-active",
                    ),
                    Library(
                        repo_id="repo-error",
                        name="Error",
                        name_slug="error",
                        status="error",
                        ragflow_dataset_id="dataset-error",
                        last_error="HTTP 403",
                    ),
                ]
            )
            session.commit()
        orchestrator = _ParseWaitOrchestrator(session_factory)
        runtime = SimpleNamespace(orchestrator=orchestrator, ragflow_client=_ParseWaitRAGFlow())

        self.assertEqual(
            _active_dataset_bindings(runtime),  # type: ignore[arg-type]
            [("repo-active", "dataset-active")],
        )

        _wait_for_parse(runtime, timeout_seconds=1)  # type: ignore[arg-type]

        self.assertEqual(orchestrator.checked, [("repo-active", "dataset-active")])
        self.assertFalse(orchestrator.discover_called)
        self.assertFalse(orchestrator.ensure_called)

    def test_wait_for_parse_keeps_running_state_across_multiple_datasets(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-running",
                        name="Running",
                        name_slug="running",
                        status="active",
                        ragflow_dataset_id="dataset-running",
                    ),
                    Library(
                        repo_id="repo-done",
                        name="Done",
                        name_slug="done",
                        status="active",
                        ragflow_dataset_id="dataset-done",
                    ),
                ]
            )
            session.commit()
        runtime = SimpleNamespace(
            orchestrator=_ParseWaitOrchestrator(session_factory),
            ragflow_client=_ParseWaitRAGFlow(
                {"dataset-running": "RUNNING", "dataset-done": "DONE"}
            ),
        )

        with patch(
            "seafile_ragflow_connector.app.cli.time.sleep",
            side_effect=RuntimeError("poll requested"),
        ), self.assertRaisesRegex(RuntimeError, "poll requested"):
            _wait_for_parse(runtime, timeout_seconds=30)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
