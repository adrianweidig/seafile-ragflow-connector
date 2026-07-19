from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
from seafile_ragflow_connector.persistence.models.admin_control import WorkflowControlState
from seafile_ragflow_connector.persistence.models.dashboard import DashboardSyncRun
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import (
    CleanupOutbox,
    WorkflowCleanupSubscription,
    WorkflowJobSubscription,
)
from seafile_ragflow_connector.persistence.sync_state import SyncStateStore


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


def test_workflow_correlation_metadata_does_not_break_semantic_deduplication() -> None:
    store = _store()
    first = store.enqueue_with_result(
        JobSpec(
            JobType.SYNC_LIBRARY_DELTA,
            repo_id="repo-1",
            payload={"scope": "/", "workflow_run_id": "workflow-a"},
        )
    )
    second = store.enqueue_with_result(
        JobSpec(
            JobType.SYNC_LIBRARY_DELTA,
            repo_id="repo-1",
            payload={"scope": "/", "workflow_run_id": "workflow-b"},
        )
    )

    assert second.job_id == first.job_id
    assert second.deduplicated is True


def test_cancelling_workflow_does_not_cancel_attached_periodic_job() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(
        run_id="workflow",
        repo_id=None,
        mode="workflow",
        status="queued",
    )
    periodic_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="repo-1")
    )
    store.subscribe_workflow(
        "workflow",
        periodic_job_id,
        is_root=True,
        owns_job=False,
    )

    assert store.cancel_workflow_subscription("workflow") == []
    periodic_job = store.get(periodic_job_id)
    assert periodic_job is not None
    assert periodic_job.status == JobStatus.QUEUED.value


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


def test_run_binding_listing_cancel_and_retry_are_persistent() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="repo"))

    assert store.bind_run(job_id, "run-1")
    assert [job.id for job in store.list_jobs(run_id="run-1")] == [job_id]
    assert store.request_cancel(job_id)
    cancelled = store.get(job_id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED.value
    assert cancelled.cancel_requested_at is not None

    assert store.retry(job_id)
    retried = store.get(job_id)
    assert retried is not None
    assert retried.status == JobStatus.QUEUED.value
    assert retried.attempts == 0
    assert retried.cancel_requested_at is None


def test_cancel_request_wins_when_failure_or_defer_transition_runs_late() -> None:
    store = _store(retry_base_seconds=1, retry_max_seconds=1)
    failed_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="cancel-failure")
    )
    deferred_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="cancel-defer")
    )

    failed = store.acquire_next("failure-worker")
    deferred = store.acquire_next("defer-worker")
    assert failed is not None and failed.id == failed_id
    assert deferred is not None and deferred.id == deferred_id
    assert store.request_cancel(failed_id)
    assert store.request_cancel(deferred_id)

    assert (
        store.mark_failed(
            failed_id,
            "late failure",
            worker_id="failure-worker",
            retryable=True,
        )
        == JobStatus.CANCELLED
    )
    assert (
        store.defer_without_attempt(
            deferred_id,
            "late defer",
            worker_id="defer-worker",
            delay_seconds=1,
        )
        == JobStatus.CANCELLED
    )
    for job_id in (failed_id, deferred_id):
        job = store.get(job_id)
        assert job is not None
        assert job.status == JobStatus.CANCELLED.value
        assert job.cancel_requested_at is not None


def test_retry_returns_false_when_an_active_dedup_copy_exists() -> None:
    store = _store()
    spec = JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="retry-dedup")
    terminal_id = store.enqueue(spec)
    assert store.request_cancel(terminal_id)
    active_id = store.enqueue(spec)
    assert active_id != terminal_id

    assert store.retry(terminal_id) is False
    terminal = store.get(terminal_id)
    active = store.get(active_id)
    assert terminal is not None and terminal.status == JobStatus.CANCELLED.value
    assert active is not None and active.status == JobStatus.QUEUED.value


def test_global_and_library_controls_hold_claims_without_new_job_status() -> None:
    store = _store()
    controls = AdminControlStore(store.session_factory)
    global_job_id = store.enqueue(JobSpec(JobType.DISCOVER_LIBRARIES))

    controls.update_workflow(queue_paused=True, updated_by="admin")
    assert store.acquire_next("worker") is None
    controls.update_workflow(queue_paused=False, updated_by="admin")
    claimed = store.acquire_next("worker")
    assert claimed is not None and claimed.id == global_job_id
    assert store.mark_succeeded(global_job_id, worker_id="worker")

    repo_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="controlled-repo")
    )
    controls.update_library(
        "controlled-repo",
        paused=True,
        updated_by="admin",
    )
    assert store.acquire_next("worker") is None
    controls.update_library(
        "controlled-repo",
        paused=False,
        updated_by="admin",
    )
    claimed = store.acquire_next("worker")
    assert claimed is not None and claimed.id == repo_job_id


def test_paused_queued_job_stays_deduplicated_and_resumes_once() -> None:
    store = _store()
    spec = JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="paused-repo")
    job_id = store.enqueue(spec)

    assert store.request_pause(job_id)
    duplicate = store.enqueue_with_result(spec)
    assert duplicate.job_id == job_id
    assert duplicate.deduplicated is True
    assert store.acquire_next("worker") is None

    assert store.resume(job_id)
    claimed = store.acquire_next("worker")
    assert claimed is not None and claimed.id == job_id
    assert store.acquire_next("other-worker") is None


def test_global_resume_preserves_library_and_workflow_holds() -> None:
    store = _store()
    controls = AdminControlStore(store.session_factory)
    free_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="free"))
    library_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="library-held")
    )
    workflow_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="workflow-held")
    )
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="paused-workflow", repo_id=None, mode="workflow")
    store.subscribe_workflow(
        "paused-workflow",
        workflow_id,
        is_root=True,
        owns_job=True,
    )

    assert set(store.request_pause_all()) == {free_id, library_id, workflow_id}
    controls.update_library("library-held", paused=True, updated_by="admin")
    assert store.request_workflow_pause("paused-workflow") == [workflow_id]

    assert store.resume_global_pause() == [free_id]
    free = store.get(free_id)
    library = store.get(library_id)
    workflow = store.get(workflow_id)
    assert free is not None and free.pause_requested_at is None
    assert library is not None and library.pause_requested_at is not None
    assert workflow is not None and workflow.pause_requested_at is not None


def test_workflow_pause_does_not_hold_a_shared_or_unowned_job() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="workflow-a", repo_id=None, mode="workflow", status="queued")
    state.create_run(run_id="workflow-b", repo_id=None, mode="workflow", status="queued")
    with store.session_factory() as session:
        session.add(
            DashboardSyncRun(
                sync_id="workflow-a",
                source="seafile",
                target="ragflow",
                status="queued",
                summary="Workflow queued",
                started_at=datetime.now(UTC),
                details={"kind": "workflow_parent"},
            )
        )
        session.commit()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="repo"))
    store.subscribe_workflow("workflow-a", job_id, is_root=True, owns_job=True)
    store.subscribe_workflow("workflow-b", job_id, is_root=True, owns_job=False)

    assert store.request_workflow_pause("workflow-a") == []
    job = store.get(job_id)
    assert job is not None and job.pause_requested_at is None
    claimed = store.acquire_next("shared-worker")
    assert claimed is not None and claimed.id == job_id
    assert store.mark_succeeded(job_id, worker_id="shared-worker")
    assert store.refresh_workflow_parent("workflow-a") == "paused"
    paused_parent = state.get_run("workflow-a")
    assert paused_parent is not None
    assert paused_parent.progress["admin_paused"] is True
    assert paused_parent.finished_at is None
    with store.session_factory() as session:
        paused_dashboard = session.get(DashboardSyncRun, "workflow-a")
        assert paused_dashboard is not None
        assert paused_dashboard.status == "paused"
        assert paused_dashboard.ended_at is None
        assert paused_dashboard.details["admin_paused"] is True

    assert store.resume_workflow_pause("workflow-a") == []
    assert store.refresh_workflow_parent("workflow-a") == "succeeded"
    resumed_parent = state.get_run("workflow-a")
    assert resumed_parent is not None
    assert "admin_paused" not in resumed_parent.progress
    assert resumed_parent.status == "succeeded"
    assert resumed_parent.finished_at is not None
    with store.session_factory() as session:
        resumed_dashboard = session.get(DashboardSyncRun, "workflow-a")
        assert resumed_dashboard is not None
        assert resumed_dashboard.status == "succeeded"
        assert resumed_dashboard.ended_at is not None
        assert resumed_dashboard.details["admin_paused"] is False


def test_shared_job_is_held_after_owner_and_subscriber_are_both_paused() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="shared-owner", repo_id=None, mode="workflow")
    state.create_run(run_id="shared-subscriber", repo_id=None, mode="workflow")
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="shared"))
    store.subscribe_workflow("shared-owner", job_id, owns_job=True)
    store.subscribe_workflow("shared-subscriber", job_id, owns_job=False)

    assert store.request_workflow_pause("shared-owner") == []
    active = store.get(job_id)
    assert active is not None and active.pause_requested_at is None

    assert store.request_workflow_pause("shared-subscriber") == [job_id]
    held = store.get(job_id)
    assert held is not None and held.pause_requested_at is not None
    assert store.acquire_next("worker") is None

    assert store.resume_workflow_pause("shared-subscriber") == [job_id]
    resumed = store.get(job_id)
    assert resumed is not None and resumed.pause_requested_at is None


def test_active_job_keeps_mixed_dead_workflow_nonterminal_and_accepts_children() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(
        run_id="mixed-workflow",
        repo_id=None,
        mode="workflow",
        status="queued",
    )
    with store.session_factory() as session:
        session.add(
            DashboardSyncRun(
                sync_id="mixed-workflow",
                source="dashboard",
                target="job-queue",
                status="queued",
                summary="Workflow queued",
                started_at=datetime.now(UTC),
                details={"kind": "workflow_parent"},
            )
        )
        session.commit()
    dead_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="dead", max_attempts=1)
    )
    active_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="active")
    )
    store.subscribe_workflow("mixed-workflow", dead_job_id, owns_job=True)
    store.subscribe_workflow("mixed-workflow", active_job_id, owns_job=True)
    acquired = store.acquire_next("failure-worker")
    assert acquired is not None and acquired.id == dead_job_id
    assert (
        store.mark_failed(
            dead_job_id,
            "injected failure",
            worker_id="failure-worker",
            retryable=False,
        )
        == JobStatus.DEAD
    )

    assert store.refresh_workflow_parent("mixed-workflow") == "queued"
    parent = state.get_run("mixed-workflow")
    assert parent is not None
    assert parent.status == "queued"
    assert parent.finished_at is None

    child_job_id = store.enqueue(JobSpec(JobType.UPLOAD_FILE, repo_id="active"))
    store.inherit_workflow_subscriptions(
        active_job_id,
        child_job_id,
        child_created=True,
    )
    child = store.get(child_job_id)
    assert child is not None
    assert child.status == JobStatus.QUEUED.value
    assert child.cancel_requested_at is None
    assert {job.id for job in store.workflow_jobs("mixed-workflow")} == {
        dead_job_id,
        active_job_id,
        child_job_id,
    }


def test_global_resume_releases_a_shared_job_needed_by_an_active_workflow() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="paused-owner", repo_id=None, mode="workflow")
    state.create_run(run_id="active-subscriber", repo_id=None, mode="workflow")
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="shared"))
    store.subscribe_workflow("paused-owner", job_id, owns_job=True)
    store.subscribe_workflow("active-subscriber", job_id, owns_job=False)

    assert store.request_pause_all() == [job_id]
    assert store.request_workflow_pause("paused-owner") == []
    assert store.resume_global_pause() == [job_id]
    job = store.get(job_id)
    assert job is not None and job.pause_requested_at is None


def test_child_inherited_after_workflow_pause_is_held() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="paused-parent", repo_id=None, mode="workflow")
    parent_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="paused-parent")
    )
    store.subscribe_workflow("paused-parent", parent_id, owns_job=True)
    assert store.request_workflow_pause("paused-parent") == [parent_id]

    child_id = store.enqueue(JobSpec(JobType.UPLOAD_FILE, repo_id="paused-child"))
    store.inherit_workflow_subscriptions(
        parent_id,
        child_id,
        child_created=True,
    )

    child = store.get(child_id)
    assert child is not None and child.pause_requested_at is not None
    assert store.acquire_next("worker") is None


@pytest.mark.parametrize("action", ["pause", "stop", "cancel"])
def test_direct_late_subscription_inherits_workflow_control(action: str) -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    workflow_run_id = f"direct-{action}"
    state.create_run(run_id=workflow_run_id, repo_id=None, mode="workflow")
    if action == "pause":
        store.request_workflow_pause(workflow_run_id)
    elif action == "stop":
        store.stop_workflow_subscription(workflow_run_id)
    else:
        store.cancel_workflow_subscription(workflow_run_id)

    job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id=f"direct-{action}")
    )
    store.subscribe_workflow(workflow_run_id, job_id, owns_job=True)

    job = store.get(job_id)
    assert job is not None
    if action == "pause":
        assert job.status == JobStatus.QUEUED.value
        assert job.pause_requested_at is not None
    else:
        assert job.status == JobStatus.CANCELLED.value
        with store.session_factory() as session:
            subscription = session.get(
                WorkflowJobSubscription,
                (workflow_run_id, job_id),
            )
            assert subscription is not None
            assert subscription.cancelled_at is not None


@pytest.mark.parametrize("action", ["stop", "cancel"])
def test_child_inherited_after_terminal_workflow_is_unclaimable(action: str) -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    workflow_run_id = f"{action}-parent"
    state.create_run(run_id=workflow_run_id, repo_id=None, mode="workflow")
    parent_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id=f"{action}-parent")
    )
    store.subscribe_workflow(workflow_run_id, parent_id, owns_job=True)
    if action == "stop":
        store.stop_workflow_subscription(workflow_run_id)
    else:
        store.cancel_workflow_subscription(workflow_run_id)

    child_id = store.enqueue(
        JobSpec(JobType.UPLOAD_FILE, repo_id=f"{action}-child")
    )
    store.inherit_workflow_subscriptions(parent_id, child_id, child_created=True)

    child = store.get(child_id)
    assert child is not None and child.status == JobStatus.CANCELLED.value
    with store.session_factory() as session:
        subscription = session.get(
            WorkflowJobSubscription,
            (workflow_run_id, child_id),
        )
        assert subscription is not None
        assert subscription.cancelled_at is not None


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("shared-owner", "shared-subscriber"),
        ("shared-subscriber", "shared-owner"),
    ],
)
def test_last_stopped_shared_workflow_cancels_the_owned_job(
    first: str,
    second: str,
) -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="shared-owner", repo_id=None, mode="workflow")
    state.create_run(run_id="shared-subscriber", repo_id=None, mode="workflow")
    job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id=f"shared-{first}")
    )
    store.subscribe_workflow("shared-owner", job_id, owns_job=True)
    store.subscribe_workflow("shared-subscriber", job_id, owns_job=False)

    assert store.stop_workflow_subscription(first) == []
    active = store.get(job_id)
    assert active is not None and active.status == JobStatus.QUEUED.value
    assert store.stop_workflow_subscription(second) == [job_id]
    cancelled = store.get(job_id)
    assert cancelled is not None and cancelled.status == JobStatus.CANCELLED.value


def test_workflow_retry_requeues_subscribed_dead_cleanup_outbox() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="cleanup-workflow", repo_id=None, mode="workflow")
    root_job_id = store.enqueue(
        JobSpec(JobType.PROCESS_CLEANUP_OUTBOX, repo_id="cleanup-repo")
    )
    store.subscribe_workflow("cleanup-workflow", root_job_id, owns_job=True)
    with store.session_factory() as session:
        cleanup = CleanupOutbox(
            repo_id="cleanup-repo",
            target_type="ragflow_document",
            target_id="document-1",
            status="dead",
            attempts=4,
            error_message="cleanup failed",
            completed_at=datetime.now(UTC),
        )
        session.add(cleanup)
        session.flush()
        outbox_id = int(cleanup.id)
        session.commit()
    store.subscribe_cleanup_from_job(root_job_id, outbox_id)
    store.stop_workflow_subscription("cleanup-workflow")

    resumed_job_ids = store.resume_workflow_subscription("cleanup-workflow")
    assert root_job_id in resumed_job_ids
    assert any(job_id != root_job_id for job_id in resumed_job_ids)
    with store.session_factory() as session:
        cleanup = session.get(CleanupOutbox, outbox_id)
        assert cleanup is not None
        assert cleanup.status == "pending"
        assert cleanup.attempts == 0
        assert cleanup.error_message is None
        assert cleanup.completed_at is None


def test_workflow_retry_schedules_cleanup_when_original_root_already_succeeded() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(
        run_id="completed-root-cleanup",
        repo_id=None,
        mode="workflow",
        status="queued",
    )
    root_job_id = store.enqueue(
        JobSpec(JobType.PROCESS_CLEANUP_OUTBOX, repo_id="cleanup-repo")
    )
    store.subscribe_workflow(
        "completed-root-cleanup",
        root_job_id,
        owns_job=True,
    )
    acquired = store.acquire_next("cleanup-worker")
    assert acquired is not None and acquired.id == root_job_id
    assert store.mark_succeeded(root_job_id, worker_id="cleanup-worker")
    with store.session_factory() as session:
        cleanup = CleanupOutbox(
            repo_id="cleanup-repo",
            target_type="ragflow_document",
            target_id="document-1",
            status="dead",
            attempts=4,
            error_message="cleanup failed",
            completed_at=datetime.now(UTC),
        )
        session.add(cleanup)
        session.flush()
        outbox_id = int(cleanup.id)
        session.commit()
    store.subscribe_cleanup_from_job(root_job_id, outbox_id)
    assert store.refresh_workflow_parent("completed-root-cleanup") == "failed"

    resumed_job_ids = store.resume_workflow_subscription("completed-root-cleanup")

    assert root_job_id in resumed_job_ids
    cleanup_jobs = [
        job
        for job in store.list_jobs(limit=20)
        if job.job_type == JobType.PROCESS_CLEANUP_OUTBOX.value
        and job.repo_id == "cleanup-repo"
    ]
    queued_cleanup_jobs = [
        job for job in cleanup_jobs if job.status == JobStatus.QUEUED.value
    ]
    assert len(queued_cleanup_jobs) == 1
    assert queued_cleanup_jobs[0].id in resumed_job_ids
    claimed = store.acquire_next("retry-worker")
    assert claimed is not None and claimed.id == queued_cleanup_jobs[0].id
    with store.session_factory() as session:
        cleanup = session.get(CleanupOutbox, outbox_id)
        assert cleanup is not None
        assert cleanup.status == "pending"
        assert cleanup.attempts == 0
        assert cleanup.completed_at is None


def test_workflow_retry_rejects_unsafe_dataset_cleanup_atomically() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="unsafe-cleanup", repo_id=None, mode="workflow")
    root_job_id = store.enqueue(
        JobSpec(JobType.PROCESS_CLEANUP_OUTBOX, repo_id="active-repo")
    )
    store.subscribe_workflow("unsafe-cleanup", root_job_id, owns_job=True)
    with store.session_factory() as session:
        session.add(
            Library(
                repo_id="active-repo",
                name="Active",
                name_slug="active",
                deletion_state="active",
            )
        )
        cleanup = CleanupOutbox(
            repo_id="active-repo",
            target_type="ragflow_dataset",
            target_id="dataset-1",
            status="dead",
            attempts=2,
            error_message="cleanup failed",
        )
        session.add(cleanup)
        session.flush()
        outbox_id = int(cleanup.id)
        session.commit()
    store.subscribe_cleanup_from_job(root_job_id, outbox_id)
    store.stop_workflow_subscription("unsafe-cleanup")

    with pytest.raises(ValueError, match="active source library"):
        store.resume_workflow_subscription("unsafe-cleanup")

    with store.session_factory() as session:
        cleanup = session.get(CleanupOutbox, outbox_id)
        job_subscription = session.get(
            WorkflowJobSubscription,
            ("unsafe-cleanup", root_job_id),
        )
        cleanup_subscription = session.get(
            WorkflowCleanupSubscription,
            ("unsafe-cleanup", outbox_id),
        )
        assert cleanup is not None and cleanup.status == "dead"
        assert job_subscription is not None
        assert job_subscription.cancelled_at is not None
        assert cleanup_subscription is not None
        assert cleanup_subscription.cancelled_at is not None


def test_workflow_stop_is_distinct_from_cancel_and_retry_clears_admin_flags() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="stopped-workflow", repo_id=None, mode="workflow")
    with store.session_factory() as session:
        session.add(
            DashboardSyncRun(
                sync_id="stopped-workflow",
                source="seafile",
                target="ragflow",
                status="queued",
                summary="Workflow queued",
                started_at=datetime.now(UTC),
                details={"kind": "workflow_parent"},
            )
        )
        session.commit()
    stopped_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="stopped-repo")
    )
    store.subscribe_workflow(
        "stopped-workflow",
        stopped_job_id,
        is_root=True,
        owns_job=True,
    )

    assert store.stop_workflow_subscription("stopped-workflow") == [stopped_job_id]
    assert store.refresh_workflow_parent("stopped-workflow") == "stopped"
    stopped_parent = state.get_run("stopped-workflow")
    assert stopped_parent is not None
    assert stopped_parent.status == "stopped"
    assert stopped_parent.progress["admin_stopped"] is True
    with store.session_factory() as session:
        stopped_dashboard = session.get(DashboardSyncRun, "stopped-workflow")
        assert stopped_dashboard is not None
        assert stopped_dashboard.status == "stopped"
        assert stopped_dashboard.details["admin_stopped"] is True

    assert store.resume_workflow_subscription("stopped-workflow") == [stopped_job_id]
    assert store.retry(stopped_job_id)
    resumed_parent = state.get_run("stopped-workflow")
    assert resumed_parent is not None
    assert "admin_paused" not in resumed_parent.progress
    assert "admin_stopped" not in resumed_parent.progress
    with store.session_factory() as session:
        resumed_dashboard = session.get(DashboardSyncRun, "stopped-workflow")
        assert resumed_dashboard is not None
        assert resumed_dashboard.status == "queued"
        assert resumed_dashboard.details["admin_paused"] is False
        assert resumed_dashboard.details["admin_stopped"] is False

    state.create_run(run_id="cancelled-workflow", repo_id=None, mode="workflow")
    cancelled_job_id = store.enqueue(
        JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="cancelled-repo")
    )
    store.subscribe_workflow(
        "cancelled-workflow",
        cancelled_job_id,
        is_root=True,
        owns_job=True,
    )
    assert store.cancel_workflow_subscription("cancelled-workflow") == [cancelled_job_id]
    assert store.refresh_workflow_parent("cancelled-workflow") == "cancelled"
    cancelled_parent = state.get_run("cancelled-workflow")
    assert cancelled_parent is not None
    assert cancelled_parent.status == "cancelled"
    assert "admin_stopped" not in cancelled_parent.progress


def test_refresh_does_not_overwrite_cancel_with_a_stale_job_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(run_id="cancel-race", repo_id=None, mode="workflow")
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="cancel-race"))
    store.subscribe_workflow("cancel-race", job_id, owns_job=True)
    stale_job = store.get(job_id)
    assert stale_job is not None and stale_job.status == JobStatus.QUEUED.value

    assert store.cancel_workflow_subscription("cancel-race") == [job_id]
    monkeypatch.setattr(store, "workflow_jobs", lambda _workflow_run_id: [stale_job])

    assert store.refresh_workflow_parent("cancel-race") == "cancelled"
    parent = state.get_run("cancel-race")
    assert parent is not None and parent.status == "cancelled"
    assert parent.finished_at is not None


@pytest.mark.parametrize("terminal_status", ["succeeded", "failed", "cancelled", "stopped"])
def test_refresh_preserves_terminal_parent_without_retained_subscriptions(
    terminal_status: str,
) -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(
        run_id=f"retained-{terminal_status}",
        repo_id=None,
        mode="workflow",
        status=terminal_status,
    )

    assert (
        store.refresh_workflow_parent(f"retained-{terminal_status}")
        == terminal_status
    )
    parent = state.get_run(f"retained-{terminal_status}")
    assert parent is not None and parent.status == terminal_status
    assert parent.finished_at is not None


def test_refresh_preserves_succeeded_parent_after_job_retention_purge() -> None:
    store = _store()
    state = SyncStateStore(store.session_factory)
    state.create_run(
        run_id="purged-success",
        repo_id=None,
        mode="workflow",
        status="queued",
    )
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="purged"))
    store.subscribe_workflow("purged-success", job_id, owns_job=True)
    acquired = store.acquire_next("retention-worker")
    assert acquired is not None and acquired.id == job_id
    assert store.mark_succeeded(job_id, worker_id="retention-worker")
    assert store.refresh_workflow_parent("purged-success") == "succeeded"
    finished_before_purge = state.get_run("purged-success")
    assert finished_before_purge is not None
    finished_at = finished_before_purge.finished_at
    assert finished_at is not None
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        job.updated_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()
    assert store.purge_completed_jobs(older_than_days=30) == 1

    assert store.refresh_workflow_parent("purged-success") == "succeeded"
    parent = state.get_run("purged-success")
    assert parent is not None and parent.status == "succeeded"
    assert parent.finished_at == finished_at


def test_sqlite_claim_waits_for_global_pause_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "admin-claim-race.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    try:
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )
        store = JobStore(session_factory)
        AdminControlStore(session_factory).initialize_workflow("running")
        job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_DELTA, repo_id="paused"))
        claimed: list[SyncJob | None] = []
        errors: list[Exception] = []
        completed = threading.Event()

        def claim() -> None:
            try:
                claimed.append(store.acquire_next("sqlite-worker"))
            except Exception as exc:  # pragma: no cover - assertion captures detail
                errors.append(exc)
            finally:
                completed.set()

        with session_factory() as admin_session:
            admin_session.execute(text("BEGIN IMMEDIATE"))
            control = admin_session.get(WorkflowControlState, 1)
            assert control is not None
            control.queue_paused = True
            admin_session.flush()
            thread = threading.Thread(target=claim, daemon=True)
            thread.start()
            assert not completed.wait(0.2)
            admin_session.commit()
        assert completed.wait(5)
        thread.join(timeout=1)
        assert errors == []
        assert claimed == [None]
        queued = store.get(job_id)
        assert queued is not None and queued.status == JobStatus.QUEUED.value
    finally:
        engine.dispose()


def test_stale_cancelled_job_is_never_requeued() -> None:
    store = _store()
    job_id = store.enqueue(JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="stop-repo"))
    claimed = store.acquire_next("worker")
    assert claimed is not None and claimed.id == job_id
    assert store.request_cancel(job_id)
    with store.session_factory() as session:
        job = session.get(SyncJob, job_id)
        assert job is not None
        job.locked_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()

    store.requeue_stale_running_jobs(older_than_seconds=60)

    stopped = store.get(job_id)
    assert stopped is not None
    assert stopped.status == JobStatus.CANCELLED.value
    assert store.acquire_next("new-worker") is None
