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
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.jobs.worker import WorkerRunner, is_retryable_job_error
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.models.job import SyncJob


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
