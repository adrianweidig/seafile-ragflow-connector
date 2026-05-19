"""initial state

Revision ID: 0001_initial_state
Revises:
Create Date: 2026-05-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "libraries",
        sa.Column("repo_id", sa.Text(), primary_key=True),
        sa.Column("owner_email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_slug", sa.Text(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("virtual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("seafile_mtime", sa.BigInteger(), nullable=True),
        sa.Column("head_commit_id", sa.Text(), nullable=True),
        sa.Column("last_synced_commit_id", sa.Text(), nullable=True),
        sa.Column("ragflow_dataset_id", sa.Text(), nullable=True),
        sa.Column("ragflow_dataset_name", sa.Text(), nullable=True),
        sa.Column("template_dataset_id", sa.Text(), nullable=True),
        sa.Column("template_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_libraries_status", "libraries", ["status"])
    op.create_index("ix_libraries_dataset_id", "libraries", ["ragflow_dataset_id"])

    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.Text(), sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("source_extension", sa.Text(), nullable=True),
        sa.Column("detected_mime", sa.Text(), nullable=True),
        sa.Column("detected_encoding", sa.Text(), nullable=True),
        sa.Column("is_text", sa.Boolean(), nullable=True),
        sa.Column("ingestion_strategy", sa.Text(), nullable=False, server_default="direct"),
        sa.Column("seafile_obj_id", sa.Text(), nullable=True),
        sa.Column("seafile_mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("source_content_sha256", sa.Text(), nullable=True),
        sa.Column("ingested_content_sha256", sa.Text(), nullable=True),
        sa.Column("ragflow_document_id", sa.Text(), nullable=True),
        sa.Column("ragflow_document_name", sa.Text(), nullable=True),
        sa.Column("ingested_document_name", sa.Text(), nullable=True),
        sa.Column("ingested_mime", sa.Text(), nullable=True),
        sa.Column("last_seen_commit_id", sa.Text(), nullable=True),
        sa.Column("last_uploaded_dataset_settings_hash", sa.Text(), nullable=True),
        sa.Column("needs_reparse", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("parse_status", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("repo_id", "normalized_path", name="uq_files_repo_path"),
    )
    op.create_index("ix_files_repo_status", "files", ["repo_id", "sync_status"])
    op.create_index("ix_files_ragflow_document_id", "files", ["ragflow_document_id"])

    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("repo_id", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sync_jobs_status_run_after", "sync_jobs", ["status", "run_after"])
    op.create_index("ix_sync_jobs_repo_type", "sync_jobs", ["repo_id", "job_type"])

    op.create_table(
        "template_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("template_dataset_name", sa.Text(), nullable=False),
        sa.Column("template_dataset_id", sa.Text(), nullable=True),
        sa.Column("template_hash", sa.Text(), nullable=True),
        sa.Column("template_payload", sa.JSON(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "dataset_settings_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.Text(), sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ragflow_dataset_id", sa.Text(), nullable=False),
        sa.Column("settings_hash", sa.Text(), nullable=False),
        sa.Column("settings_payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.Text(), nullable=False, server_default="ragflow"),
    )
    op.create_index(
        "ix_dataset_settings_snapshots_repo_observed",
        "dataset_settings_snapshots",
        ["repo_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_settings_snapshots_repo_observed", table_name="dataset_settings_snapshots")
    op.drop_table("dataset_settings_snapshots")
    op.drop_table("template_state")
    op.drop_index("ix_sync_jobs_repo_type", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_status_run_after", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.drop_index("ix_files_ragflow_document_id", table_name="files")
    op.drop_index("ix_files_repo_status", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_libraries_dataset_id", table_name="libraries")
    op.drop_index("ix_libraries_status", table_name="libraries")
    op.drop_table("libraries")

