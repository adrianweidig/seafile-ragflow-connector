from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Mapping
from typing import Any

from seafile_ragflow_connector.app.metrics import dashboard_logs_dropped_total
from seafile_ragflow_connector.dashboard.store import DashboardEventStore


class DashboardLogHandler(logging.Handler):
    def __init__(
        self,
        store: DashboardEventStore,
        *,
        queue_size: int = 5_000,
        batch_size: int = 100,
        flush_interval_seconds: float = 0.25,
        max_persist_attempts: int = 3,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        super().__init__()
        if (
            queue_size <= 0
            or batch_size <= 0
            or flush_interval_seconds <= 0
            or max_persist_attempts <= 0
            or retry_backoff_seconds <= 0
        ):
            raise ValueError("dashboard log queue settings must be positive")
        self.store = store
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.max_persist_attempts = max_persist_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._last_prune_monotonic = 0.0
        self._worker = threading.Thread(
            target=self._run,
            name="dashboard-log-writer",
            daemon=True,
        )
        self._worker.start()

    @property
    def dropped_count(self) -> int:
        with self._dropped_lock:
            return self._dropped

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            details: dict[str, Any] = {}
            event_name = message
            sync_id = None
            level = record.levelname.lower()
            try:
                payload = json.loads(message)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                details = dict(payload)
                event_name = str(payload.get("event") or payload.get("message") or message)
                sync_id_value = payload.get("sync_id")
                sync_id = str(sync_id_value) if sync_id_value else None
                level = str(payload.get("level") or level).lower()
            entry = {
                "level": level,
                "message": event_name,
                "component": record.name,
                "sync_id": sync_id,
                "details": details,
            }
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                self._record_drop()
                if record.levelno >= logging.WARNING:
                    self._replace_oldest(entry)
        except Exception:
            # Dashboard persistence must never destabilize the connector or recurse through logging.
            return

    def flush(self) -> None:
        deadline = time.monotonic() + 2.0
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        if not self._stop.is_set():
            self._stop.set()
            self._worker.join(timeout=2.0)
        super().close()

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            batch: list[dict[str, Any]] = []
            try:
                first = self._queue.get(timeout=self.flush_interval_seconds)
            except queue.Empty:
                continue
            batch.append(first)
            deadline = time.monotonic() + self.flush_interval_seconds
            while len(batch) < self.batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            persisted = False
            try:
                for attempt in range(self.max_persist_attempts):
                    if self._persist_batch(batch):
                        persisted = True
                        break
                    if attempt + 1 < self.max_persist_attempts:
                        self._stop.wait(self.retry_backoff_seconds * (2**attempt))
                if not persisted:
                    self._record_drops(len(batch))
            finally:
                for _entry in batch:
                    self._queue.task_done()

    def _persist_batch(self, batch: list[dict[str, Any]]) -> bool:
        try:
            record_logs = getattr(self.store, "record_logs", None)
            if callable(record_logs):
                now = time.monotonic()
                prune = now - self._last_prune_monotonic >= 60.0
                record_logs(batch, prune=prune)
                if prune:
                    self._last_prune_monotonic = now
                return True
            for entry in batch:  # pragma: no cover - compatibility for external stores
                self.store.record_log(**entry)
            return True
        except Exception:
            # Persisting dashboard logs must never recursively log or stop the connector.
            return False

    def _replace_oldest(self, entry: Mapping[str, Any]) -> None:
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self._queue.task_done()
        try:
            self._queue.put_nowait(dict(entry))
        except queue.Full:
            self._record_drop()

    def _record_drop(self) -> None:
        self._record_drops(1)

    def _record_drops(self, count: int) -> None:
        with self._dropped_lock:
            self._dropped += count
        dashboard_logs_dropped_total.inc(count)
