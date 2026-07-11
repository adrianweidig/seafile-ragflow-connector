from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, delete, func, select, text
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


class JobStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
    ) -> None:
        self.session_factory = session_factory
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    def enqueue(self, spec: JobSpec) -> int:
        return self.enqueue_with_result(spec).job_id

    def enqueue_with_result(self, spec: JobSpec) -> EnqueueResult:
        values = {
            "job_type": spec.job_type.value,
            "repo_id": spec.repo_id,
            "file_path": spec.file_path,
            "dedup_key": spec.dedup_key(),
            "payload": spec.payload,
            "status": JobStatus.QUEUED.value,
            "priority": spec.resolved_priority(),
            "max_attempts": spec.max_attempts,
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
                    existing.max_attempts = max(existing.max_attempts, spec.max_attempts)
                    self._refresh_queue_metrics(session)
                    session.commit()
                    jobs_deduplicated_total.inc()
                    return EnqueueResult(int(existing.id), True)
            raise RuntimeError("active job changed repeatedly while enqueueing")

    def acquire_next(self, worker_id: str) -> SyncJob | None:
        with self.session_factory() as session:
            now = datetime.now(UTC)
            stmt: Select[tuple[SyncJob]] = (
                select(SyncJob)
                .where(SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]))
                .where(SyncJob.run_after <= now)
                .order_by(SyncJob.priority.asc(), SyncJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = session.execute(stmt).scalar_one_or_none()
            if job is None:
                return None
            job.status = JobStatus.RUNNING.value
            job.locked_by = worker_id
            job.locked_at = now
            job.attempts += 1
            self._refresh_queue_metrics(session)
            session.commit()
            session.refresh(job)
            session.expunge(job)
            return job

    def mark_succeeded(self, job_id: int) -> None:
        with self.session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None:
                return
            job.status = JobStatus.SUCCEEDED.value
            job.error_message = None
            job.locked_by = None
            job.locked_at = None
            self._refresh_queue_metrics(session)
            session.commit()

    def mark_failed(self, job_id: int, error: str) -> JobStatus:
        with self.session_factory() as session:
            job = session.get(SyncJob, job_id)
            if job is None:
                return JobStatus.DEAD
            job.error_message = error[:4000]
            job.locked_by = None
            job.locked_at = None
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.DEAD.value
                self._refresh_queue_metrics(session)
                session.commit()
                return JobStatus.DEAD
            delay = exponential_backoff_seconds(
                job.attempts,
                base_seconds=self.retry_base_seconds,
                max_seconds=self.retry_max_seconds,
            )
            job.status = JobStatus.RETRYING.value
            job.run_after = datetime.now(UTC) + timedelta(seconds=delay)
            self._refresh_queue_metrics(session)
            session.commit()
            return JobStatus.RETRYING

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

    def requeue_stale_running_jobs(self, *, older_than_seconds: int = 900) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        count = 0
        with self.session_factory() as session:
            jobs = session.scalars(
                select(SyncJob)
                .where(SyncJob.status == JobStatus.RUNNING.value)
                .where(SyncJob.locked_at < cutoff)
            ).all()
            for job in jobs:
                job.status = JobStatus.RETRYING.value
                job.locked_by = None
                job.locked_at = None
                job.run_after = datetime.now(UTC)
                count += 1
            self._refresh_queue_metrics(session)
            session.commit()
        return count

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
