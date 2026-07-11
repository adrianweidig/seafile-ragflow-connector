from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.app.metrics import (
    jobs_deduplicated_total,
    jobs_oldest_queued_age_seconds,
    jobs_queued,
    jobs_running,
)
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.utils.retry import exponential_backoff_seconds

ACTIVE_JOB_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.RETRYING.value,
    JobStatus.RUNNING.value,
)
ACTIVE_JOB_INDEX_PREDICATE = text("status IN ('queued', 'retrying', 'running')")


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
        with self.session_factory() as session:
            dialect_name = session.get_bind().dialect.name
            if dialect_name not in {"postgresql", "sqlite"}:
                job = SyncJob(**values)
                session.add(job)
                self._refresh_queue_metrics(session)
                session.commit()
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
                    self._refresh_queue_metrics(session)
                    session.commit()
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
                    self._refresh_queue_metrics(session)
                    session.commit()
                    jobs_deduplicated_total.inc()
                    return EnqueueResult(int(existing.id), True)
            raise RuntimeError("active job changed repeatedly while enqueueing")

    def acquire_next(self, worker_id: str) -> SyncJob | None:
        with self.session_factory() as session:
            now = datetime.now(UTC)
            stmt: Select[tuple[int]] = (
                select(SyncJob.id)
                .where(SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]))
                .where(SyncJob.run_after <= now)
                .order_by(SyncJob.priority.asc(), SyncJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job_id = session.execute(stmt).scalar_one_or_none()
            if job_id is None:
                return None
            job = session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .where(
                    SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value])
                )
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

    def mark_succeeded(self, job_id: int, *, worker_id: str) -> bool:
        with self.session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id)
                    .where(SyncJob.status == JobStatus.RUNNING.value)
                    .where(SyncJob.locked_by == worker_id)
                    .values(
                        status=JobStatus.SUCCEEDED.value,
                        error_message=None,
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
        if not retryable or job.attempts >= job.max_attempts:
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
                    error_message=error[:4000],
                    locked_by=None,
                    locked_at=None,
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
        if job.attempts >= job.max_attempts:
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
                    locked_by=None,
                    locked_at=None,
                    error_message="worker_lease_expired",
                    run_after=run_after,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return status if result.rowcount else None

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
