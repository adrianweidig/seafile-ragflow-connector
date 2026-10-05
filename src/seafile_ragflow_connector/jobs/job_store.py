from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.app.metrics import (
    jobs_deduplicated_total,
    jobs_oldest_queued_age_seconds,
    jobs_queued,
    jobs_running,
)
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.models.admin_control import (
    LibraryControlState,
    WorkflowControlState,
)
from seafile_ragflow_connector.persistence.models.dashboard import DashboardSyncRun
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import (
    CleanupOutbox,
    SyncRun,
    WorkflowCleanupSubscription,
    WorkflowJobSubscription,
)
from seafile_ragflow_connector.utils.retry import exponential_backoff_seconds

ACTIVE_JOB_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.RETRYING.value,
    JobStatus.RUNNING.value,
)
ACTIVE_JOB_INDEX_PREDICATE = text("status IN ('queued', 'retrying', 'running')")


def _aggregate_workflow_status(statuses: list[str]) -> str:
    if not statuses:
        return "queued"
    if any(status == JobStatus.RUNNING.value for status in statuses):
        return "running"
    if any(status == JobStatus.RETRYING.value for status in statuses):
        return "retrying"
    if any(status == JobStatus.QUEUED.value for status in statuses):
        return "queued"
    if any(status == JobStatus.DEAD.value for status in statuses):
        return "failed"
    if all(status == JobStatus.CANCELLED.value for status in statuses):
        return "cancelled"
    if all(
        status in {JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value}
        for status in statuses
    ):
        return "succeeded"
    return "queued"


@dataclass(frozen=True)
class EnqueueResult:
    job_id: int
    deduplicated: bool


@dataclass(frozen=True)
class StaleJobRecoveryResult:
    retrying: int = 0
    dead: int = 0

    @property
    def total(self) -> int:
        return self.retrying + self.dead


class JobStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        default_max_attempts: int = 5,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
    ) -> None:
        if default_max_attempts <= 0:
            raise ValueError("default_max_attempts must be positive")
        if retry_base_seconds <= 0 or retry_max_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if retry_base_seconds > retry_max_seconds:
            raise ValueError("retry_base_seconds must not exceed retry_max_seconds")
        self.session_factory = session_factory
        self.default_max_attempts = default_max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    def enqueue(self, spec: JobSpec) -> int:
        return self.enqueue_with_result(spec).job_id

    def enqueue_with_result(self, spec: JobSpec) -> EnqueueResult:
        with self.session_factory() as session:
            result = self._enqueue_with_result_in_session(session, spec)
            self._refresh_queue_metrics(session)
            session.commit()
        if result.deduplicated:
            jobs_deduplicated_total.inc()
        return result

    def _enqueue_with_result_in_session(
        self,
        session: Session,
        spec: JobSpec,
    ) -> EnqueueResult:
        max_attempts = (
            self.default_max_attempts if spec.max_attempts is None else spec.max_attempts
        )
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        values = {
            "job_type": spec.job_type.value,
            "repo_id": spec.repo_id,
            "file_path": spec.file_path,
            "dedup_key": spec.dedup_key(),
            "payload": spec.payload,
            "status": JobStatus.QUEUED.value,
            "priority": spec.resolved_priority(),
            "max_attempts": max_attempts,
        }
        dialect_name = session.get_bind().dialect.name
        if dialect_name not in {"postgresql", "sqlite"}:
            job = SyncJob(**values)
            session.add(job)
            session.flush()
            return EnqueueResult(int(job.id), False)
        insert_factory = postgresql_insert if dialect_name == "postgresql" else sqlite_insert
        for _attempt in range(2):
            stmt = (
                insert_factory(SyncJob)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=[SyncJob.dedup_key],
                    index_where=ACTIVE_JOB_INDEX_PREDICATE,
                )
                .returning(SyncJob.id)
            )
            job_id = session.execute(stmt).scalar_one_or_none()
            if job_id is not None:
                return EnqueueResult(int(job_id), False)
            existing = session.scalar(
                select(SyncJob)
                .where(SyncJob.dedup_key == spec.dedup_key())
                .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                .order_by(SyncJob.id.asc())
                .limit(1)
            )
            if existing is not None:
                existing.priority = min(existing.priority, spec.resolved_priority())
                existing.max_attempts = max(existing.max_attempts, max_attempts)
                return EnqueueResult(int(existing.id), True)
        raise RuntimeError("active job changed repeatedly while enqueueing")

    def acquire_next(self, worker_id: str) -> SyncJob | None:
        with self.session_factory() as session:
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            now = datetime.now(UTC)
            workflow_control = session.get(
                WorkflowControlState,
                1,
                with_for_update=True,
            )
            if workflow_control is not None and workflow_control.queue_paused:
                session.commit()
                return None
            blocked_library = exists(
                select(LibraryControlState.repo_id).where(
                    LibraryControlState.repo_id == SyncJob.repo_id,
                    or_(
                        LibraryControlState.enabled.is_(False),
                        LibraryControlState.paused.is_(True),
                    ),
                )
            )
            stmt: Select[tuple[int, str | None]] = (
                select(SyncJob.id, SyncJob.repo_id)
                .where(SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]))
                .where(SyncJob.cancel_requested_at.is_(None))
                .where(SyncJob.pause_requested_at.is_(None))
                .where(or_(SyncJob.repo_id.is_(None), ~blocked_library))
                .where(SyncJob.run_after <= now)
                .order_by(SyncJob.priority.asc(), SyncJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            candidate = session.execute(stmt).one_or_none()
            if candidate is None:
                return None
            job_id, repo_id = candidate
            if repo_id is not None:
                library_control = session.get(
                    LibraryControlState,
                    repo_id,
                    with_for_update=True,
                )
                if library_control is not None and (
                    not library_control.enabled or library_control.paused
                ):
                    session.commit()
                    return None
            job = session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .where(
                    SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value])
                )
                .where(SyncJob.cancel_requested_at.is_(None))
                .where(SyncJob.pause_requested_at.is_(None))
                .where(or_(SyncJob.repo_id.is_(None), ~blocked_library))
                .where(SyncJob.run_after <= now)
                .values(
                    status=JobStatus.RUNNING.value,
                    locked_by=worker_id,
                    locked_at=now,
                    attempts=SyncJob.attempts + 1,
                )
                .execution_options(synchronize_session=False)
                .returning(SyncJob)
            ).scalar_one_or_none()
            if job is None:
                session.rollback()
                return None
            self._refresh_queue_metrics(session)
            session.commit()
            session.refresh(job)
            session.expunge(job)
            return job

    def heartbeat(self, job_id: int, *, worker_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .values(locked_at=datetime.now(UTC))
                    .execution_options(synchronize_session=False)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def get(self, job_id: int) -> SyncJob | None:
        with self.session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is not None:
                session.expunge(job)
            return job

    def list_jobs(
        self,
        *,
        statuses: tuple[JobStatus, ...] | None = None,
        repo_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[SyncJob]:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.session_factory() as session:
            stmt = select(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit)
            if statuses:
                stmt = stmt.where(SyncJob.status.in_([status.value for status in statuses]))
            if repo_id is not None:
                stmt = stmt.where(SyncJob.repo_id == repo_id)
            if run_id is not None:
                stmt = stmt.where(SyncJob.run_id == run_id)
            jobs = list(session.scalars(stmt).all())
            for job in jobs:
                session.expunge(job)
            return jobs

    def bind_run(self, job_id: int, run_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .values(run_id=run_id)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def bind_run_if_unbound(self, job_id: int, run_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(or_(SyncJob.run_id.is_(None), SyncJob.run_id == run_id))
                    .values(run_id=run_id)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def subscribe_workflow(
        self,
        workflow_run_id: str,
        job_id: int,
        *,
        is_root: bool = False,
        owns_job: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            subscription = session.get(
                WorkflowJobSubscription,
                (workflow_run_id, job_id),
                with_for_update=True,
            )
            job = session.get(SyncJob, job_id, with_for_update=True)
            if job is None:
                raise ValueError(f"job {job_id} does not exist")
            cancelled = parent is not None and self._workflow_is_terminal(parent)
            if subscription is None:
                subscription = WorkflowJobSubscription(
                    workflow_run_id=workflow_run_id,
                    job_id=job_id,
                    is_root=is_root,
                    owns_job=owns_job,
                    cancelled_at=now if cancelled else None,
                )
                session.add(subscription)
            else:
                subscription.is_root = subscription.is_root or is_root
                subscription.owns_job = subscription.owns_job or owns_job
                subscription.cancelled_at = now if cancelled else None
            session.flush()
            self._reconcile_workflow_job(session, job, now=now)
            self._refresh_queue_metrics(session)
            session.commit()

    def inherit_workflow_subscriptions(
        self,
        parent_job_id: int,
        child_job_id: int,
        *,
        child_created: bool,
    ) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow_ids = sorted(
                set(
                    session.scalars(
                        select(WorkflowJobSubscription.workflow_run_id).where(
                            WorkflowJobSubscription.job_id == parent_job_id
                        )
                    ).all()
                )
            )
            if not workflow_ids:
                return
            workflows = {
                workflow.id: workflow
                for workflow in session.scalars(
                    select(SyncRun)
                    .where(SyncRun.id.in_(workflow_ids))
                    .order_by(SyncRun.id)
                    .with_for_update()
                ).all()
            }
            subscriptions = list(
                session.scalars(
                    select(WorkflowJobSubscription)
                    .where(WorkflowJobSubscription.job_id == parent_job_id)
                    .where(
                        WorkflowJobSubscription.workflow_run_id.in_(workflow_ids)
                    )
                    .order_by(WorkflowJobSubscription.workflow_run_id)
                    .with_for_update()
                ).all()
            )
            existing = {
                subscription.workflow_run_id: subscription
                for subscription in session.scalars(
                    select(WorkflowJobSubscription)
                    .where(WorkflowJobSubscription.job_id == child_job_id)
                    .where(
                        WorkflowJobSubscription.workflow_run_id.in_(workflow_ids)
                    )
                    .order_by(WorkflowJobSubscription.workflow_run_id)
                    .with_for_update()
                ).all()
            }
            child = session.get(SyncJob, child_job_id, with_for_update=True)
            if child is None:
                raise ValueError(f"job {child_job_id} does not exist")
            for source in subscriptions:
                workflow = workflows.get(source.workflow_run_id)
                cancelled = source.cancelled_at is not None or (
                    workflow is not None and self._workflow_is_terminal(workflow)
                )
                subscription = existing.get(source.workflow_run_id)
                if subscription is None:
                    subscription = WorkflowJobSubscription(
                        workflow_run_id=source.workflow_run_id,
                        job_id=child_job_id,
                        owns_job=child_created and bool(source.owns_job),
                    )
                    session.add(subscription)
                else:
                    subscription.owns_job = subscription.owns_job or (
                        child_created and bool(source.owns_job)
                    )
                subscription.cancelled_at = now if cancelled else None
            session.flush()
            self._reconcile_workflow_job(session, child, now=now)
            self._refresh_queue_metrics(session)
            session.commit()

    def subscribe_cleanup_from_job(self, parent_job_id: int, outbox_id: int) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            workflow_ids = sorted(
                set(
                    session.scalars(
                        select(WorkflowJobSubscription.workflow_run_id).where(
                            WorkflowJobSubscription.job_id == parent_job_id
                        )
                    ).all()
                )
            )
            if not workflow_ids:
                return
            workflows = {
                workflow.id: workflow
                for workflow in session.scalars(
                    select(SyncRun)
                    .where(SyncRun.id.in_(workflow_ids))
                    .order_by(SyncRun.id)
                    .with_for_update()
                ).all()
            }
            sources = {
                subscription.workflow_run_id: subscription
                for subscription in session.scalars(
                    select(WorkflowJobSubscription)
                    .where(WorkflowJobSubscription.job_id == parent_job_id)
                    .where(
                        WorkflowJobSubscription.workflow_run_id.in_(workflow_ids)
                    )
                    .order_by(WorkflowJobSubscription.workflow_run_id)
                    .with_for_update()
                ).all()
            }
            existing = {
                subscription.workflow_run_id: subscription
                for subscription in session.scalars(
                    select(WorkflowCleanupSubscription)
                    .where(WorkflowCleanupSubscription.outbox_id == outbox_id)
                    .where(
                        WorkflowCleanupSubscription.workflow_run_id.in_(workflow_ids)
                    )
                    .order_by(WorkflowCleanupSubscription.workflow_run_id)
                    .with_for_update()
                ).all()
            }
            for workflow_run_id in workflow_ids:
                subscription = existing.get(workflow_run_id)
                if subscription is None:
                    subscription = WorkflowCleanupSubscription(
                        workflow_run_id=workflow_run_id,
                        outbox_id=outbox_id,
                    )
                    session.add(subscription)
                source = sources[workflow_run_id]
                workflow = workflows.get(workflow_run_id)
                cancelled = source.cancelled_at is not None or (
                    workflow is not None and self._workflow_is_terminal(workflow)
                )
                subscription.cancelled_at = now if cancelled else None
            session.commit()

    def workflow_jobs(self, workflow_run_id: str) -> list[SyncJob]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .join(
                        WorkflowJobSubscription,
                        WorkflowJobSubscription.job_id == SyncJob.id,
                    )
                    .where(
                        WorkflowJobSubscription.workflow_run_id == workflow_run_id
                    )
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                    .order_by(SyncJob.id)
                ).all()
            )
            for job in jobs:
                session.expunge(job)
            return jobs

    def workflow_cleanup_rows(self, workflow_run_id: str) -> list[CleanupOutbox]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(CleanupOutbox)
                    .join(
                        WorkflowCleanupSubscription,
                        WorkflowCleanupSubscription.outbox_id == CleanupOutbox.id,
                    )
                    .where(
                        WorkflowCleanupSubscription.workflow_run_id == workflow_run_id
                    )
                    .where(WorkflowCleanupSubscription.cancelled_at.is_(None))
                    .order_by(CleanupOutbox.id)
                ).all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def cancel_workflow_subscription(
        self,
        workflow_run_id: str,
        *,
        administrative_stop: bool = False,
    ) -> list[int]:
        now = datetime.now(UTC)
        workflow_status = "stopped" if administrative_stop else "cancelled"
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            was_paused = bool(
                parent is not None and (parent.progress or {}).get("admin_paused")
            )
            subscriptions = list(
                session.scalars(
                    select(WorkflowJobSubscription)
                    .where(
                        WorkflowJobSubscription.workflow_run_id == workflow_run_id
                    )
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                    .order_by(WorkflowJobSubscription.job_id)
                    .with_for_update()
                ).all()
            )
            job_ids = [int(subscription.job_id) for subscription in subscriptions]
            cleanup_subscriptions = list(
                session.scalars(
                    select(WorkflowCleanupSubscription)
                    .where(
                        WorkflowCleanupSubscription.workflow_run_id
                        == workflow_run_id
                    )
                    .where(WorkflowCleanupSubscription.cancelled_at.is_(None))
                    .order_by(WorkflowCleanupSubscription.outbox_id)
                    .with_for_update()
                ).all()
            )
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.id.in_(sorted(set(job_ids))))
                    .order_by(SyncJob.id)
                    .with_for_update()
                ).all()
            )
            for subscription in subscriptions:
                subscription.cancelled_at = now
            for cleanup_subscription in cleanup_subscriptions:
                cleanup_subscription.cancelled_at = now
            if parent is not None:
                progress = dict(parent.progress or {})
                progress.pop("admin_paused", None)
                if administrative_stop:
                    progress["admin_stopped"] = True
                else:
                    progress.pop("admin_stopped", None)
                parent.progress = progress
            self._set_workflow_parent_status(
                session,
                workflow_run_id,
                workflow_status,
                terminal=True,
                error_count=0,
                total=len(job_ids),
            )
            session.flush()
            cancelled_jobs = [
                int(job.id)
                for job in jobs
                if self._reconcile_workflow_job(
                    session,
                    job,
                    now=now,
                    clear_workflow_pause=was_paused,
                )
            ]
            self._refresh_queue_metrics(session)
            session.commit()
        return cancelled_jobs

    def stop_workflow_subscription(self, workflow_run_id: str) -> list[int]:
        return self.cancel_workflow_subscription(
            workflow_run_id,
            administrative_stop=True,
        )

    def request_workflow_pause(self, workflow_run_id: str) -> list[int]:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            if parent is None:
                return []
            parent.progress = {
                **dict(parent.progress or {}),
                "admin_paused": True,
                "admin_stopped": False,
            }
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .join(
                        WorkflowJobSubscription,
                        WorkflowJobSubscription.job_id == SyncJob.id,
                    )
                    .where(WorkflowJobSubscription.workflow_run_id == workflow_run_id)
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .order_by(SyncJob.id)
                    .with_for_update()
                ).all()
            )
            session.flush()
            paused_job_ids: list[int] = []
            for job in jobs:
                self._reconcile_workflow_job(
                    session,
                    job,
                    now=now,
                    preserve_existing_pause=True,
                )
                if job.pause_requested_at is not None and self._job_has_pause_policy(
                    session,
                    job,
                    ignore_library=True,
                    ignore_global=True,
                ):
                    paused_job_ids.append(int(job.id))
            self._refresh_queue_metrics(session)
            session.commit()
        self.refresh_workflow_parent(workflow_run_id)
        return paused_job_ids

    def resume_workflow_pause(self, workflow_run_id: str) -> list[int]:
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            if parent is None:
                return []
            progress = dict(parent.progress or {})
            progress.pop("admin_paused", None)
            progress.pop("admin_stopped", None)
            parent.progress = progress
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .join(
                        WorkflowJobSubscription,
                        WorkflowJobSubscription.job_id == SyncJob.id,
                    )
                    .where(
                        WorkflowJobSubscription.workflow_run_id == workflow_run_id
                    )
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .order_by(SyncJob.id)
                    .with_for_update()
                ).all()
            )
            session.flush()
            changed: list[int] = []
            for job in jobs:
                was_paused = job.pause_requested_at is not None
                self._reconcile_workflow_job(
                    session,
                    job,
                    now=datetime.now(UTC),
                    clear_workflow_pause=True,
                )
                if was_paused and job.pause_requested_at is None:
                    changed.append(int(job.id))
            self._refresh_queue_metrics(session)
            session.commit()
        self.refresh_workflow_parent(workflow_run_id)
        return changed

    def resume_workflow_subscription(self, workflow_run_id: str) -> list[int]:
        now = datetime.now(UTC)
        deduplicated_cleanup_jobs = 0
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            subscriptions = list(
                session.scalars(
                    select(WorkflowJobSubscription)
                    .where(
                        WorkflowJobSubscription.workflow_run_id == workflow_run_id
                    )
                    .order_by(WorkflowJobSubscription.job_id)
                    .with_for_update()
                ).all()
            )
            cleanup_subscriptions = list(
                session.scalars(
                    select(WorkflowCleanupSubscription)
                    .where(
                        WorkflowCleanupSubscription.workflow_run_id
                        == workflow_run_id
                    )
                    .order_by(WorkflowCleanupSubscription.outbox_id)
                    .with_for_update()
                ).all()
            )
            outbox_ids = sorted(
                {int(subscription.outbox_id) for subscription in cleanup_subscriptions}
            )
            cleanup_rows = list(
                session.scalars(
                    select(CleanupOutbox)
                    .where(CleanupOutbox.id.in_(outbox_ids))
                    .order_by(CleanupOutbox.id)
                    .with_for_update()
                ).all()
            )
            dead_cleanup_rows = [row for row in cleanup_rows if row.status == "dead"]
            repo_ids = sorted({row.repo_id for row in dead_cleanup_rows})
            controls = {
                control.repo_id: control
                for control in session.scalars(
                    select(LibraryControlState)
                    .where(LibraryControlState.repo_id.in_(repo_ids))
                    .order_by(LibraryControlState.repo_id)
                    .with_for_update()
                ).all()
            }
            libraries = {
                library.repo_id: library
                for library in session.scalars(
                    select(Library)
                    .where(Library.repo_id.in_(repo_ids))
                    .order_by(Library.repo_id)
                    .with_for_update()
                ).all()
            }
            for row in dead_cleanup_rows:
                control = controls.get(row.repo_id)
                if control is not None and (not control.enabled or control.paused):
                    raise ValueError(
                        f"cleanup retry for library {row.repo_id!r} is blocked"
                    )
                library = libraries.get(row.repo_id)
                if (
                    row.target_type == "ragflow_dataset"
                    and library is not None
                    and library.deletion_state == "active"
                ):
                    raise ValueError(
                        "active source library blocks RAGFlow dataset cleanup retry"
                    )
            for subscription in subscriptions:
                subscription.cancelled_at = None
            for cleanup_subscription in cleanup_subscriptions:
                cleanup_subscription.cancelled_at = None
            for row in dead_cleanup_rows:
                row.status = "pending"
                row.attempts = 0
                row.run_after = now
                row.error_message = None
                row.completed_at = None
                library = libraries.get(row.repo_id)
                if library is not None and row.target_type == "ragflow_dataset":
                    library.status = "confirmed_for_deletion"
                    library.deletion_state = "confirmed"
                    library.last_error = None
            if parent is not None:
                progress = dict(parent.progress or {})
                progress.pop("admin_paused", None)
                progress.pop("admin_stopped", None)
                parent.progress = progress
            self._set_workflow_parent_status(
                session,
                workflow_run_id,
                "queued",
                terminal=False,
                error_count=0,
                total=len(subscriptions),
            )
            session.flush()
            cleanup_job_ids: list[int] = []
            for repo_id in repo_ids:
                enqueue_result = self._enqueue_with_result_in_session(
                    session,
                    JobSpec(
                        JobType.PROCESS_CLEANUP_OUTBOX,
                        repo_id=repo_id,
                        payload={"workflow_run_id": workflow_run_id},
                    ),
                )
                deduplicated_cleanup_jobs += int(enqueue_result.deduplicated)
                cleanup_job_ids.append(enqueue_result.job_id)
                cleanup_job = session.get(
                    SyncJob,
                    enqueue_result.job_id,
                    with_for_update=True,
                )
                if cleanup_job is None:
                    raise RuntimeError("cleanup retry job disappeared while scheduling")
                if not enqueue_result.deduplicated:
                    cleanup_job.run_id = workflow_run_id
                cleanup_job_subscription = session.get(
                    WorkflowJobSubscription,
                    (workflow_run_id, enqueue_result.job_id),
                    with_for_update=True,
                )
                if cleanup_job_subscription is None:
                    cleanup_job_subscription = WorkflowJobSubscription(
                        workflow_run_id=workflow_run_id,
                        job_id=enqueue_result.job_id,
                        owns_job=not enqueue_result.deduplicated,
                    )
                    session.add(cleanup_job_subscription)
                else:
                    cleanup_job_subscription.cancelled_at = None
                    cleanup_job_subscription.owns_job = (
                        cleanup_job_subscription.owns_job
                        or not enqueue_result.deduplicated
                    )
                session.flush()
                self._reconcile_workflow_job(session, cleanup_job, now=now)
            resumed_job_ids = list(
                dict.fromkeys(
                    [int(subscription.job_id) for subscription in subscriptions]
                    + cleanup_job_ids
                )
            )
            self._set_workflow_parent_status(
                session,
                workflow_run_id,
                "queued",
                terminal=False,
                error_count=0,
                total=len(resumed_job_ids),
            )
            self._refresh_queue_metrics(session)
            session.commit()
        if deduplicated_cleanup_jobs:
            jobs_deduplicated_total.inc(deduplicated_cleanup_jobs)
        return resumed_job_ids

    def refresh_workflow_parents_for_job(self, job_id: int) -> None:
        with self.session_factory() as session:
            workflow_ids = list(
                session.scalars(
                    select(WorkflowJobSubscription.workflow_run_id)
                    .where(WorkflowJobSubscription.job_id == job_id)
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                ).all()
            )
        for workflow_run_id in workflow_ids:
            self.refresh_workflow_parent(workflow_run_id)

    def refresh_workflow_parents_for_cleanup(self, outbox_id: int) -> None:
        with self.session_factory() as session:
            workflow_ids = list(
                session.scalars(
                    select(WorkflowCleanupSubscription.workflow_run_id)
                    .where(WorkflowCleanupSubscription.outbox_id == outbox_id)
                    .where(WorkflowCleanupSubscription.cancelled_at.is_(None))
                ).all()
            )
        for workflow_run_id in workflow_ids:
            self.refresh_workflow_parent(workflow_run_id)

    def refresh_workflow_parents_for_repo_cleanup(self, repo_id: str) -> None:
        with self.session_factory() as session:
            workflow_ids = list(
                session.scalars(
                    select(WorkflowCleanupSubscription.workflow_run_id)
                    .join(
                        CleanupOutbox,
                        CleanupOutbox.id == WorkflowCleanupSubscription.outbox_id,
                    )
                    .where(CleanupOutbox.repo_id == repo_id)
                    .where(WorkflowCleanupSubscription.cancelled_at.is_(None))
                    .distinct()
                ).all()
            )
        for workflow_run_id in workflow_ids:
            self.refresh_workflow_parent(workflow_run_id)

    def refresh_workflow_parent(self, workflow_run_id: str) -> str:
        with self.session_factory() as session:
            parent = session.get(SyncRun, workflow_run_id, with_for_update=True)
            if parent is None:
                return "queued"
            subscriptions = list(
                session.scalars(
                    select(WorkflowJobSubscription)
                    .where(
                        WorkflowJobSubscription.workflow_run_id == workflow_run_id
                    )
                    .where(WorkflowJobSubscription.cancelled_at.is_(None))
                    .order_by(WorkflowJobSubscription.job_id)
                    .with_for_update()
                ).all()
            )
            cleanup_subscriptions = list(
                session.scalars(
                    select(WorkflowCleanupSubscription)
                    .where(
                        WorkflowCleanupSubscription.workflow_run_id
                        == workflow_run_id
                    )
                    .where(WorkflowCleanupSubscription.cancelled_at.is_(None))
                    .order_by(WorkflowCleanupSubscription.outbox_id)
                    .with_for_update()
                ).all()
            )
            job_ids = sorted({int(subscription.job_id) for subscription in subscriptions})
            outbox_ids = sorted(
                {
                    int(subscription.outbox_id)
                    for subscription in cleanup_subscriptions
                }
            )
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.id.in_(job_ids))
                    .order_by(SyncJob.id)
                    .with_for_update()
                ).all()
            )
            cleanup_rows = list(
                session.scalars(
                    select(CleanupOutbox)
                    .where(CleanupOutbox.id.in_(outbox_ids))
                    .order_by(CleanupOutbox.id)
                    .with_for_update()
                ).all()
            )
            statuses = [str(job.status) for job in jobs]
            statuses.extend(
                JobStatus.DEAD.value
                if row.status == "dead"
                else (
                    JobStatus.SUCCEEDED.value
                    if row.status in {"completed", "cancelled", "superseded"}
                    else JobStatus.RETRYING.value
                )
                for row in cleanup_rows
            )
            progress = dict(parent.progress or {})
            if bool(progress.get("admin_stopped")) or parent.status == "stopped":
                status = "stopped"
            elif parent.status == "cancelled":
                status = "cancelled"
            elif bool(progress.get("admin_paused")):
                status = "paused"
            elif statuses:
                status = _aggregate_workflow_status(statuses)
            elif parent.status in {"succeeded", "failed", "cancelled", "stopped"}:
                status = parent.status
            else:
                status = "queued"
            terminal = status in {"succeeded", "failed", "cancelled", "stopped"}
            error_count = sum(value == JobStatus.DEAD.value for value in statuses)
            completed = sum(
                value
                in {
                    JobStatus.SUCCEEDED.value,
                    JobStatus.CANCELLED.value,
                    JobStatus.DEAD.value,
                }
                for value in statuses
            )
            self._set_workflow_parent_status(
                session,
                workflow_run_id,
                status,
                terminal=terminal,
                error_count=error_count,
                total=len(statuses),
                completed=completed,
            )
            session.commit()
        return status

    @staticmethod
    def _set_workflow_parent_status(
        session: Session,
        workflow_run_id: str,
        status: str,
        *,
        terminal: bool,
        error_count: int,
        total: int,
        completed: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        run = session.get(SyncRun, workflow_run_id)
        admin_paused = False
        admin_stopped = False
        if run is not None:
            run.status = status
            run.progress = {
                **dict(run.progress or {}),
                "completed": (
                    total if terminal else int(completed or 0)
                ),
                "total": total,
            }
            run.error_message = "workflow child failed" if status == "failed" else None
            run.finished_at = (run.finished_at or now) if terminal else None
            admin_paused = bool((run.progress or {}).get("admin_paused"))
            admin_stopped = bool((run.progress or {}).get("admin_stopped"))
        dashboard_run = session.get(DashboardSyncRun, workflow_run_id)
        if dashboard_run is not None:
            dashboard_run.status = status
            dashboard_run.objects_checked = total
            dashboard_run.errors_count = error_count
            dashboard_run.summary = f"Workflow {status}: {total} Arbeitsschritte"
            dashboard_run.details = {
                **dict(dashboard_run.details or {}),
                "admin_paused": admin_paused,
                "admin_stopped": admin_stopped,
            }
            dashboard_run.ended_at = (
                dashboard_run.ended_at or now if terminal else None
            )
            if terminal:
                started_at = dashboard_run.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=UTC)
                ended_at = dashboard_run.ended_at or now
                if ended_at.tzinfo is None:
                    ended_at = ended_at.replace(tzinfo=UTC)
                dashboard_run.duration_ms = int(
                    (ended_at - started_at).total_seconds() * 1000
                )
            else:
                dashboard_run.duration_ms = None

    def set_fence_token(self, job_id: int, *, worker_id: str, fence_token: int) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .values(fence_token=fence_token)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    @staticmethod
    def _request_cancel_locked(
        job: SyncJob,
        *,
        now: datetime,
        finalize_running: bool = False,
    ) -> bool:
        if job.status not in ACTIVE_JOB_STATUSES:
            return False
        if job.status in {JobStatus.QUEUED.value, JobStatus.RETRYING.value} or (
            finalize_running and job.status == JobStatus.RUNNING.value
        ):
            job.status = JobStatus.CANCELLED.value
            job.locked_by = None
            job.locked_at = None
            job.fence_token = None
        job.cancel_requested_at = job.cancel_requested_at or now
        job.pause_requested_at = None
        return True

    def request_cancel(self, job_id: int) -> bool:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .with_for_update()
            )
            if job is None or not self._request_cancel_locked(job, now=now):
                return False
            self._refresh_queue_metrics(session)
            session.commit()
            return True

    def cancel_requested(self, job_id: int, *, worker_id: str | None = None) -> bool:
        with self.session_factory() as session:
            stmt = select(SyncJob.cancel_requested_at).where(SyncJob.id == job_id)
            if worker_id is not None:
                stmt = stmt.where(SyncJob.locked_by == worker_id)
            value = session.scalar(stmt)
        return value is not None

    def request_pause(self, job_id: int) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .values(pause_requested_at=datetime.now(UTC))
                    .execution_options(synchronize_session=False)
                ),
            )
            session.commit()
            return bool(result.rowcount)

    def pause_requested(self, job_id: int, *, worker_id: str | None = None) -> bool:
        with self.session_factory() as session:
            stmt = select(SyncJob.pause_requested_at).where(SyncJob.id == job_id)
            if worker_id is not None:
                stmt = stmt.where(SyncJob.locked_by == worker_id)
            value = session.scalar(stmt)
        return value is not None

    def resume(self, job_id: int) -> bool:
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                .with_for_update()
            )
            if job is None or self._job_has_pause_policy(session, job):
                return False
            changed = job.pause_requested_at is not None
            job.pause_requested_at = None
            session.commit()
            return changed

    def hold_running_for_pause(self, job_id: int, *, worker_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .values(
                        status=JobStatus.QUEUED.value,
                        attempts=SyncJob.attempts - 1,
                        run_after=datetime.now(UTC),
                        error_message=None,
                        locked_by=None,
                        locked_at=None,
                        fence_token=None,
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if result.rowcount:
                self._refresh_queue_metrics(session)
            session.commit()
            return bool(result.rowcount)

    def request_repo_pause(self, repo_id: str) -> list[int]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.repo_id == repo_id)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .with_for_update()
                ).all()
            )
            now = datetime.now(UTC)
            for job in jobs:
                job.pause_requested_at = now
            session.commit()
            return [int(job.id) for job in jobs]

    def request_pause_all(self) -> list[int]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .with_for_update()
                ).all()
            )
            now = datetime.now(UTC)
            for job in jobs:
                job.pause_requested_at = now
            session.commit()
            return [int(job.id) for job in jobs]

    def resume_global_pause(self) -> list[int]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.pause_requested_at.is_not(None))
                    .with_for_update()
                ).all()
            )
            changed: list[int] = []
            for job in jobs:
                if self._job_has_pause_policy(session, job, ignore_global=True):
                    continue
                job.pause_requested_at = None
                changed.append(int(job.id))
            session.commit()
            return changed

    def resume_repo(self, repo_id: str) -> list[int]:
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.repo_id == repo_id)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .with_for_update()
                ).all()
            )
            changed: list[int] = []
            for job in jobs:
                if self._job_has_pause_policy(session, job, ignore_library=True):
                    continue
                if job.pause_requested_at is not None:
                    job.pause_requested_at = None
                    changed.append(int(job.id))
            session.commit()
            return changed

    def request_cancel_all(self) -> list[int]:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            jobs = list(
                session.scalars(
                    select(SyncJob)
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .with_for_update()
                ).all()
            )
            for job in jobs:
                if job.status in {JobStatus.QUEUED.value, JobStatus.RETRYING.value}:
                    job.status = JobStatus.CANCELLED.value
                    job.locked_by = None
                    job.locked_at = None
                job.cancel_requested_at = now
                job.pause_requested_at = None
            self._refresh_queue_metrics(session)
            session.commit()
            return [int(job.id) for job in jobs]

    def active_counts(self) -> dict[str, int]:
        with self.session_factory() as session:
            counts = {
                status: int(
                    session.scalar(
                        select(func.count(SyncJob.id)).where(SyncJob.status == status)
                    )
                    or 0
                )
                for status in ACTIVE_JOB_STATUSES
            }
            counts["paused"] = int(
                session.scalar(
                    select(func.count(SyncJob.id))
                    .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                    .where(SyncJob.pause_requested_at.is_not(None))
                )
                or 0
            )
            return counts

    def mark_cancelled(self, job_id: int, *, worker_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .values(
                        status=JobStatus.CANCELLED.value,
                        locked_by=None,
                        locked_at=None,
                        pause_requested_at=None,
                    )
                ),
            )
            if result.rowcount:
                self._refresh_queue_metrics(session)
            session.commit()
            return bool(result.rowcount)

    def defer_without_attempt(
        self,
        job_id: int,
        error: str,
        *,
        worker_id: str,
        delay_seconds: int = 30,
    ) -> JobStatus | None:
        if delay_seconds <= 0:
            raise ValueError("delay_seconds must be positive")
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(SyncJob.locked_by == worker_id)
                .with_for_update()
            )
            if job is None:
                return None
            now = datetime.now(UTC)
            if job.cancel_requested_at is not None:
                self._request_cancel_locked(
                    job,
                    now=now,
                    finalize_running=True,
                )
                status = JobStatus.CANCELLED
                job.error_message = None
                job.run_after = now
            elif job.pause_requested_at is not None:
                status = JobStatus.QUEUED
                job.status = status.value
                job.attempts = max(0, int(job.attempts) - 1)
                job.run_after = now
                job.error_message = None
                job.locked_by = None
                job.locked_at = None
                job.fence_token = None
            else:
                status = JobStatus.RETRYING
                job.status = status.value
                job.attempts = max(0, int(job.attempts) - 1)
                job.run_after = now + timedelta(seconds=delay_seconds)
                job.error_message = error[:4000]
                job.locked_by = None
                job.locked_at = None
                job.fence_token = None
            self._refresh_queue_metrics(session)
            session.commit()
            return status

    def retry(self, job_id: int) -> bool:
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .where(
                    SyncJob.status.in_(
                        [JobStatus.DEAD.value, JobStatus.CANCELLED.value]
                    )
                )
                .with_for_update()
            )
            if job is None:
                return False
            active_copy = session.scalar(
                select(SyncJob.id)
                .where(SyncJob.dedup_key == job.dedup_key)
                .where(SyncJob.id != job.id)
                .where(SyncJob.status.in_(ACTIVE_JOB_STATUSES))
                .order_by(SyncJob.id)
                .limit(1)
            )
            if active_copy is not None:
                return False
            try:
                with session.begin_nested():
                    job.status = JobStatus.QUEUED.value
                    job.attempts = 0
                    job.run_after = datetime.now(UTC)
                    job.error_message = None
                    job.cancel_requested_at = None
                    job.pause_requested_at = None
                    job.locked_by = None
                    job.locked_at = None
                    job.fence_token = None
                    session.flush()
            except IntegrityError:
                session.rollback()
                return False
            self._refresh_queue_metrics(session)
            session.commit()
            return True

    def mark_succeeded(self, job_id: int, *, worker_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .where(SyncJob.cancel_requested_at.is_(None))
                    .values(
                        status=JobStatus.SUCCEEDED.value,
                        error_message=None,
                        pause_requested_at=None,
                        locked_by=None,
                        locked_at=None,
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if result.rowcount:
                self._refresh_queue_metrics(session)
            session.commit()
            return bool(result.rowcount)

    def mark_failed(
        self,
        job_id: int,
        error: str,
        *,
        worker_id: str,
        retryable: bool,
    ) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.scalar(
                select(SyncJob)
                .where(SyncJob.id == job_id)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(SyncJob.locked_by == worker_id)
                .with_for_update()
            )
            if job is None:
                return None
            status = self._mark_failed_job(
                session,
                job,
                error,
                retryable=retryable,
                now=datetime.now(UTC),
            )
            if status is None:
                session.rollback()
                return None
            self._refresh_queue_metrics(session)
            session.commit()
            return status

    def _mark_failed_job(
        self,
        session: Session,
        job: SyncJob,
        error: str,
        *,
        retryable: bool,
        now: datetime,
    ) -> JobStatus | None:
        if job.cancel_requested_at is not None:
            status = JobStatus.CANCELLED
            run_after = now
        elif job.pause_requested_at is not None:
            status = JobStatus.QUEUED
            run_after = now
        elif not retryable or job.attempts >= job.max_attempts:
            status = JobStatus.DEAD
            run_after = now
        else:
            delay = exponential_backoff_seconds(
                job.attempts,
                base_seconds=self.retry_base_seconds,
                max_seconds=self.retry_max_seconds,
            )
            status = JobStatus.RETRYING
            run_after = now + timedelta(seconds=delay)
        result = cast(
            CursorResult[Any],
            session.execute(
                update(SyncJob)
                .where(SyncJob.id == job.id)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(SyncJob.locked_by == job.locked_by)
                .where(SyncJob.attempts == job.attempts)
                .values(
                    status=status.value,
                    attempts=(
                        max(0, int(job.attempts) - 1)
                        if status == JobStatus.QUEUED
                        else job.attempts
                    ),
                    error_message=(
                        None
                        if status in {JobStatus.CANCELLED, JobStatus.QUEUED}
                        else error[:4000]
                    ),
                    locked_by=None,
                    locked_at=None,
                    fence_token=None,
                    pause_requested_at=(
                        None
                        if status == JobStatus.CANCELLED
                        else job.pause_requested_at
                    ),
                    run_after=run_after,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return status if result.rowcount else None

    @staticmethod
    def to_spec(job: SyncJob) -> JobSpec:
        return JobSpec(
            job_type=JobType(job.job_type),
            repo_id=job.repo_id,
            file_path=job.file_path,
            payload=dict(job.payload or {}),
            priority=job.priority,
            max_attempts=job.max_attempts,
        )

    def requeue_stale_running_jobs(
        self,
        *,
        older_than_seconds: int = 900,
    ) -> StaleJobRecoveryResult:
        if older_than_seconds <= 0:
            raise ValueError("older_than_seconds must be positive")
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)
        retrying = 0
        dead = 0
        with self.session_factory() as session:
            jobs = session.scalars(
                select(SyncJob)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(or_(SyncJob.locked_at.is_(None), SyncJob.locked_at < cutoff))
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                recovered_status = self._recover_stale_job(
                    session,
                    job,
                    cutoff=cutoff,
                    now=now,
                )
                if recovered_status == JobStatus.DEAD:
                    dead += 1
                elif recovered_status == JobStatus.RETRYING:
                    retrying += 1
            self._refresh_queue_metrics(session)
            session.commit()
        return StaleJobRecoveryResult(retrying=retrying, dead=dead)

    def _recover_stale_job(
        self,
        session: Session,
        job: SyncJob,
        *,
        cutoff: datetime,
        now: datetime,
    ) -> JobStatus | None:
        if job.cancel_requested_at is not None:
            status = JobStatus.CANCELLED
            run_after = now
        elif job.pause_requested_at is not None:
            status = JobStatus.QUEUED
            run_after = now
        elif job.attempts >= job.max_attempts:
            status = JobStatus.DEAD
            run_after = now
        else:
            status = JobStatus.RETRYING
            delay = exponential_backoff_seconds(
                job.attempts,
                base_seconds=self.retry_base_seconds,
                max_seconds=self.retry_max_seconds,
            )
            run_after = now + timedelta(seconds=delay)
        result = cast(
            CursorResult[Any],
            session.execute(
                update(SyncJob)
                .where(SyncJob.id == job.id)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(SyncJob.locked_by == job.locked_by)
                .where(or_(SyncJob.locked_at.is_(None), SyncJob.locked_at < cutoff))
                .values(
                    status=status.value,
                    attempts=(
                        SyncJob.attempts - 1
                        if status == JobStatus.QUEUED
                        else SyncJob.attempts
                    ),
                    locked_by=None,
                    locked_at=None,
                    error_message=(
                        None
                        if status in {JobStatus.CANCELLED, JobStatus.QUEUED}
                        else "worker_lease_expired"
                    ),
                    run_after=run_after,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return status if result.rowcount else None

    @staticmethod
    def _workflow_is_terminal(workflow: SyncRun) -> bool:
        progress = dict(workflow.progress or {})
        return (
            workflow.cancel_requested_at is not None
            or workflow.status in {"cancelled", "stopped", "failed", "succeeded"}
            or bool(progress.get("admin_stopped"))
        )

    @staticmethod
    def _workflow_is_paused(workflow: SyncRun) -> bool:
        return not JobStore._workflow_is_terminal(workflow) and bool(
            (workflow.progress or {}).get("admin_paused")
        )

    @staticmethod
    def _active_workflow_subscribers(
        session: Session,
        job_id: int,
    ) -> list[tuple[bool, SyncRun]]:
        rows = session.execute(
            select(WorkflowJobSubscription.owns_job, SyncRun)
            .join(
                SyncRun,
                SyncRun.id == WorkflowJobSubscription.workflow_run_id,
            )
            .where(WorkflowJobSubscription.job_id == job_id)
            .where(WorkflowJobSubscription.cancelled_at.is_(None))
            .order_by(WorkflowJobSubscription.workflow_run_id)
        ).all()
        return [
            (bool(owns_job), workflow)
            for owns_job, workflow in rows
            if not JobStore._workflow_is_terminal(workflow)
        ]

    @classmethod
    def _reconcile_workflow_job(
        cls,
        session: Session,
        job: SyncJob,
        *,
        now: datetime,
        clear_workflow_pause: bool = False,
        preserve_existing_pause: bool = False,
    ) -> bool:
        subscribers = cls._active_workflow_subscribers(session, int(job.id))
        if not subscribers:
            has_owner = session.scalar(
                select(WorkflowJobSubscription.job_id)
                .where(WorkflowJobSubscription.job_id == job.id)
                .where(WorkflowJobSubscription.owns_job.is_(True))
                .limit(1)
            )
            if has_owner is not None:
                return cls._request_cancel_locked(job, now=now)
            return False
        workflow_pause = (
            any(
                owns_job and cls._workflow_is_paused(workflow)
                for owns_job, workflow in subscribers
            )
            and all(cls._workflow_is_paused(workflow) for _owns_job, workflow in subscribers)
        )
        if (
            workflow_pause
            and job.status in ACTIVE_JOB_STATUSES
            and job.cancel_requested_at is None
        ):
            job.pause_requested_at = job.pause_requested_at or now
            return False
        paused_workflow_is_sharing = any(
            cls._workflow_is_paused(workflow) for _owns_job, workflow in subscribers
        )
        if (
            job.pause_requested_at is not None
            and not preserve_existing_pause
            and (clear_workflow_pause or paused_workflow_is_sharing)
            and not cls._job_has_pause_policy(session, job)
        ):
            job.pause_requested_at = None
        return False

    @staticmethod
    def _job_has_pause_policy(
        session: Session,
        job: SyncJob,
        *,
        excluded_workflow_run_id: str | None = None,
        ignore_library: bool = False,
        ignore_global: bool = False,
    ) -> bool:
        if not ignore_global:
            workflow_control = session.get(WorkflowControlState, 1)
            if workflow_control is not None and workflow_control.queue_paused:
                return True
        if not ignore_library and job.repo_id:
            library_control = session.get(LibraryControlState, job.repo_id)
            if library_control is not None and (
                not library_control.enabled or library_control.paused
            ):
                return True
        subscribers = [
            (owns_job, workflow)
            for owns_job, workflow in JobStore._active_workflow_subscribers(
                session, int(job.id)
            )
            if workflow.id != excluded_workflow_run_id
        ]
        return bool(subscribers) and any(
            owns_job and JobStore._workflow_is_paused(workflow)
            for owns_job, workflow in subscribers
        ) and all(
            JobStore._workflow_is_paused(workflow) for _owns_job, workflow in subscribers
        )

    def purge_completed_jobs(self, *, older_than_days: int = 30) -> int:
        if older_than_days <= 0:
            raise ValueError("older_than_days must be positive")
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    delete(SyncJob)
                    .where(
                        SyncJob.status.in_(
                            [JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value]
                        )
                    )
                    .where(SyncJob.updated_at < cutoff)
                ),
            )
            self._refresh_queue_metrics(session)
            session.commit()
            return int(result.rowcount or 0)

    @staticmethod
    def _refresh_queue_metrics(session: Session) -> None:
        queued_count = session.scalar(
            select(func.count(SyncJob.id)).where(
                SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value])
            )
        )
        running_count = session.scalar(
            select(func.count(SyncJob.id)).where(SyncJob.status == JobStatus.RUNNING.value)
        )
        oldest = session.scalar(
            select(func.min(SyncJob.created_at)).where(
                SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value])
            )
        )
        jobs_queued.set(int(queued_count or 0))
        jobs_running.set(int(running_count or 0))
        if oldest is None:
            jobs_oldest_queued_age_seconds.set(0)
            return
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        age_seconds = max(0.0, (datetime.now(UTC) - oldest).total_seconds())
        jobs_oldest_queued_age_seconds.set(age_seconds)


class JobSignalQueue:
    def __init__(self, redis_url: str, *, queue_name: str = "connector:jobs") -> None:
        from redis import Redis

        self.redis = Redis.from_url(redis_url)
        self.queue_name = queue_name

    def signal(self, job_id: int) -> None:
        self.redis.lpush(self.queue_name, str(job_id))

    def wait(self, timeout_seconds: int = 5) -> str | None:
        item = cast(
            tuple[bytes, bytes] | None,
            self.redis.brpop(
                self.queue_name,
                timeout=timeout_seconds,
            ),
        )
        if item is None:
            return None
        return item[1].decode("utf-8")

    def close(self) -> None:
        self.redis.close()
