"""dashboard state

Revision ID: 0002_dashboard_state
Revises: 0001_initial_state
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_dashboard_state"
down_revision = "0001_initial_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_sync_runs",
        sa.Column("sync_id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("objects_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objects_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objects_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objects_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("objects_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
    op.create_index(
        "ix_dashboard_sync_runs_status_started",
        "dashboard_sync_runs",
        ["status", "started_at"],
    )

    op.create_table(
        "dashboard_change_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sync_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_name", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("previous_name", sa.Text(), nullable=True),
        sa.Column("new_name", sa.Text(), nullable=True),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("source_system", sa.Text(), nullable=False, server_default="seafile"),
        sa.Column("target_system", sa.Text(), nullable=False, server_default="ragflow"),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_dashboard_change_events_sync_time",
        "dashboard_change_events",
        ["sync_id", "occurred_at"],
    )
    op.create_index(
        "ix_dashboard_change_events_type_status",
        "dashboard_change_events",
        ["change_type", "status"],
    )

    op.create_table(
        "dashboard_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("component", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sync_id", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_dashboard_log_entries_time", "dashboard_log_entries", ["occurred_at"])
    op.create_index(
        "ix_dashboard_log_entries_level_sync",
        "dashboard_log_entries",
        ["level", "sync_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_log_entries_level_sync", table_name="dashboard_log_entries")
    op.drop_index("ix_dashboard_log_entries_time", table_name="dashboard_log_entries")
    op.drop_table("dashboard_log_entries")
    op.drop_index("ix_dashboard_change_events_type_status", table_name="dashboard_change_events")
    op.drop_index("ix_dashboard_change_events_sync_time", table_name="dashboard_change_events")
    op.drop_table("dashboard_change_events")
    op.drop_index("ix_dashboard_sync_runs_status_started", table_name="dashboard_sync_runs")
    op.drop_table("dashboard_sync_runs")
