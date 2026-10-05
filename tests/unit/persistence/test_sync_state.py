from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import RepoMutationLease
from seafile_ragflow_connector.persistence.sync_state import (
    RepoLeaseBusyError,
    RepoLeaseLostError,
    RepoMutationLeaseStore,
    SyncStateStore,
)


def _stores() -> tuple[RepoMutationLeaseStore, SyncStateStore]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return RepoMutationLeaseStore(factory), SyncStateStore(factory)


def test_repo_lease_serializes_owners_and_increments_fence_on_takeover() -> None:
    leases, _state = _stores()

    first = leases.acquire("repo", "worker-a", lease_seconds=60)
    assert first.fence_token == 1
    with pytest.raises(RepoLeaseBusyError):
        leases.acquire("repo", "worker-b", lease_seconds=60)
    assert leases.release(first)

    second = leases.acquire("repo", "worker-b", lease_seconds=60)
    assert second.fence_token == 2
    with pytest.raises(RepoLeaseLostError):
        leases.assert_owned(first)
    leases.assert_owned(second)


def test_expired_repo_lease_can_be_taken_over_but_old_fence_cannot_heartbeat() -> None:
    leases, _state = _stores()
    first = leases.acquire("repo", "worker-a", lease_seconds=60)
    with leases.session_factory() as session:
        row = session.get(RepoMutationLease, "repo")
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    second = leases.acquire("repo", "worker-b", lease_seconds=60)

    assert second.fence_token == first.fence_token + 1
    assert not leases.heartbeat(first)
    assert leases.heartbeat(second)


def test_snapshot_cursor_compare_and_swap_rejects_stale_baseline() -> None:
    _leases, state = _stores()
    with state.session_factory() as session:
        session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
        session.commit()
    first = state.replace_snapshot(
        repo_id="repo",
        commit_id="c1",
        scope="/",
        entries=[
            {
                "path": "/a.txt",
                "normalized_path": "/a.txt",
                "object_id": "obj-a",
                "is_directory": False,
            }
        ],
    )
    second = state.replace_snapshot(
        repo_id="repo",
        commit_id="c2",
        scope="/",
        entries=[
            {
                "path": "/a.txt",
                "normalized_path": "/a.txt",
                "object_id": "obj-b",
                "is_directory": False,
            }
        ],
    )

    assert state.advance_cursor(
        repo_id="repo",
        scope="/",
        expected_commit_id=None,
        target_commit_id="c1",
        snapshot_id=first.snapshot_id,
    )
    assert not state.advance_cursor(
        repo_id="repo",
        scope="/",
        expected_commit_id=None,
        target_commit_id="c2",
        snapshot_id=second.snapshot_id,
    )
    assert state.advance_cursor(
        repo_id="repo",
        scope="/",
        expected_commit_id="c1",
        target_commit_id="c2",
        snapshot_id=second.snapshot_id,
    )
    cursor = state.get_cursor("repo")
    assert cursor is not None
    assert cursor.commit_id == "c2"
    assert cursor.version == 2


def test_snapshot_pruning_keeps_cursor_active_run_job_and_recent_baselines() -> None:
    _leases, state = _stores()
    with state.session_factory() as session:
        session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
        session.commit()
    snapshots = [
        state.replace_snapshot(
            repo_id="repo",
            commit_id=f"c{index}",
            scope="/",
            entries=[
                {
                    "path": f"/{index}.txt",
                    "normalized_path": f"/{index}.txt",
                    "object_id": f"obj-{index}",
                    "is_directory": False,
                }
            ],
        )
        for index in range(1, 7)
    ]
    state.create_run(
        run_id="active-run",
        repo_id="repo",
        mode="delta",
        target_commit_id="c1",
    )
    with state.session_factory() as session:
        session.add(
            SyncJob(
                job_type="RECONCILE_LIBRARY",
                repo_id="repo",
                dedup_key="active-reconcile",
                payload={"snapshot_id": snapshots[2].snapshot_id},
                status="queued",
            )
        )
        session.commit()

    assert state.advance_cursor(
        repo_id="repo",
        scope="/",
        expected_commit_id=None,
        target_commit_id="c2",
        snapshot_id=snapshots[1].snapshot_id,
    )

    assert state.get_snapshot(snapshots[0].snapshot_id) is not None
    assert state.get_snapshot(snapshots[1].snapshot_id) is not None
    assert state.get_snapshot(snapshots[2].snapshot_id) is not None
    assert state.get_snapshot(snapshots[3].snapshot_id) is None
    assert state.get_snapshot(snapshots[4].snapshot_id) is not None
    assert state.get_snapshot(snapshots[5].snapshot_id) is not None


def test_parent_run_can_span_repositories_and_cancel_cascades_to_children() -> None:
    _leases, state = _stores()
    with state.session_factory() as session:
        session.add_all(
            [
                Library(repo_id="repo-a", name="A", name_slug="a"),
                Library(repo_id="repo-b", name="B", name_slug="b"),
            ]
        )
        session.commit()
    parent = state.create_run(repo_id=None, mode="workflow", status="running")
    child_a = state.create_run(
        repo_id="repo-a",
        mode="delta",
        parent_run_id=parent,
    )
    child_b = state.create_run(
        repo_id="repo-b",
        mode="delta",
        parent_run_id=parent,
    )

    assert state.request_cancel(parent)
    assert state.cancel_requested(parent)
    assert state.cancel_requested(child_a)
    assert state.cancel_requested(child_b)
    assert {run.id for run in state.list_runs(parent_run_id=parent)} == {
        child_a,
        child_b,
    }
