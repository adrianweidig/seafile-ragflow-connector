from __future__ import annotations

import socket
import time
from collections.abc import Callable

import structlog

from seafile_ragflow_connector.app.metrics import job_duration_seconds, jobs_failed
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
from seafile_ragflow_connector.persistence.models.job import SyncJob

JobHandler = Callable[[JobSpec], None]


class WorkerRunner:
    def __init__(
        self,
        job_store: JobStore,
        *,
        handlers: dict[JobType, JobHandler],
        signal_queue: JobSignalQueue | None = None,
        poll_seconds: int = 5,
        worker_id: str | None = None,
    ) -> None:
        self.job_store = job_store
        self.handlers = handlers
        self.signal_queue = signal_queue
        self.poll_seconds = poll_seconds
        self.worker_id = worker_id or socket.gethostname()
        self.log = structlog.get_logger(__name__).bind(worker_id=self.worker_id)

    def run_forever(self) -> None:
        while True:
            self.run_once()
            if self.signal_queue:
                try:
                    self.signal_queue.wait(timeout_seconds=self.poll_seconds)
                except Exception as exc:
                    self.log.warning("worker.signal_wait_failed", error=str(exc))
                    time.sleep(self.poll_seconds)
            else:
                time.sleep(self.poll_seconds)

    def run_once(self) -> bool:
        job = self.job_store.acquire_next(self.worker_id)
        if job is None:
            return False
        self._handle_job(job)
        return True

    def _handle_job(self, job: SyncJob) -> None:
        started = time.perf_counter()
        spec = self.job_store.to_spec(job)
        handler = self.handlers.get(spec.job_type)
        if handler is None:
            error = f"no handler registered for {spec.job_type}"
            status = self.job_store.mark_failed(job.id, error)
            jobs_failed.inc()
            job_duration_seconds.observe(time.perf_counter() - started)
            self.log.warning(
                "job.no_handler",
                job_id=job.id,
                job_type=spec.job_type,
                status=status.value,
            )
            return
        try:
            handler(spec)
        except Exception as exc:
            status = self.job_store.mark_failed(job.id, str(exc))
            jobs_failed.inc()
            job_duration_seconds.observe(time.perf_counter() - started)
            self.log.warning(
                "job.failed",
                job_id=job.id,
                job_type=spec.job_type,
                status=status.value,
            )
            return
        self.job_store.mark_succeeded(job.id)
        job_duration_seconds.observe(time.perf_counter() - started)
        self.log.info("job.succeeded", job_id=job.id, job_type=spec.job_type)
