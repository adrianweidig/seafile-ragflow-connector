from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.db import (
    _alembic_config,
    database_revisions,
    init_database,
)


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for the PostgreSQL migration test",
)
def test_previous_release_revision_upgrades_to_head_on_postgresql() -> None:
    database_url = os.environ["TEST_POSTGRES_URL"]
    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0004_acl_search_profiles")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO sync_jobs (job_type, status, priority, attempts, max_attempts) "
                    "VALUES ('SYNC_LIBRARY_FULL', 'queued', 100, 0, 5)"
                )
            )
        command.upgrade(config, "head")
        columns = {column["name"] for column in inspect(engine).get_columns("sync_jobs")}
        indexes = {index["name"] for index in inspect(engine).get_indexes("sync_jobs")}
        with engine.connect() as connection:
            dedup_key = connection.scalar(text("SELECT dedup_key FROM sync_jobs LIMIT 1"))
        current, expected = database_revisions(database_url)

        assert "dedup_key" in columns
        assert "uq_sync_jobs_active_dedup" in indexes
        assert str(dedup_key).startswith("legacy:")
        assert current == expected == "0007_dashboard_admin_control"
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for the PostgreSQL migration test",
)
def test_empty_postgresql_database_initializes_to_head() -> None:
    database_url = os.environ["TEST_POSTGRES_URL"]
    command.downgrade(_alembic_config(database_url), "base")

    init_database(database_url)

    current, expected = database_revisions(database_url)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("sync_jobs")}
        indexes = {index["name"] for index in inspector.get_indexes("sync_jobs")}
    finally:
        engine.dispose()
    assert current == expected == "0007_dashboard_admin_control"
    assert "dedup_key" in columns
    assert "uq_sync_jobs_active_dedup" in indexes


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for the PostgreSQL concurrency test",
)
def test_parallel_identical_jobs_are_coalesced_on_postgresql() -> None:
    database_url = os.environ["TEST_POSTGRES_URL"]
    command.downgrade(_alembic_config(database_url), "base")
    init_database(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    store = JobStore(session_factory)
    spec = JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="parallel-repo")
    workers = 8
    start = Barrier(workers)

    def enqueue() -> tuple[int, bool]:
        start.wait()
        result = store.enqueue_with_result(spec)
        return result.job_id, result.deduplicated

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(lambda _index: enqueue(), range(workers)))
        job_ids = {job_id for job_id, _deduplicated in results}
        inserted = sum(not deduplicated for _job_id, deduplicated in results)
        with engine.connect() as connection:
            active_jobs = connection.scalar(
                text(
                    "SELECT count(*) FROM sync_jobs "
                    "WHERE dedup_key = :dedup_key "
                    "AND status IN ('queued', 'retrying', 'running')"
                ),
                {"dedup_key": spec.dedup_key()},
            )
    finally:
        engine.dispose()

    assert len(job_ids) == 1
    assert inserted == 1
    assert active_jobs == 1


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for the PostgreSQL concurrency test",
)
def test_parallel_claim_has_one_owner_and_fences_terminal_update_on_postgresql() -> None:
    database_url = os.environ["TEST_POSTGRES_URL"]
    command.downgrade(_alembic_config(database_url), "base")
    init_database(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    store = JobStore(session_factory)
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="claim-repo"))
    workers = 4
    start = Barrier(workers)

    def acquire(worker_id: str) -> tuple[str, int | None]:
        start.wait()
        job = store.acquire_next(worker_id)
        return worker_id, int(job.id) if job is not None else None

    try:
        worker_ids = [f"worker-{index}" for index in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(acquire, worker_ids))
        claims = [(worker_id, claimed_id) for worker_id, claimed_id in results if claimed_id]
        assert len(claims) == 1
        owner, claimed_id = claims[0]
        assert claimed_id == job_id
        assert not store.mark_succeeded(job_id, worker_id="wrong-owner")
        assert store.mark_succeeded(job_id, worker_id=owner)
        with engine.connect() as connection:
            status = connection.scalar(
                text("SELECT status FROM sync_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )
    finally:
        engine.dispose()

    assert status == JobStatus.SUCCEEDED.value
