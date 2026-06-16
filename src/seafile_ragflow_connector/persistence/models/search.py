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


class LibraryACLSubject(Base):
    __tablename__ = "library_acl_subjects"
    __table_args__ = (
        UniqueConstraint(
            "repo_id",
            "subject_type",
            "subject_id",
            "source",
            name="uq_library_acl_subject_source",
        ),
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
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject_name: Mapped[str | None] = mapped_column(Text)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class LibraryACLEffectiveUser(Base):
    __tablename__ = "library_acl_effective_users"
    __table_args__ = (
        UniqueConstraint("repo_id", "user_email", name="uq_library_acl_effective_user"),
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
    user_email: Mapped[str] = mapped_column(Text, nullable=False)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_seen_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SearchProfile(Base):
    __tablename__ = "search_profiles"
    __table_args__ = (
        UniqueConstraint("repo_id", name="uq_search_profiles_repo"),
        UniqueConstraint("ragflow_dataset_id", name="uq_search_profiles_dataset"),
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
    ragflow_dataset_id: Mapped[str | None] = mapped_column(Text)
    ragflow_dataset_name: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="library")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    last_dataset_sync_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_acl_sync_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
