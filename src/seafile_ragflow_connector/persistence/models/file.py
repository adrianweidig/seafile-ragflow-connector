from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from seafile_ragflow_connector.persistence.db import Base


class File(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("repo_id", "normalized_path", name="uq_files_repo_path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("libraries.repo_id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_extension: Mapped[str | None] = mapped_column(Text)
    detected_mime: Mapped[str | None] = mapped_column(Text)
    detected_encoding: Mapped[str | None] = mapped_column(Text)
    is_text: Mapped[bool | None] = mapped_column(Boolean)
    ingestion_strategy: Mapped[str] = mapped_column(Text, nullable=False, default="direct")
    seafile_obj_id: Mapped[str | None] = mapped_column(Text)
    seafile_mtime: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    size: Mapped[int | None] = mapped_column(BigInteger)
    source_content_sha256: Mapped[str | None] = mapped_column(Text)
    ingested_content_sha256: Mapped[str | None] = mapped_column(Text)
    ragflow_document_id: Mapped[str | None] = mapped_column(Text)
    ragflow_document_name: Mapped[str | None] = mapped_column(Text)
    ingested_document_name: Mapped[str | None] = mapped_column(Text)
    ingested_mime: Mapped[str | None] = mapped_column(Text)
    last_seen_commit_id: Mapped[str | None] = mapped_column(Text)
    last_uploaded_dataset_settings_hash: Mapped[str | None] = mapped_column(Text)
    needs_reparse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sync_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    parse_status: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    library = relationship("Library", back_populates="files")
