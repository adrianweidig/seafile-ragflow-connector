from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.persistence.db import Base


class WorkflowControlState(Base):
    __tablename__ = "workflow_control_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    automation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    queue_paused: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="system",
        server_default="system",
    )


class LibraryControlState(Base):
    __tablename__ = "library_control_states"

    repo_id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    paused: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="system",
        server_default="system",
    )
