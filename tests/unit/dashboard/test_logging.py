from __future__ import annotations

import logging
import threading

from seafile_ragflow_connector.dashboard.logging import DashboardLogHandler


class _BatchStore:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, object]]] = []
        self.written = threading.Event()

    def record_logs(
        self,
        entries: list[dict[str, object]],
        *,
        prune: bool = True,
    ) -> None:
        self.batches.append(entries)
        self.written.set()


class _FlakyBatchStore(_BatchStore):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.attempts = 0

    def record_logs(
        self,
        entries: list[dict[str, object]],
        *,
        prune: bool = True,
    ) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OSError("database unavailable")
        super().record_logs(entries, prune=prune)


def test_dashboard_log_handler_batches_without_blocking_emit() -> None:
    store = _BatchStore()
    handler = DashboardLogHandler(
        store,  # type: ignore[arg-type]
        queue_size=10,
        batch_size=10,
        flush_interval_seconds=0.01,
    )
    try:
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 1, "one", (), None))
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 2, "two", (), None))
        assert store.written.wait(timeout=1)
        handler.flush()
    finally:
        handler.close()

    assert [entry["message"] for batch in store.batches for entry in batch] == ["one", "two"]


def test_dashboard_log_handler_prioritizes_warning_when_queue_is_full() -> None:
    store = _BatchStore()
    handler = DashboardLogHandler(
        store,  # type: ignore[arg-type]
        queue_size=1,
        batch_size=1,
        flush_interval_seconds=60,
    )
    handler._stop.set()
    handler._worker.join(timeout=1)
    try:
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 1, "noise", (), None))
        handler.emit(logging.LogRecord("unit", logging.WARNING, __file__, 2, "important", (), None))
        queued = handler._queue.get_nowait()
        handler._queue.task_done()
    finally:
        handler.close()

    assert queued["message"] == "important"
    assert handler.dropped_count == 1


def test_dashboard_log_handler_retries_transient_persistence_failure() -> None:
    store = _FlakyBatchStore(failures=2)
    handler = DashboardLogHandler(
        store,  # type: ignore[arg-type]
        queue_size=10,
        batch_size=10,
        flush_interval_seconds=0.01,
        retry_backoff_seconds=0.001,
    )
    try:
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 1, "one", (), None))
        assert store.written.wait(timeout=1)
        handler.flush()
    finally:
        handler.close()

    assert store.attempts == 3
    assert handler.dropped_count == 0


def test_dashboard_log_handler_counts_permanent_persistence_loss() -> None:
    store = _FlakyBatchStore(failures=10)
    handler = DashboardLogHandler(
        store,  # type: ignore[arg-type]
        queue_size=10,
        batch_size=10,
        flush_interval_seconds=0.01,
        max_persist_attempts=2,
        retry_backoff_seconds=0.001,
    )
    try:
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 1, "one", (), None))
        handler.emit(logging.LogRecord("unit", logging.INFO, __file__, 2, "two", (), None))
        handler.flush()
    finally:
        handler.close()

    assert store.attempts >= 2
    assert handler.dropped_count == 2
