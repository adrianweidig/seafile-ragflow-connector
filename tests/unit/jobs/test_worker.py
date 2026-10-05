from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import cast

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.jobs.context import JobDeferredError
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner, is_retryable_job_error
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.sync_state import RepoMutationLeaseStore


def _store() -> JobStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return JobStore(
        sessionmaker(bind=engine, class_=Session, expire_on_commit=False),
        retry_base_seconds=1,
        retry_max_seconds=1,
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://service.internal/resource")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("timed out"), True),
        (_http_status_error(408), True),
        (_http_status_error(425), True),
        (_http_status_error(429), True),
        (_http_status_error(503), True),
        (_http_status_error(401), False),
        (_http_status_error(403), False),
        (_http_status_error(404), False),
        (_http_status_error(409), False),
        (ApiError("busy", status_code=429), True),
        (ApiError("upload rejected", status_code=200, payload={"code": 500}), True),
        (ApiError("busy", status_code=200, payload={"code": "429"}), True),
        (ApiError("invalid", status_code=200, payload={"code": 102}), False),
        (ApiError("invalid", status_code=200), False),
        (ValueError("invalid"), False),
        (KeyError("missing"), False),
        (RuntimeError("unknown"), True),
    ],
)
def test_job_error_classification(error: Exception, expected: bool) -> None:
    assert is_retryable_job_error(error) is expected


def test_worker_marks_owned_job_succeeded() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo"))
    handled: list[str | None] = []
    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: lambda spec: handled.append(spec.repo_id)},
        worker_id="worker-a",
    )

    assert runner.run_once()
    assert handled == ["repo"]
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.SUCCEEDED.value
        assert job.locked_by is None and job.locked_at is None


@pytest.mark.parametrize(
    ("error_factory", "expected_status"),
    [
        (lambda: ValueError("invalid payload"), JobStatus.DEAD),
        (lambda: ApiError("unauthorized", status_code=401), JobStatus.DEAD),
        (lambda: ApiError("rate limited", status_code=429), JobStatus.RETRYING),
        (lambda: httpx.ReadTimeout("timed out"), JobStatus.RETRYING),
        (lambda: RuntimeError("unknown"), JobStatus.RETRYING),
    ],
)
def test_worker_persists_retryable_or_terminal_failure(
    error_factory: Callable[[], Exception],
    expected_status: JobStatus,
) -> None:
    store = _store()
    job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo", max_attempts=3)
    )

    def fail(_spec: JobSpec) -> None:
        raise error_factory()

    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: fail},
        worker_id="worker-a",
    )

    assert runner.run_once()
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == expected_status.value
        assert job.error_message
        assert job.locked_by is None and job.locked_at is None


def test_missing_handler_is_terminal() -> None:
    store = _store()
    job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo", max_attempts=3)
    )
    runner = WorkerRunner(store, handlers={}, worker_id="worker-a")

    assert runner.run_once()
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.DEAD.value
        assert job.attempts == 1


def test_worker_cannot_finalize_after_owner_changes() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo"))

    def steal_lease(_spec: JobSpec) -> None:
        with store.session_factory() as session:
            job = session.get(SyncJob, job_id)
            assert job is not None
            job.locked_by = "worker-b"
            session.commit()

    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: steal_lease},
        worker_id="worker-a",
    )

    assert runner.run_once()
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING.value
        assert job.locked_by == "worker-b"


def test_running_job_cancel_request_wins_over_late_handler_failure() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo"))

    def cancel_then_fail(_spec: JobSpec) -> None:
        assert store.request_cancel(job_id)
        raise RuntimeError("late failure after cancellation")

    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: cancel_then_fail},
        worker_id="worker-a",
    )

    assert runner.run_once()
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.CANCELLED.value


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("late failure"), JobDeferredError("late defer", delay_seconds=1)],
)
def test_cancel_wins_when_requested_after_worker_precheck(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="race-repo"))
    original_cancel_requested = store.cancel_requested
    checks = 0

    def stale_cancel_check(
        checked_job_id: int,
        *,
        worker_id: str | None = None,
    ) -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            assert store.request_cancel(job_id)
            return False
        return original_cancel_requested(checked_job_id, worker_id=worker_id)

    monkeypatch.setattr(store, "cancel_requested", stale_cancel_check)

    def fail(_spec: JobSpec) -> None:
        raise failure

    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: fail},
        worker_id="worker-a",
    )

    assert runner.run_once()
    job = store.get(job_id)
    assert job is not None
    assert job.status == JobStatus.CANCELLED.value
    assert job.cancel_requested_at is not None


def test_running_job_pause_returns_to_held_queue_without_consuming_attempt() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo"))

    def pause(_spec: JobSpec) -> None:
        assert store.request_pause(job_id)
        raise RuntimeError("cooperative pause checkpoint")

    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: pause},
        worker_id="worker-a",
    )

    assert runner.run_once()
    paused = store.get(job_id)
    assert paused is not None
    assert paused.status == JobStatus.QUEUED.value
    assert paused.pause_requested_at is not None
    assert paused.attempts == 0
    assert paused.locked_by is None

    assert store.resume(job_id)
    resumed = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: lambda _spec: None},
        worker_id="worker-b",
    )
    assert resumed.run_once()
    completed = store.get(job_id)
    assert completed is not None
    assert completed.status == JobStatus.SUCCEEDED.value
    assert completed.attempts == 1


def test_busy_repository_lease_defers_job_without_consuming_attempt() -> None:
    store = _store()
    leases = RepoMutationLeaseStore(store.session_factory)
    held = leases.acquire("repo", "other-worker", lease_seconds=60)
    job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo", max_attempts=1)
    )
    handled: list[bool] = []
    runner = WorkerRunner(
        store,
        handlers={JobType.SYNC_LIBRARY_FULL: lambda _spec: handled.append(True)},
        worker_id="worker-a",
        repo_lease_store=leases,
        heartbeat_seconds=1,
    )

    assert runner.run_once()
    assert handled == []
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.RETRYING.value
        assert job.attempts == 0
    leases.release(held)


class _HeartbeatStore:
    def __init__(self, *, owned: bool = True, error: Exception | None = None) -> None:
        self.owned = owned
        self.error = error
        self.calls: list[tuple[int, str]] = []

    def heartbeat(self, job_id: int, *, worker_id: str) -> bool:
        self.calls.append((job_id, worker_id))
        if self.error is not None:
            raise self.error
        return self.owned


class _OneHeartbeatStop:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self, _timeout: float | None = None) -> bool:
        self.calls += 1
        return self.calls > 1


def test_heartbeat_refreshes_owner_and_detects_lost_lease() -> None:
    owned_store = _HeartbeatStore()
    runner = WorkerRunner(
        cast(JobStore, owned_store),
        handlers={},
        worker_id="worker-a",
        heartbeat_seconds=1,
    )
    lease_lost = Event()

    runner._heartbeat_loop(42, cast(Event, _OneHeartbeatStop()), lease_lost)

    assert owned_store.calls == [(42, "worker-a")]
    assert not lease_lost.is_set()

    lost_store = _HeartbeatStore(owned=False)
    runner = WorkerRunner(
        cast(JobStore, lost_store),
        handlers={},
        worker_id="worker-b",
        heartbeat_seconds=1,
    )
    lease_lost = Event()
    runner._heartbeat_loop(43, cast(Event, _OneHeartbeatStop()), lease_lost)

    assert lost_store.calls == [(43, "worker-b")]
    assert lease_lost.is_set()

    failing_store = _HeartbeatStore(error=RuntimeError("database unavailable"))
    runner = WorkerRunner(
        cast(JobStore, failing_store),
        handlers={},
        worker_id="worker-c",
        heartbeat_seconds=1,
    )
    lease_lost = Event()
    runner._heartbeat_loop(44, cast(Event, _OneHeartbeatStop()), lease_lost)

    assert failing_store.calls == [(44, "worker-c")]
    assert not lease_lost.is_set()


def test_default_worker_ids_are_unique_per_process_instance() -> None:
    store = _store()

    first = WorkerRunner(store, handlers={})
    second = WorkerRunner(store, handlers={})

    assert first.worker_id != second.worker_id
