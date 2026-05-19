from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from seafile_ragflow_connector.models.db import Base


class TemplateState(Base):
    __tablename__ = "template_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    template_dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    template_dataset_id: Mapped[str | None] = mapped_column(Text)
    template_hash: Mapped[str | None] = mapped_column(Text)
    template_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_checked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class DatasetSettingsSnapshot(Base):
    __tablename__ = "dataset_settings_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("libraries.repo_id", ondelete="CASCADE"),
        nullable=False,
    )
    ragflow_dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    settings_hash: Mapped[str] = mapped_column(Text, nullable=False)
    settings_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(Text, nullable=False, default="ragflow")

