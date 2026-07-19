"""persistent dashboard administration control

Revision ID: 0007_dashboard_admin_control
Revises: 0006_sync_consistency_state
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_dashboard_admin_control"
down_revision = "0006_sync_consistency_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_jobs",
        sa.Column("pause_requested_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "workflow_control_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "automation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "queue_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.Text(), nullable=False, server_default="system"),
    )
    op.create_table(
        "library_control_states",
        sa.Column("repo_id", sa.Text(), primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.Text(), nullable=False, server_default="system"),
    )

    library_controls = sa.table(
        "library_control_states",
        sa.column("repo_id", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("paused", sa.Boolean()),
        sa.column("updated_by", sa.Text()),
    )
    libraries = sa.table("libraries", sa.column("repo_id", sa.Text()))
    op.execute(
        library_controls.insert().from_select(
            ["repo_id", "enabled", "paused", "updated_by"],
            sa.select(
                libraries.c.repo_id,
                sa.literal(True),
                sa.literal(False),
                sa.literal("migration"),
            ),
        )
    )


def downgrade() -> None:
    op.drop_table("library_control_states")
    op.drop_table("workflow_control_state")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.drop_column("pause_requested_at")
    else:
        op.drop_column("sync_jobs", "pause_requested_at")
