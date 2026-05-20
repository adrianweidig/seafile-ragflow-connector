from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.persistence.db import Base


class DashboardSyncRun(Base):
    __tablename__ = "dashboard_sync_runs"

    sync_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    objects_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class DashboardChangeEvent(Base):
    __tablename__ = "dashboard_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_name: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(Text)
    target_path: Mapped[str | None] = mapped_column(Text)
    previous_name: Mapped[str | None] = mapped_column(Text)
    new_name: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[str] = mapped_column(Text, nullable=False, default="seafile")
    target_system: Mapped[str] = mapped_column(Text, nullable=False, default="ragflow")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DashboardLogEntry(Base):
    __tablename__ = "dashboard_log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sync_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
