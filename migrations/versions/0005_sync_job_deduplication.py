"""deduplicate active sync jobs

Revision ID: 0005_sync_job_deduplication
Revises: 0004_acl_search_profiles
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_sync_job_deduplication"
down_revision = "0004_acl_search_profiles"
branch_labels = None
depends_on = None

_ACTIVE_PREDICATE = "status IN ('queued', 'retrying', 'running')"


def upgrade() -> None:
    op.add_column("sync_jobs", sa.Column("dedup_key", sa.Text(), nullable=True))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("UPDATE sync_jobs SET dedup_key = 'legacy:' || id::text"))
    else:
        op.execute(sa.text("UPDATE sync_jobs SET dedup_key = 'legacy:' || CAST(id AS TEXT)"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.alter_column("dedup_key", existing_type=sa.Text(), nullable=False)
    else:
        op.alter_column("sync_jobs", "dedup_key", existing_type=sa.Text(), nullable=False)
    op.create_index(
        "uq_sync_jobs_active_dedup",
        "sync_jobs",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_PREDICATE),
        sqlite_where=sa.text(_ACTIVE_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_jobs_active_dedup", table_name="sync_jobs")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.drop_column("dedup_key")
    else:
        op.drop_column("sync_jobs", "dedup_key")
