from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from seafile_ragflow_connector.app.cli import (
    _discover_job_specs,
    _format_payload,
    _sync_openwebui_controller_guarded,
    _sync_openwebui_if_enabled,
)
from seafile_ragflow_connector.jobs.types import JobSpec, JobType


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


if __name__ == "__main__":
    unittest.main()
