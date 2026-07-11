from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.models.job import SyncJob


def _store(
    *,
    default_max_attempts: int = 5,
    retry_base_seconds: int = 30,
    retry_max_seconds: int = 3600,
) -> JobStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return JobStore(
        sessionmaker(bind=engine, class_=Session, expire_on_commit=False),
        default_max_attempts=default_max_attempts,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )


def test_configured_max_attempts_is_default_and_explicit_override_is_preserved() -> None:
    store = _store(default_max_attempts=7)

    default_job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="default"))
    override_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="override", max_attempts=2)
    )

    with store.session_factory() as session:
        default_job = session.get(SyncJob, default_job_id)
        override_job = session.get(SyncJob, override_job_id)
        assert default_job is not None and default_job.max_attempts == 7
        assert override_job is not None and override_job.max_attempts == 2


def test_job_store_rejects_invalid_retry_configuration() -> None:
    invalid_settings = (
        {"default_max_attempts": 0},
        {"retry_base_seconds": 0},
        {"retry_max_seconds": 0},
        {"retry_base_seconds": 31, "retry_max_seconds": 30},
    )

    for settings in invalid_settings:
        try:
            _store(**settings)
        except ValueError:
            continue
        raise AssertionError(f"expected invalid job store settings to fail: {settings}")


def test_job_spec_rejects_non_positive_max_attempts_when_enqueued() -> None:
    store = _store()

    for max_attempts in (0, -1):
        try:
            store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, max_attempts=max_attempts))
        except ValueError:
            continue
        raise AssertionError(f"expected max_attempts={max_attempts} to fail")


def test_semantically_identical_active_jobs_are_coalesced() -> None:
    store = _store()
    first = store.enqueue_with_result(
        JobSpec(
            JobType.SYNC_LIBRARY_FULL,
            repo_id="repo-1",
            payload={"mode": "full", "options": {"b": 2, "a": 1}},
        )
    )
    second = store.enqueue_with_result(
        JobSpec(
            JobType.SYNC_LIBRARY_FULL,
            repo_id="repo-1",
            payload={"options": {"a": 1, "b": 2}, "mode": "full"},
        )
    )

    assert second.job_id == first.job_id
    assert second.deduplicated is True


def test_completed_job_frees_dedup_key_for_next_periodic_run() -> None:
    store = _store()
    spec = JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo-1")
    first_id = store.enqueue(spec)

    acquired = store.acquire_next("worker-1")
    assert acquired is not None and acquired.id == first_id
    assert store.mark_succeeded(first_id, worker_id="worker-1")
    second = store.enqueue_with_result(spec)

    assert second.job_id != first_id
    assert second.deduplicated is False


def test_job_path_and_payload_participate_in_dedup_key() -> None:
    store = _store()

    first = store.enqueue(
        JobSpec(JobType.UPLOAD_FILE, repo_id="repo-1", file_path="/a.txt", payload={"v": 1})
    )
    second = store.enqueue(
        JobSpec(JobType.UPLOAD_FILE, repo_id="repo-1", file_path="/b.txt", payload={"v": 1})
    )
    third = store.enqueue(
        JobSpec(JobType.UPLOAD_FILE, repo_id="repo-1", file_path="/a.txt", payload={"v": 2})
    )

    assert len({first, second, third}) == 3


def test_completed_job_retention_keeps_recent_and_dead_jobs() -> None:
    store = _store()
    old_succeeded = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="old"))
    acquired = store.acquire_next("worker")
    assert acquired is not None and acquired.id == old_succeeded
    assert store.mark_succeeded(old_succeeded, worker_id="worker")
    recent_succeeded = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="recent"))
    acquired = store.acquire_next("worker")
    assert acquired is not None and acquired.id == recent_succeeded
    assert store.mark_succeeded(recent_succeeded, worker_id="worker")
    dead = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="dead", max_attempts=1))
    acquired = store.acquire_next("worker")
    assert acquired is not None and acquired.id == dead
    assert (
        store.mark_failed(dead, "failed", worker_id="worker", retryable=True)
        == JobStatus.DEAD
    )
    with store.session_factory() as session:
        old = session.get(SyncJob, old_succeeded)
        assert old is not None
        old.updated_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()

    assert store.purge_completed_jobs(older_than_days=30) == 1
    with store.session_factory() as session:
        assert session.get(SyncJob, old_succeeded) is None
        assert session.get(SyncJob, recent_succeeded) is not None
        assert session.get(SyncJob, dead) is not None


def test_job_transitions_require_running_status_and_matching_owner() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="owned"))

    assert not store.mark_succeeded(job_id, worker_id="worker-a")
    assert store.mark_failed(
        job_id,
        "not running",
        worker_id="worker-a",
        retryable=True,
    ) is None
    acquired = store.acquire_next("worker-a")
    assert acquired is not None and acquired.id == job_id

    assert not store.heartbeat(job_id, worker_id="worker-b")
    assert not store.mark_succeeded(job_id, worker_id="worker-b")
    assert store.mark_failed(
        job_id,
        "wrong owner",
        worker_id="worker-b",
        retryable=False,
    ) is None
    assert store.heartbeat(job_id, worker_id="worker-a")
    assert store.mark_succeeded(job_id, worker_id="worker-a")
    assert not store.mark_succeeded(job_id, worker_id="worker-a")


def test_retryability_and_attempt_limit_determine_terminal_state() -> None:
    store = _store(retry_base_seconds=1, retry_max_seconds=1)
    retry_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="retry", max_attempts=3)
    )
    terminal_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="terminal", max_attempts=3)
    )
    exhausted_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="exhausted", max_attempts=1)
    )

    acquired = store.acquire_next("worker-a")
    assert acquired is not None and acquired.id == retry_id
    assert (
        store.mark_failed(
            retry_id,
            "temporary",
            worker_id="worker-a",
            retryable=True,
        )
        == JobStatus.RETRYING
    )
    acquired = store.acquire_next("worker-b")
    assert acquired is not None and acquired.id == terminal_id
    assert (
        store.mark_failed(
            terminal_id,
            "invalid payload",
            worker_id="worker-b",
            retryable=False,
        )
        == JobStatus.DEAD
    )
    acquired = store.acquire_next("worker-c")
    assert acquired is not None and acquired.id == exhausted_id
    assert (
        store.mark_failed(
            exhausted_id,
            "still unavailable",
            worker_id="worker-c",
            retryable=True,
        )
        == JobStatus.DEAD
    )

    with store.session_factory() as session:
        retry = session.get(SyncJob, retry_id)
        terminal = session.get(SyncJob, terminal_id)
        exhausted = session.get(SyncJob, exhausted_id)
        assert retry is not None and retry.status == JobStatus.RETRYING.value
        assert retry.locked_by is None and retry.locked_at is None
        assert terminal is not None and terminal.attempts < terminal.max_attempts
        assert terminal.status == JobStatus.DEAD.value
        assert exhausted is not None and exhausted.attempts == exhausted.max_attempts
        assert exhausted.status == JobStatus.DEAD.value


def test_stale_recovery_retries_or_exhausts_and_fences_old_worker() -> None:
    store = _store(retry_base_seconds=1, retry_max_seconds=1)
    retry_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="retry-stale", max_attempts=2)
    )
    dead_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="dead-stale", max_attempts=1)
    )
    assert store.acquire_next("old-worker").id == retry_id  # type: ignore[union-attr]
    assert store.acquire_next("dead-worker").id == dead_id  # type: ignore[union-attr]
    with store.session_factory() as session:
        stale_at = datetime.now(UTC) - timedelta(minutes=20)
        retry = session.get(SyncJob, retry_id)
        dead = session.get(SyncJob, dead_id)
        assert retry is not None and dead is not None
        retry.locked_at = stale_at
        dead.locked_at = stale_at
        session.commit()
        session.expunge(retry)
        retry_snapshot = retry

    recovered = store.requeue_stale_running_jobs(older_than_seconds=60)

    assert recovered.retrying == 1
    assert recovered.dead == 1
    assert recovered.total == 2
    assert not store.mark_succeeded(retry_id, worker_id="old-worker")
    with store.session_factory() as session:
        retry = session.get(SyncJob, retry_id)
        dead = session.get(SyncJob, dead_id)
        assert retry is not None and dead is not None
        assert retry.status == JobStatus.RETRYING.value
        assert retry.error_message == "worker_lease_expired"
        retry.run_after = datetime.now(UTC) - timedelta(seconds=1)
        assert dead.status == JobStatus.DEAD.value
        assert dead.error_message == "worker_lease_expired"
        session.commit()

    reclaimed = store.acquire_next("new-worker")
    assert reclaimed is not None and reclaimed.id == retry_id
    assert not store.mark_succeeded(retry_id, worker_id="old-worker")
    with store.session_factory() as session:
        stale_failure = store._mark_failed_job(
            session,
            retry_snapshot,
            "old worker failed late",
            retryable=False,
            now=datetime.now(UTC),
        )
        session.commit()
    assert stale_failure is None
    assert store.mark_succeeded(retry_id, worker_id="new-worker")


def test_stale_recovery_cas_does_not_overwrite_fresh_heartbeat() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="heartbeat-race"))
    acquired = store.acquire_next("worker-a")
    assert acquired is not None and acquired.id == job_id
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        job.locked_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()
    with store.session_factory() as session:
        stale_snapshot = session.get(SyncJob, job_id)
        assert stale_snapshot is not None
        session.expunge(stale_snapshot)

    assert store.heartbeat(job_id, worker_id="worker-a")
    now = datetime.now(UTC)
    with store.session_factory() as session:
        recovered = store._recover_stale_job(
            session,
            stale_snapshot,
            cutoff=now - timedelta(minutes=1),
            now=now,
        )
        session.commit()

    assert recovered is None
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING.value
        assert job.locked_by == "worker-a"
