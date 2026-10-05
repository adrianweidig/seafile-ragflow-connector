from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from threading import Event, Thread
from uuid import uuid4

import httpx
import structlog

from seafile_ragflow_connector.app.metrics import job_duration_seconds, jobs_failed
from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.jobs.context import (
    JobDeferredError,
    activate_job_cancellation,
    activate_job_execution,
    activate_job_pause,
)
from seafile_ragflow_connector.jobs.job_store import JobSignalQueue, JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.sync_state import (
    RepoLeaseBusyError,
    RepoLeaseHandle,
    RepoMutationLeaseStore,
    activate_repo_lease,
)

JobHandler = Callable[[JobSpec], None]


class WorkerRunner:
    def __init__(
        self,
        job_store: JobStore,
        *,
        handlers: dict[JobType, JobHandler],
        signal_queue: JobSignalQueue | None = None,
        poll_seconds: int = 5,
        heartbeat_seconds: int = 60,
        worker_id: str | None = None,
        repo_lease_store: RepoMutationLeaseStore | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.job_store = job_store
        self.handlers = handlers
        self.signal_queue = signal_queue
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
        )
        session_factory = getattr(job_store, "session_factory", None)
        self.repo_lease_store = repo_lease_store or (
            RepoMutationLeaseStore(session_factory) if session_factory is not None else None
        )
        self.repo_lease_seconds = max(180, heartbeat_seconds * 3)
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
        self._refresh_workflow_parents(job)
        if self.job_store.cancel_requested(job.id, worker_id=self.worker_id):
            if not self.job_store.mark_cancelled(job.id, worker_id=self.worker_id):
                self._log_lease_lost(job)
                return
            self.log.info("job.cancelled", job_id=job.id, job_type=spec.job_type)
            self._refresh_workflow_parents(job)
            return
        if self.job_store.pause_requested(job.id, worker_id=self.worker_id):
            if not self.job_store.hold_running_for_pause(
                job.id,
                worker_id=self.worker_id,
            ):
                self._log_lease_lost(job)
                return
            self.log.info("job.paused", job_id=job.id, job_type=spec.job_type)
            self._refresh_workflow_parents(job)
            return
        handler = self.handlers.get(spec.job_type)
        if handler is None:
            error = f"no handler registered for {spec.job_type}"
            status = self.job_store.mark_failed(
                job.id,
                error,
                worker_id=self.worker_id,
                retryable=False,
            )
            job_duration_seconds.observe(time.perf_counter() - started)
            if status is None:
                self._log_lease_lost(job)
                return
            if not self._log_controlled_transition(job, spec, status):
                jobs_failed.inc()
                self.log.warning(
                    "job.no_handler",
                    job_id=job.id,
                    job_type=spec.job_type,
                    status=status.value,
                )
            self._refresh_workflow_parents(job)
            return

        repo_lease: RepoLeaseHandle | None = None
        if spec.repo_id and self.repo_lease_store is not None:
            try:
                repo_lease = self.repo_lease_store.acquire(
                    spec.repo_id,
                    f"job:{job.id}:{self.worker_id}",
                    lease_seconds=self.repo_lease_seconds,
                )
                if not self.job_store.set_fence_token(
                    job.id,
                    worker_id=self.worker_id,
                    fence_token=repo_lease.fence_token,
                ):
                    raise RuntimeError("job lease was lost before repository lease binding")
            except Exception as exc:
                if isinstance(exc, RepoLeaseBusyError):
                    status = self.job_store.defer_without_attempt(
                        job.id,
                        str(exc),
                        worker_id=self.worker_id,
                        delay_seconds=min(30, self.heartbeat_seconds),
                    )
                else:
                    status = self.job_store.mark_failed(
                        job.id,
                        str(exc),
                        worker_id=self.worker_id,
                        retryable=True,
                    )
                if repo_lease is not None:
                    self.repo_lease_store.release(repo_lease)
                if status is None:
                    self._log_lease_lost(job)
                elif self._log_controlled_transition(job, spec, status):
                    pass
                elif isinstance(exc, RepoLeaseBusyError):
                    self.log.info(
                        "job.repo_lease_deferred",
                        job_id=job.id,
                        repo_id=spec.repo_id,
                    )
                else:
                    jobs_failed.inc()
                    self.log.warning(
                        "job.repo_lease_unavailable",
                        job_id=job.id,
                        repo_id=spec.repo_id,
                        status=status.value,
                    )
                self._refresh_workflow_parents(job)
                return

        heartbeat_stop = Event()
        lease_lost = Event()
        heartbeat = Thread(
            target=self._heartbeat_loop,
            args=(job.id, heartbeat_stop, lease_lost, repo_lease),
            name=f"connector-job-heartbeat-{job.id}",
            daemon=True,
        )
        heartbeat.start()
        failure: Exception | None = None
        try:
            context = activate_repo_lease(repo_lease) if repo_lease else nullcontext()
            with (
                context,
                activate_job_execution(job.id, job.run_id),
                activate_job_cancellation(
                    lambda: self.job_store.cancel_requested(
                        job.id,
                        worker_id=self.worker_id,
                    )
                ),
                activate_job_pause(
                    lambda: self.job_store.pause_requested(
                        job.id,
                        worker_id=self.worker_id,
                    )
                ),
            ):
                handler(spec)
        except Exception as exc:
            failure = exc
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=min(float(self.heartbeat_seconds), 5.0))
            if heartbeat.is_alive():
                self.log.warning(
                    "job.heartbeat_stop_timeout",
                    job_id=job.id,
                )
        job_duration_seconds.observe(time.perf_counter() - started)

        try:
            if lease_lost.is_set():
                self._log_lease_lost(job)
                return
            if self.job_store.cancel_requested(job.id, worker_id=self.worker_id):
                if not self.job_store.mark_cancelled(job.id, worker_id=self.worker_id):
                    self._log_lease_lost(job)
                    return
                self.log.info("job.cancelled", job_id=job.id, job_type=spec.job_type)
                self._refresh_workflow_parents(job)
                return
            if failure is not None and self.job_store.pause_requested(
                job.id,
                worker_id=self.worker_id,
            ):
                if not self.job_store.hold_running_for_pause(
                    job.id,
                    worker_id=self.worker_id,
                ):
                    self._log_lease_lost(job)
                    return
                self.log.info("job.paused", job_id=job.id, job_type=spec.job_type)
                self._refresh_workflow_parents(job)
                return
            if failure is not None:
                if isinstance(failure, JobDeferredError):
                    status = self.job_store.defer_without_attempt(
                        job.id,
                        str(failure),
                        worker_id=self.worker_id,
                        delay_seconds=failure.delay_seconds,
                    )
                    if status is None:
                        self._log_lease_lost(job)
                        return
                    if not self._log_controlled_transition(job, spec, status):
                        self.log.info(
                            "job.deferred",
                            job_id=job.id,
                            job_type=spec.job_type,
                            delay_seconds=failure.delay_seconds,
                        )
                    self._refresh_workflow_parents(job)
                    return
                retryable = is_retryable_job_error(failure)
                status = self.job_store.mark_failed(
                    job.id,
                    str(failure),
                    worker_id=self.worker_id,
                    retryable=retryable,
                )
                if status is None:
                    self._log_lease_lost(job)
                    return
                if not self._log_controlled_transition(job, spec, status):
                    jobs_failed.inc()
                    self.log.warning(
                        "job.failed",
                        job_id=job.id,
                        job_type=spec.job_type,
                        status=status.value,
                        retryable=retryable,
                    )
                self._refresh_workflow_parents(job)
                return
            if not self.job_store.mark_succeeded(job.id, worker_id=self.worker_id):
                if self.job_store.cancel_requested(
                    job.id,
                    worker_id=self.worker_id,
                ) and self.job_store.mark_cancelled(job.id, worker_id=self.worker_id):
                    self.log.info(
                        "job.cancelled",
                        job_id=job.id,
                        job_type=spec.job_type,
                    )
                    self._refresh_workflow_parents(job)
                    return
                if self.job_store.pause_requested(
                    job.id,
                    worker_id=self.worker_id,
                ) and self.job_store.hold_running_for_pause(
                        job.id,
                        worker_id=self.worker_id,
                ):
                    self.log.info(
                        "job.paused",
                        job_id=job.id,
                        job_type=spec.job_type,
                    )
                    self._refresh_workflow_parents(job)
                    return
                self._log_lease_lost(job)
                return
            self.log.info("job.succeeded", job_id=job.id, job_type=spec.job_type)
            self._refresh_workflow_parents(job)
        finally:
            if repo_lease is not None and self.repo_lease_store is not None:
                self.repo_lease_store.release(repo_lease)

    def _heartbeat_loop(
        self,
        job_id: int,
        stop: Event,
        lease_lost: Event,
        repo_lease: RepoLeaseHandle | None = None,
    ) -> None:
        while not stop.wait(self.heartbeat_seconds):
            try:
                owned = self.job_store.heartbeat(job_id, worker_id=self.worker_id)
            except Exception as exc:
                self.log.warning(
                    "job.heartbeat_failed",
                    job_id=job_id,
                    error_class=type(exc).__name__,
                )
                continue
            if not owned:
                lease_lost.set()
                return
            if repo_lease is not None and self.repo_lease_store is not None:
                try:
                    repo_owned = self.repo_lease_store.heartbeat(
                        repo_lease,
                        lease_seconds=self.repo_lease_seconds,
                    )
                except Exception as exc:
                    self.log.warning(
                        "job.repo_lease_heartbeat_failed",
                        job_id=job_id,
                        error_class=type(exc).__name__,
                    )
                    continue
                if not repo_owned:
                    lease_lost.set()
                    return

    def _log_lease_lost(self, job: SyncJob) -> None:
        self.log.warning(
            "job.lease_lost",
            job_id=job.id,
            job_type=job.job_type,
        )

    def _log_controlled_transition(
        self,
        job: SyncJob,
        spec: JobSpec,
        status: JobStatus,
    ) -> bool:
        if status == JobStatus.CANCELLED:
            self.log.info(
                "job.cancelled",
                job_id=job.id,
                job_type=spec.job_type,
            )
            return True
        if status == JobStatus.QUEUED:
            self.log.info(
                "job.paused",
                job_id=job.id,
                job_type=spec.job_type,
            )
            return True
        return False

    def _refresh_workflow_parents(self, job: SyncJob) -> None:
        try:
            self.job_store.refresh_workflow_parents_for_job(int(job.id))
        except Exception as exc:
            self.log.warning(
                "workflow.parent_refresh_failed",
                job_id=job.id,
                error_class=type(exc).__name__,
            )


def is_retryable_job_error(exc: Exception) -> bool:
    if isinstance(exc, ApiError):
        if exc.status_code not in {None, 200}:
            return _is_retryable_status(exc.status_code)
        if isinstance(exc.payload, Mapping):
            return _is_retryable_status(_normalized_status_code(exc.payload.get("code")))
        return _is_retryable_status(exc.status_code)
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_status(exc.response.status_code)
    if isinstance(exc, httpx.RequestError):
        return True
    return not isinstance(exc, (ValueError, KeyError, TypeError, PermissionError))


def _is_retryable_status(status_code: int | None) -> bool:
    return status_code in {408, 425, 429} or bool(status_code and status_code >= 500)


def _normalized_status_code(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
