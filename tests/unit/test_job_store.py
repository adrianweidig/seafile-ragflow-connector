from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobType
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

    store.mark_succeeded(first_id)
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
    recent_succeeded = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="recent"))
    dead = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="dead", max_attempts=1))
    store.mark_succeeded(old_succeeded)
    store.mark_succeeded(recent_succeeded)
    acquired = store.acquire_next("worker")
    assert acquired is not None and acquired.id == dead
    store.mark_failed(dead, "failed")
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
