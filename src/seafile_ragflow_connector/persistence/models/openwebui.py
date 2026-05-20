from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.persistence.db import Base


class OpenWebUIDatasetMapping(Base):
    __tablename__ = "openwebui_dataset_mappings"
    __table_args__ = (
        UniqueConstraint("repo_id", name="uq_openwebui_mappings_repo"),
        UniqueConstraint("ragflow_dataset_id", name="uq_openwebui_mappings_dataset"),
        UniqueConstraint("openwebui_tool_id", name="uq_openwebui_mappings_tool"),
        UniqueConstraint("openwebui_pipe_id", name="uq_openwebui_mappings_pipe"),
        UniqueConstraint("openwebui_model_name", name="uq_openwebui_mappings_model"),
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
    ragflow_dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    ragflow_dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    ragflow_binding_type: Mapped[str] = mapped_column(Text, nullable=False, default="chat")
    ragflow_chat_id: Mapped[str | None] = mapped_column(Text)
    ragflow_agent_id: Mapped[str | None] = mapped_column(Text)
    openwebui_tool_id: Mapped[str | None] = mapped_column(Text)
    openwebui_pipe_id: Mapped[str | None] = mapped_column(Text)
    openwebui_model_name: Mapped[str | None] = mapped_column(Text)
    tool_definition_hash: Mapped[str | None] = mapped_column(Text)
    pipe_definition_hash: Mapped[str | None] = mapped_column(Text)
    artifact_version: Mapped[str] = mapped_column(Text, nullable=False, default="1")
    sync_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    last_sync_attempt_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    openwebui_tool_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    openwebui_pipe_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    capabilities_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class OpenWebUISyncState(Base):
    __tablename__ = "openwebui_sync_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="disabled")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="disabled")
    base_url: Mapped[str | None] = mapped_column(Text)
    last_healthcheck_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_sync_started_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_sync_finished_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dry_run_plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    capabilities_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
