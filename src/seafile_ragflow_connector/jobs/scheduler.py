from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval_seconds: int
    run: Callable[[], None]
    last_run_monotonic: float = 0.0


class SimpleScheduler:
    def __init__(self, tasks: list[PeriodicTask], *, sleep_seconds: int = 5) -> None:
        self.tasks = tasks
        self.sleep_seconds = sleep_seconds
        self.log = structlog.get_logger(__name__)

    def run_forever(self) -> None:
        last_runs = {task.name: task.last_run_monotonic for task in self.tasks}
        while True:
            now = time.monotonic()
            for task in self.tasks:
                if now - last_runs[task.name] >= task.interval_seconds:
                    try:
                        task.run()
                    except Exception as exc:
                        self.log.warning("scheduler.task_failed", task=task.name, error=str(exc))
                    last_runs[task.name] = now
            time.sleep(self.sleep_seconds)
