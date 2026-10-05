from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.persistence.db import Base


class RepoMutationLease(Base):
    __tablename__ = "repo_mutation_leases"

    repo_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(Text)
    fence_token: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_repo_started", "repo_id", "started_at"),
        Index("ix_sync_runs_status_started", "status", "started_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_run_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("sync_runs.id", ondelete="SET NULL"),
    )
    job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sync_jobs.id", ondelete="SET NULL"),
    )
    repo_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("libraries.repo_id", ondelete="CASCADE"),
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="/")
    baseline_commit_id: Mapped[str | None] = mapped_column(Text)
    target_commit_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    fence_token: Mapped[int | None] = mapped_column(BigInteger)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkflowJobSubscription(Base):
    __tablename__ = "workflow_job_subscriptions"
    __table_args__ = (
        Index("ix_workflow_job_subscriptions_job", "job_id", "cancelled_at"),
    )

    workflow_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sync_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owns_job: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "repo_id",
            "commit_id",
            "scope",
            name="uq_source_snapshots_repo_commit_scope",
        ),
        Index("ix_source_snapshots_repo_state", "repo_id", "state"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    repo_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("libraries.repo_id", ondelete="CASCADE"),
        nullable=False,
    )
    commit_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="/")
    state: Mapped[str] = mapped_column(Text, nullable=False, default="staging")
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceSnapshotEntry(Base):
    __tablename__ = "source_snapshot_entries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "normalized_path",
            name="uq_source_snapshot_entries_path",
        ),
        Index("ix_source_snapshot_entries_object", "snapshot_id", "object_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(BigInteger)
    mtime: Mapped[int | None] = mapped_column(BigInteger)
    is_directory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    repo_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("libraries.repo_id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(Text, primary_key=True, default="/")
    commit_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class FileDocumentVersion(Base):
    __tablename__ = "file_document_versions"
    __table_args__ = (
        Index("ix_file_document_versions_file_state", "file_id", "state"),
        Index("ix_file_document_versions_repo_state", "repo_id", "state"),
        UniqueConstraint(
            "dataset_id",
            "document_id",
            name="uq_file_document_versions_target",
        ),
        UniqueConstraint(
            "upload_operation_id",
            name="uq_file_document_versions_upload_operation",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_id: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str | None] = mapped_column(Text)
    document_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_content_sha256: Mapped[str | None] = mapped_column(Text)
    ingested_content_sha256: Mapped[str | None] = mapped_column(Text)
    ingested_mime: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending_upload")
    parse_status: Mapped[str | None] = mapped_column(Text)
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload_operation_id: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    previous_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("file_document_versions.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CleanupOutbox(Base):
    __tablename__ = "cleanup_outbox"
    __table_args__ = (
        Index("ix_cleanup_outbox_status_run_after", "status", "run_after"),
        Index("ix_cleanup_outbox_repo_status", "repo_id", "status"),
        Index("ix_cleanup_outbox_run_status", "run_id", "status"),
        UniqueConstraint(
            "target_type",
            "target_id",
            "action",
            name="uq_cleanup_outbox_target_action",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    repo_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("sync_runs.id", ondelete="SET NULL"),
    )
    file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("files.id", ondelete="SET NULL"),
    )
    document_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("file_document_versions.id", ondelete="SET NULL"),
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False, default="delete")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fence_token: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowCleanupSubscription(Base):
    __tablename__ = "workflow_cleanup_subscriptions"
    __table_args__ = (
        Index(
            "ix_workflow_cleanup_subscriptions_outbox",
            "outbox_id",
            "cancelled_at",
        ),
    )

    workflow_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    outbox_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cleanup_outbox.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
