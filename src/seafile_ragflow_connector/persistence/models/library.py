from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seafile_ragflow_connector.persistence.db import Base


class Library(Base):
    __tablename__ = "libraries"

    repo_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_slug: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seafile_mtime: Mapped[int | None] = mapped_column(BigInteger)
    head_commit_id: Mapped[str | None] = mapped_column(Text)
    last_synced_commit_id: Mapped[str | None] = mapped_column(Text)
    ragflow_dataset_id: Mapped[str | None] = mapped_column(Text)
    ragflow_dataset_name: Mapped[str | None] = mapped_column(Text)
    template_dataset_id: Mapped[str | None] = mapped_column(Text)
    template_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    files = relationship("File", back_populates="library", cascade="all, delete-orphan")
