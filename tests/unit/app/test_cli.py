from __future__ import annotations

import unittest
from types import SimpleNamespace

from seafile_ragflow_connector.app.cli import (
    _discover_job_specs,
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


def _runtime(mode: str, service: _FakeOpenWebUIService | None = None):
    return SimpleNamespace(
        settings=SimpleNamespace(openwebui_effective_sync_mode=mode),
        orchestrator=_FakeOrchestrator(),
        openwebui_sync_service=service,
    )


class CliSyncHelpersTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
