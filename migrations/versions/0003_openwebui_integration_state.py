"""openwebui integration state

Revision ID: 0003_openwebui_integration_state
Revises: 0002_dashboard_state
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_openwebui_integration_state"
down_revision = "0002_dashboard_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openwebui_dataset_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ragflow_dataset_id", sa.Text(), nullable=False),
        sa.Column("ragflow_dataset_name", sa.Text(), nullable=False),
        sa.Column("ragflow_binding_type", sa.Text(), nullable=False, server_default="chat"),
        sa.Column("ragflow_chat_id", sa.Text(), nullable=True),
        sa.Column("ragflow_agent_id", sa.Text(), nullable=True),
        sa.Column("openwebui_tool_id", sa.Text(), nullable=True),
        sa.Column("openwebui_pipe_id", sa.Text(), nullable=True),
        sa.Column("openwebui_model_name", sa.Text(), nullable=True),
        sa.Column("tool_definition_hash", sa.Text(), nullable=True),
        sa.Column("pipe_definition_hash", sa.Text(), nullable=True),
        sa.Column("artifact_version", sa.Text(), nullable=False, server_default="1"),
        sa.Column("sync_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "openwebui_tool_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "openwebui_pipe_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "capabilities_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("repo_id", name="uq_openwebui_mappings_repo"),
        sa.UniqueConstraint("ragflow_dataset_id", name="uq_openwebui_mappings_dataset"),
        sa.UniqueConstraint("openwebui_tool_id", name="uq_openwebui_mappings_tool"),
        sa.UniqueConstraint("openwebui_pipe_id", name="uq_openwebui_mappings_pipe"),
        sa.UniqueConstraint("openwebui_model_name", name="uq_openwebui_mappings_model"),
    )
    op.create_index(
        "ix_openwebui_mappings_status",
        "openwebui_dataset_mappings",
        ["sync_status"],
    )
    op.create_index(
        "ix_openwebui_mappings_last_success",
        "openwebui_dataset_mappings",
        ["last_successful_sync_at"],
    )

    op.create_table(
        "openwebui_sync_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mode", sa.Text(), nullable=False, server_default="disabled"),
        sa.Column("status", sa.Text(), nullable=False, server_default="disabled"),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("last_healthcheck_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "dry_run_plan",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "capabilities_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("openwebui_sync_state")
    op.drop_index("ix_openwebui_mappings_last_success", table_name="openwebui_dataset_mappings")
    op.drop_index("ix_openwebui_mappings_status", table_name="openwebui_dataset_mappings")
    op.drop_table("openwebui_dataset_mappings")
