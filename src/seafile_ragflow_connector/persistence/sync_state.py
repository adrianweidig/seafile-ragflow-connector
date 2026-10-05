from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.models.sync_state import (
    RepoMutationLease,
    SourceSnapshot,
    SourceSnapshotEntry,
    SyncCursor,
    SyncRun,
)


class RepoLeaseBusyError(RuntimeError):
    pass


class RepoLeaseLostError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoLeaseHandle:
    repo_id: str
    owner_id: str
    fence_token: int


@dataclass(frozen=True)
class CursorState:
    repo_id: str
    scope: str
    commit_id: str
    snapshot_id: int
    version: int


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: int
    repo_id: str
    commit_id: str
    scope: str
    state: str
    complete: bool


_active_repo_lease: ContextVar[RepoLeaseHandle | None] = ContextVar(
    "active_repo_mutation_lease",
    default=None,
)


def current_repo_lease(repo_id: str | None = None) -> RepoLeaseHandle | None:
    handle = _active_repo_lease.get()
    if handle is None or (repo_id is not None and handle.repo_id != repo_id):
        return None
    return handle


@contextmanager
def activate_repo_lease(handle: RepoLeaseHandle) -> Iterator[None]:
    token: Token[RepoLeaseHandle | None] = _active_repo_lease.set(handle)
    try:
        yield
    finally:
        _active_repo_lease.reset(token)


class RepoMutationLeaseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def acquire(
        self,
        repo_id: str,
        owner_id: str,
        *,
        lease_seconds: int = 300,
    ) -> RepoLeaseHandle:
        if not repo_id or not owner_id:
            raise ValueError("repo_id and owner_id are required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)
        for _attempt in range(2):
            with self.session_factory() as session:
                token = session.execute(
                    update(RepoMutationLease)
                    .where(RepoMutationLease.repo_id == repo_id)
                    .where(
                        or_(
                            RepoMutationLease.owner_id.is_(None),
                            RepoMutationLease.owner_id == owner_id,
                            RepoMutationLease.expires_at.is_(None),
                            RepoMutationLease.expires_at <= now,
                        )
                    )
                    .values(
                        owner_id=owner_id,
                        fence_token=RepoMutationLease.fence_token + 1,
                        acquired_at=now,
                        heartbeat_at=now,
                        expires_at=expires_at,
                    )
                    .returning(RepoMutationLease.fence_token)
                ).scalar_one_or_none()
                if token is not None:
                    session.commit()
                    return RepoLeaseHandle(repo_id, owner_id, int(token))
                try:
                    lease = RepoMutationLease(
                        repo_id=repo_id,
                        owner_id=owner_id,
                        fence_token=1,
                        acquired_at=now,
                        heartbeat_at=now,
                        expires_at=expires_at,
                    )
                    session.add(lease)
                    session.commit()
                    return RepoLeaseHandle(repo_id, owner_id, 1)
                except IntegrityError:
                    session.rollback()
        raise RepoLeaseBusyError(f"repository mutation lease is already held: {repo_id}")

    def heartbeat(
        self,
        handle: RepoLeaseHandle,
        *,
        lease_seconds: int = 300,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = datetime.now(UTC)
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(RepoMutationLease)
                    .where(RepoMutationLease.repo_id == handle.repo_id)
                    .where(RepoMutationLease.owner_id == handle.owner_id)
                    .where(RepoMutationLease.fence_token == handle.fence_token)
                    .where(RepoMutationLease.expires_at > now)
                    .values(
                        heartbeat_at=now,
                        expires_at=now + timedelta(seconds=lease_seconds),
                    )
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def is_owned(self, handle: RepoLeaseHandle) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            owned = session.scalar(
                select(RepoMutationLease.repo_id)
                .where(RepoMutationLease.repo_id == handle.repo_id)
                .where(RepoMutationLease.owner_id == handle.owner_id)
                .where(RepoMutationLease.fence_token == handle.fence_token)
                .where(RepoMutationLease.expires_at > now)
            )
        return owned is not None

    def assert_owned(self, handle: RepoLeaseHandle) -> None:
        if not self.is_owned(handle):
            raise RepoLeaseLostError(
                f"repository mutation lease was lost: {handle.repo_id}:{handle.fence_token}"
            )

    def release(self, handle: RepoLeaseHandle) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(RepoMutationLease)
                    .where(RepoMutationLease.repo_id == handle.repo_id)
                    .where(RepoMutationLease.owner_id == handle.owner_id)
                    .where(RepoMutationLease.fence_token == handle.fence_token)
                    .values(owner_id=None, heartbeat_at=now, expires_at=now)
                ),
            )
            session.commit()
            return bool(result.rowcount)


class SyncStateStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create_run(
        self,
        *,
        repo_id: str | None,
        mode: str,
        scope: str = "/",
        run_id: str | None = None,
        parent_run_id: str | None = None,
        job_id: int | None = None,
        baseline_commit_id: str | None = None,
        target_commit_id: str | None = None,
        fence_token: int | None = None,
        status: str = "running",
        progress: Mapping[str, Any] | None = None,
    ) -> str:
        resolved_id = run_id or uuid4().hex
        now = datetime.now(UTC)
        with self.session_factory() as session:
            session.add(
                SyncRun(
                    id=resolved_id,
                    parent_run_id=parent_run_id,
                    job_id=job_id,
                    repo_id=repo_id,
                    mode=mode,
                    scope=scope,
                    baseline_commit_id=baseline_commit_id,
                    target_commit_id=target_commit_id,
                    status=status,
                    fence_token=fence_token,
                    progress=dict(progress or {}),
                    started_at=now,
                )
            )
            session.commit()
        return resolved_id

    def get_run(self, run_id: str) -> SyncRun | None:
        with self.session_factory() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                session.expunge(run)
            return run

    def list_runs(
        self,
        *,
        parent_run_id: str | None = None,
        repo_id: str | None = None,
        limit: int = 100,
    ) -> list[SyncRun]:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.session_factory() as session:
            stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit)
            if parent_run_id is not None:
                stmt = stmt.where(SyncRun.parent_run_id == parent_run_id)
            if repo_id is not None:
                stmt = stmt.where(SyncRun.repo_id == repo_id)
            runs = list(session.scalars(stmt).all())
            for run in runs:
                session.expunge(run)
            return runs

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        progress: Mapping[str, Any] | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> bool:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress"] = dict(progress)
        if error_message is not None or status == "succeeded":
            values["error_message"] = error_message
        if finished:
            values["finished_at"] = datetime.now(UTC)
        if not values:
            return False
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(update(SyncRun).where(SyncRun.id == run_id).values(**values)),
            )
            session.commit()
            return bool(result.rowcount)

    def request_cancel(self, run_id: str) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncRun)
                    .where(or_(SyncRun.id == run_id, SyncRun.parent_run_id == run_id))
                    .where(SyncRun.status.in_(["queued", "running", "retrying"]))
                    .values(cancel_requested_at=now)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def attach_job(self, run_id: str, job_id: int) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncRun).where(SyncRun.id == run_id).values(job_id=job_id)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def cancel_requested(self, run_id: str) -> bool:
        with self.session_factory() as session:
            value = session.scalar(
                select(SyncRun.cancel_requested_at).where(SyncRun.id == run_id)
            )
        return value is not None

    def replace_snapshot(
        self,
        *,
        repo_id: str,
        commit_id: str,
        scope: str,
        entries: Sequence[Mapping[str, Any]],
        complete: bool = True,
    ) -> SnapshotRecord:
        with self.session_factory() as session:
            snapshot = session.scalar(
                select(SourceSnapshot)
                .where(SourceSnapshot.repo_id == repo_id)
                .where(SourceSnapshot.commit_id == commit_id)
                .where(SourceSnapshot.scope == scope)
                .with_for_update()
            )
            if snapshot is None:
                snapshot = SourceSnapshot(
                    repo_id=repo_id,
                    commit_id=commit_id,
                    scope=scope,
                )
                session.add(snapshot)
                session.flush()
            elif snapshot.state == "confirmed" and snapshot.complete:
                return SnapshotRecord(
                    int(snapshot.id),
                    snapshot.repo_id,
                    snapshot.commit_id,
                    snapshot.scope,
                    snapshot.state,
                    snapshot.complete,
                )
            else:
                session.execute(
                    delete(SourceSnapshotEntry).where(
                        SourceSnapshotEntry.snapshot_id == snapshot.id
                    )
                )
            session.add_all(
                [
                    SourceSnapshotEntry(
                        snapshot_id=snapshot.id,
                        path=str(entry["path"]),
                        normalized_path=str(entry["normalized_path"]),
                        object_id=cast(str | None, entry.get("object_id")),
                        size=cast(int | None, entry.get("size")),
                        mtime=cast(int | None, entry.get("mtime")),
                        is_directory=bool(entry.get("is_directory", False)),
                        raw=dict(cast(Mapping[str, Any], entry.get("raw") or {})),
                    )
                    for entry in entries
                ]
            )
            snapshot.state = "staging"
            snapshot.complete = complete
            snapshot.entry_count = len(entries)
            session.commit()
            return SnapshotRecord(
                int(snapshot.id),
                snapshot.repo_id,
                snapshot.commit_id,
                snapshot.scope,
                snapshot.state,
                snapshot.complete,
            )

    def snapshot_entries(self, snapshot_id: int) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(SourceSnapshotEntry)
                .where(SourceSnapshotEntry.snapshot_id == snapshot_id)
                .order_by(SourceSnapshotEntry.normalized_path)
            ).all()
        return [
            {
                "path": row.path,
                "normalized_path": row.normalized_path,
                "object_id": row.object_id,
                "size": row.size,
                "mtime": row.mtime,
                "is_directory": row.is_directory,
                "raw": dict(row.raw or {}),
            }
            for row in rows
        ]

    def get_snapshot(self, snapshot_id: int) -> SnapshotRecord | None:
        with self.session_factory() as session:
            snapshot = session.get(SourceSnapshot, snapshot_id)
            if snapshot is None:
                return None
            return SnapshotRecord(
                int(snapshot.id),
                snapshot.repo_id,
                snapshot.commit_id,
                snapshot.scope,
                snapshot.state,
                snapshot.complete,
            )

    def get_cursor(self, repo_id: str, scope: str = "/") -> CursorState | None:
        with self.session_factory() as session:
            cursor = session.get(SyncCursor, (repo_id, scope))
            if cursor is None:
                return None
            return CursorState(
                cursor.repo_id,
                cursor.scope,
                cursor.commit_id,
                int(cursor.snapshot_id),
                cursor.version,
            )

    def advance_cursor(
        self,
        *,
        repo_id: str,
        scope: str,
        expected_commit_id: str | None,
        target_commit_id: str,
        snapshot_id: int,
    ) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            cursor = session.scalar(
                select(SyncCursor)
                .where(SyncCursor.repo_id == repo_id)
                .where(SyncCursor.scope == scope)
                .with_for_update()
            )
            if cursor is None:
                if expected_commit_id is not None:
                    return False
                cursor = SyncCursor(
                    repo_id=repo_id,
                    scope=scope,
                    commit_id=target_commit_id,
                    snapshot_id=snapshot_id,
                    version=1,
                )
                session.add(cursor)
            else:
                if cursor.commit_id != expected_commit_id:
                    return False
                cursor.commit_id = target_commit_id
                cursor.snapshot_id = snapshot_id
                cursor.version += 1
            snapshot = session.get(SourceSnapshot, snapshot_id)
            if snapshot is None or not snapshot.complete:
                raise ValueError("cannot advance cursor to an incomplete snapshot")
            snapshot.state = "confirmed"
            snapshot.confirmed_at = now
            session.commit()
        self.prune_snapshots(repo_id=repo_id, scope=scope)
        return True

    def prune_snapshots(
        self,
        *,
        repo_id: str,
        scope: str,
        keep_recent: int = 2,
        batch_size: int = 100,
    ) -> int:
        if keep_recent < 1:
            raise ValueError("keep_recent must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        active_statuses = ["queued", "running", "retrying"]
        with self.session_factory() as session:
            protected_ids = {
                int(snapshot_id)
                for snapshot_id in session.scalars(select(SyncCursor.snapshot_id)).all()
            }
            protected_ids.update(
                int(snapshot_id)
                for snapshot_id in session.scalars(
                    select(SourceSnapshot.id)
                    .where(SourceSnapshot.repo_id == repo_id)
                    .where(SourceSnapshot.scope == scope)
                    .order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc())
                    .limit(keep_recent)
                ).all()
            )
            latest_confirmed = session.scalar(
                select(SourceSnapshot.id)
                .where(SourceSnapshot.repo_id == repo_id)
                .where(SourceSnapshot.scope == scope)
                .where(SourceSnapshot.state == "confirmed")
                .order_by(SourceSnapshot.confirmed_at.desc(), SourceSnapshot.id.desc())
                .limit(1)
            )
            if latest_confirmed is not None:
                protected_ids.add(int(latest_confirmed))
            active_commits: set[str] = set()
            for baseline_commit_id, target_commit_id in session.execute(
                select(SyncRun.baseline_commit_id, SyncRun.target_commit_id)
                .where(SyncRun.repo_id == repo_id)
                .where(SyncRun.scope == scope)
                .where(SyncRun.status.in_(active_statuses))
            ):
                active_commits.update(
                    str(commit_id)
                    for commit_id in (baseline_commit_id, target_commit_id)
                    if commit_id
                )
            if active_commits:
                protected_ids.update(
                    int(snapshot_id)
                    for snapshot_id in session.scalars(
                        select(SourceSnapshot.id)
                        .where(SourceSnapshot.repo_id == repo_id)
                        .where(SourceSnapshot.scope == scope)
                        .where(SourceSnapshot.commit_id.in_(active_commits))
                    ).all()
                )
            for payload in session.scalars(
                select(SyncJob.payload)
                .where(SyncJob.repo_id == repo_id)
                .where(SyncJob.status.in_(active_statuses))
            ):
                if not isinstance(payload, Mapping):
                    continue
                snapshot_id = payload.get("snapshot_id")
                try:
                    if snapshot_id is not None:
                        protected_ids.add(int(snapshot_id))
                except (TypeError, ValueError):
                    continue
            candidate_stmt = (
                select(SourceSnapshot.id)
                .where(SourceSnapshot.repo_id == repo_id)
                .where(SourceSnapshot.scope == scope)
                .order_by(SourceSnapshot.created_at.asc(), SourceSnapshot.id.asc())
                .limit(batch_size)
            )
            if protected_ids:
                candidate_stmt = candidate_stmt.where(
                    SourceSnapshot.id.not_in(protected_ids)
                )
            candidate_ids = [
                int(snapshot_id) for snapshot_id in session.scalars(candidate_stmt).all()
            ]
            if not candidate_ids:
                return 0
            session.execute(
                delete(SourceSnapshotEntry).where(
                    SourceSnapshotEntry.snapshot_id.in_(candidate_ids)
                )
            )
            session.execute(
                delete(SourceSnapshot).where(SourceSnapshot.id.in_(candidate_ids))
            )
            session.commit()
            return len(candidate_ids)
