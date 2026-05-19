from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.utils.retry import exponential_backoff_seconds


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
        with self.session_factory() as session:
            job = SyncJob(
                job_type=spec.job_type.value,
                repo_id=spec.repo_id,
                file_path=spec.file_path,
                payload=spec.payload,
                status=JobStatus.QUEUED.value,
                priority=spec.resolved_priority(),
                max_attempts=spec.max_attempts,
            )
            session.add(job)
            session.commit()
            return int(job.id)

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
            job.locked_by = None
            job.locked_at = None
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
                session.commit()
                return JobStatus.DEAD
            delay = exponential_backoff_seconds(
                job.attempts,
                base_seconds=self.retry_base_seconds,
                max_seconds=self.retry_max_seconds,
            )
            job.status = JobStatus.RETRYING.value
            job.run_after = datetime.now(UTC) + timedelta(seconds=delay)
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
            session.commit()
        return count


class JobSignalQueue:
    def __init__(self, redis_url: str, *, queue_name: str = "connector:jobs") -> None:
        from redis import Redis

        self.redis = Redis.from_url(redis_url)
        self.queue_name = queue_name

    def signal(self, job_id: int) -> None:
        self.redis.lpush(self.queue_name, str(job_id))

    def wait(self, timeout_seconds: int = 5) -> str | None:
        item: tuple[bytes, bytes] | None = self.redis.brpop(self.queue_name, timeout=timeout_seconds)
        if item is None:
            return None
        return item[1].decode("utf-8")
