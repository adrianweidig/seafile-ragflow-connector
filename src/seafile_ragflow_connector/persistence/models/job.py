from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.persistence.db import Base


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index(
            "uq_sync_jobs_active_dedup",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'retrying', 'running')"),
            sqlite_where=text("status IN ('queued', 'retrying', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    repo_id: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    fence_token: Mapped[int | None] = mapped_column(BigInteger)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
