"""ACL snapshot and search profiles

Revision ID: 0004_acl_search_profiles
Revises: 0003_openwebui_integration_state
Create Date: 2026-06-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_acl_search_profiles"
down_revision = "0003_openwebui_integration_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_acl_subjects",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("subject_name", sa.Text(), nullable=True),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint(
            "repo_id",
            "subject_type",
            "subject_id",
            "source",
            name="uq_library_acl_subject_source",
        ),
    )
    op.create_index("ix_library_acl_subjects_repo", "library_acl_subjects", ["repo_id"])
    op.create_index(
        "ix_library_acl_subjects_seen",
        "library_acl_subjects",
        ["repo_id", "last_seen_at"],
    )

    op.create_table(
        "library_acl_effective_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_email", sa.Text(), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("repo_id", "user_email", name="uq_library_acl_effective_user"),
    )
    op.create_index(
        "ix_library_acl_effective_users_lookup",
        "library_acl_effective_users",
        ["repo_id", "user_email"],
    )
    op.create_index(
        "ix_library_acl_effective_users_seen",
        "library_acl_effective_users",
        ["repo_id", "last_seen_at"],
    )

    op.create_table(
        "search_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ragflow_dataset_id", sa.Text(), nullable=True),
        sa.Column("ragflow_dataset_name", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default="library"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("last_dataset_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_acl_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("repo_id", name="uq_search_profiles_repo"),
        sa.UniqueConstraint("ragflow_dataset_id", name="uq_search_profiles_dataset"),
    )
    op.create_index("ix_search_profiles_status", "search_profiles", ["status"])
    op.create_index("ix_search_profiles_dataset", "search_profiles", ["ragflow_dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_search_profiles_dataset", table_name="search_profiles")
    op.drop_index("ix_search_profiles_status", table_name="search_profiles")
    op.drop_table("search_profiles")
    op.drop_index("ix_library_acl_effective_users_seen", table_name="library_acl_effective_users")
    op.drop_index("ix_library_acl_effective_users_lookup", table_name="library_acl_effective_users")
    op.drop_table("library_acl_effective_users")
    op.drop_index("ix_library_acl_subjects_seen", table_name="library_acl_subjects")
    op.drop_index("ix_library_acl_subjects_repo", table_name="library_acl_subjects")
    op.drop_table("library_acl_subjects")
