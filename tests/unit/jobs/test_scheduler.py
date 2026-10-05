from __future__ import annotations

import unittest
from unittest.mock import patch

from seafile_ragflow_connector.jobs.scheduler import PeriodicTask, SimpleScheduler


class _StopScheduler(RuntimeError):
    pass


class _FakeLog:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.warnings.append((event, kwargs))


class SimpleSchedulerTests(unittest.TestCase):
    def test_disabled_cycle_does_not_advance_task_last_run(self) -> None:
        runs: list[str] = []
        states = iter([False, True])
        scheduler = SimpleScheduler(
            [
                PeriodicTask(
                    "sync",
                    interval_seconds=10,
                    run=lambda: runs.append("sync"),
                    last_run_monotonic=95.0,
                )
            ],
            sleep_seconds=1,
            enabled=lambda: next(states),
        )

        with (
            patch(
                "seafile_ragflow_connector.jobs.scheduler.time.monotonic",
                side_effect=[100.0, 106.0],
            ),
            patch(
                "seafile_ragflow_connector.jobs.scheduler.time.sleep",
                side_effect=[None, _StopScheduler()],
            ),
            self.assertRaises(_StopScheduler),
        ):
            scheduler.run_forever()

        self.assertEqual(runs, ["sync"])

    def test_enabled_callback_failure_is_fail_closed_without_error_text(self) -> None:
        runs: list[str] = []
        checks = 0

        def enabled() -> bool:
            nonlocal checks
            checks += 1
            if checks == 1:
                raise RuntimeError("sensitive database detail")
            return True

        scheduler = SimpleScheduler(
            [
                PeriodicTask(
                    "sync",
                    interval_seconds=10,
                    run=lambda: runs.append("sync"),
                    last_run_monotonic=95.0,
                )
            ],
            sleep_seconds=1,
            enabled=enabled,
        )
        log = _FakeLog()
        scheduler.log = log  # type: ignore[assignment]

        with (
            patch(
                "seafile_ragflow_connector.jobs.scheduler.time.monotonic",
                side_effect=[100.0, 106.0],
            ),
            patch(
                "seafile_ragflow_connector.jobs.scheduler.time.sleep",
                side_effect=[None, _StopScheduler()],
            ),
            self.assertRaises(_StopScheduler),
        ):
            scheduler.run_forever()

        self.assertEqual(runs, ["sync"])
        self.assertEqual(
            log.warnings,
            [("scheduler.enabled_check_failed", {"error_class": "RuntimeError"})],
        )


if __name__ == "__main__":
    unittest.main()
