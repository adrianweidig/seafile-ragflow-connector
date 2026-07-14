from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import typer
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.app.cli import (
    _active_dataset_bindings,
    _cleanup_outbox_payload,
    _cleanup_status_filter,
    _discover_job_specs,
    _emit_job_result,
    _exit_for_invalid_configuration,
    _format_payload,
    _job_payload,
    _job_status_filter,
    _sync_openwebui_controller_guarded,
    _sync_openwebui_if_enabled,
    _wait_for_parse,
)
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion


class _RequiredConfiguration(BaseModel):
    required_value: str


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

    def test_emit_job_result_fails_after_rendering_dead_job(self) -> None:
        payload = {"job": {"status": JobStatus.DEAD.value}}

        with patch("typer.echo") as echo, self.assertRaises(typer.Exit) as raised:
            _emit_job_result(payload, json_output=True)

        self.assertEqual(raised.exception.exit_code, 1)
        echo.assert_called_once()

    def test_emit_job_result_fails_after_rendering_timeout(self) -> None:
        payload = {"timed_out": True, "job": {"status": JobStatus.RUNNING.value}}

        with patch("typer.echo"), self.assertRaises(typer.Exit) as raised:
            _emit_job_result(payload)

        self.assertEqual(raised.exception.exit_code, 1)

    def test_invalid_configuration_is_concise_and_exits_with_usage_code(self) -> None:
        try:
            _RequiredConfiguration()  # type: ignore[call-arg]
        except ValidationError as exc:
            validation_error = exc
        else:  # pragma: no cover - Pydantic contract guard
            self.fail("validation error expected")

        with patch("typer.echo") as echo, self.assertRaises(typer.Exit) as raised:
            _exit_for_invalid_configuration(validation_error)

        self.assertEqual(raised.exception.exit_code, 2)
        message = str(echo.call_args.args[0])
        self.assertIn("required_value", message)
        self.assertNotIn("https://errors.pydantic.dev", message)

    def test_job_status_filter_accepts_comma_separated_unique_values(self) -> None:
        self.assertEqual(
            _job_status_filter("queued, dead,queued"),
            (JobStatus.QUEUED, JobStatus.DEAD),
        )

    def test_cleanup_status_filter_accepts_superseded_and_deduplicates(self) -> None:
        self.assertEqual(
            _cleanup_status_filter("dead, superseded,dead"),
            ("dead", "superseded"),
        )

    def test_cleanup_outbox_payload_exposes_retry_context(self) -> None:
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id=8,
            repo_id="repo-1",
            run_id="run-1",
            target_type="ragflow_document",
            target_id="doc-1",
            dataset_id="dataset-1",
            action="delete",
            status="dead",
            attempts=5,
            run_after=now,
            error_message="HTTP 503",
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

        payload = _cleanup_outbox_payload(row)

        self.assertEqual(payload["id"], 8)
        self.assertEqual(payload["status"], "dead")
        self.assertEqual(payload["run_after"], now.isoformat())

    def test_job_payload_redacts_nested_secrets(self) -> None:
        now = datetime.now(UTC)
        job = SimpleNamespace(
            id=7,
            job_type="SYNC_LIBRARY_DELTA",
            repo_id="repo-1",
            file_path="/wissen.md",
            status="queued",
            priority=100,
            attempts=0,
            max_attempts=5,
            run_id=None,
            fence_token=None,
            cancel_requested_at=None,
            run_after=now,
            locked_by=None,
            locked_at=None,
            error_message=None,
            payload={"scope": "/", "api_key": "nicht-ausgeben"},
            created_at=now,
            updated_at=now,
        )

        payload = _job_payload(job)

        self.assertEqual(payload["payload"]["api_key"], "***")
        self.assertEqual(payload["run_after"], now.isoformat())

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
            running_file = File(
                repo_id="repo-running",
                path="/running.pdf",
                normalized_path="/running.pdf",
            )
            session.add(running_file)
            session.flush()
            session.add(
                FileDocumentVersion(
                    file_id=running_file.id,
                    repo_id="repo-running",
                    normalized_path="/running.pdf",
                    dataset_id="dataset-running",
                    document_id="doc-running",
                    document_name="running.pdf",
                    state="parsing",
                    parse_status="RUNNING",
                )
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
