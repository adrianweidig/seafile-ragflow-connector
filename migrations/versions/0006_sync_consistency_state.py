"""sync consistency and recovery state

Revision ID: 0006_sync_consistency_state
Revises: 0005_sync_job_deduplication
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_sync_consistency_state"
down_revision = "0005_sync_job_deduplication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("libraries", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.add_column("libraries", sa.Column("missing_since", sa.DateTime(timezone=True)))
    op.add_column(
        "libraries",
        sa.Column("last_missing_observation_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "libraries",
        sa.Column("missing_observations", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "libraries",
        sa.Column("deletion_state", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column("sync_jobs", sa.Column("run_id", sa.Text()))
    op.add_column("sync_jobs", sa.Column("fence_token", sa.BigInteger()))
    op.add_column(
        "sync_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "repo_mutation_leases",
        sa.Column("repo_id", sa.Text(), primary_key=True),
        sa.Column("owner_id", sa.Text()),
        sa.Column("fence_token", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("acquired_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "parent_run_id",
            sa.Text(),
            sa.ForeignKey("sync_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("sync_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
        ),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="/"),
        sa.Column("baseline_commit_id", sa.Text()),
        sa.Column("target_commit_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("fence_token", sa.BigInteger()),
        sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.Text()),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
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
    op.create_index("ix_sync_runs_repo_started", "sync_runs", ["repo_id", "started_at"])
    op.create_index("ix_sync_runs_status_started", "sync_runs", ["status", "started_at"])

    op.create_table(
        "workflow_job_subscriptions",
        sa.Column(
            "workflow_run_id",
            sa.Text(),
            sa.ForeignKey("sync_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("sync_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_root", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owns_job", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_workflow_job_subscriptions_job",
        "workflow_job_subscriptions",
        ["job_id", "cancelled_at"],
    )

    op.create_table(
        "source_snapshots",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("commit_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="/"),
        sa.Column("state", sa.Text(), nullable=False, server_default="staging"),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "repo_id",
            "commit_id",
            "scope",
            name="uq_source_snapshots_repo_commit_scope",
        ),
    )
    op.create_index(
        "ix_source_snapshots_repo_state",
        "source_snapshots",
        ["repo_id", "state"],
    )

    op.create_table(
        "source_snapshot_entries",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("source_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text()),
        sa.Column("size", sa.BigInteger()),
        sa.Column("mtime", sa.BigInteger()),
        sa.Column("is_directory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint(
            "snapshot_id",
            "normalized_path",
            name="uq_source_snapshot_entries_path",
        ),
    )
    op.create_index(
        "ix_source_snapshot_entries_object",
        "source_snapshot_entries",
        ["snapshot_id", "object_id"],
    )

    op.create_table(
        "sync_cursors",
        sa.Column(
            "repo_id",
            sa.Text(),
            sa.ForeignKey("libraries.repo_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scope", sa.Text(), primary_key=True, server_default="/"),
        sa.Column("commit_id", sa.Text(), nullable=False),
        sa.Column(
            "snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "file_document_versions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repo_id", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text()),
        sa.Column("document_name", sa.Text(), nullable=False),
        sa.Column("source_content_sha256", sa.Text()),
        sa.Column("ingested_content_sha256", sa.Text()),
        sa.Column("ingested_mime", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending_upload"),
        sa.Column("parse_status", sa.Text()),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upload_operation_id", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "previous_version_id",
            sa.BigInteger(),
            sa.ForeignKey("file_document_versions.id", ondelete="SET NULL"),
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
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "dataset_id",
            "document_id",
            name="uq_file_document_versions_target",
        ),
        sa.UniqueConstraint(
            "upload_operation_id",
            name="uq_file_document_versions_upload_operation",
        ),
    )
    op.create_index(
        "ix_file_document_versions_file_state",
        "file_document_versions",
        ["file_id", "state"],
    )
    op.create_index(
        "ix_file_document_versions_repo_state",
        "file_document_versions",
        ["repo_id", "state"],
    )

    op.create_table(
        "cleanup_outbox",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("repo_id", sa.Text(), nullable=False),
        sa.Column(
            "run_id",
            sa.Text(),
            sa.ForeignKey("sync_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "document_version_id",
            sa.BigInteger(),
            sa.ForeignKey("file_document_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False, server_default="delete"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("fence_token", sa.BigInteger()),
        sa.Column("error_message", sa.Text()),
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
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "target_type",
            "target_id",
            "action",
            name="uq_cleanup_outbox_target_action",
        ),
    )
    op.create_index(
        "ix_cleanup_outbox_status_run_after",
        "cleanup_outbox",
        ["status", "run_after"],
    )
    op.create_index(
        "ix_cleanup_outbox_repo_status",
        "cleanup_outbox",
        ["repo_id", "status"],
    )
    op.create_index(
        "ix_cleanup_outbox_run_status",
        "cleanup_outbox",
        ["run_id", "status"],
    )
    op.create_table(
        "workflow_cleanup_subscriptions",
        sa.Column(
            "workflow_run_id",
            sa.Text(),
            sa.ForeignKey("sync_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "outbox_id",
            sa.BigInteger(),
            sa.ForeignKey("cleanup_outbox.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_workflow_cleanup_subscriptions_outbox",
        "workflow_cleanup_subscriptions",
        ["outbox_id", "cancelled_at"],
    )

    # Legacy state occasionally bound the same RAGFlow document to multiple
    # files. Keep the lowest file id as the deterministic owner and quarantine
    # every loser before the unique version target constraint is populated.
    op.execute(
        sa.text(
            """
            UPDATE files
            SET ragflow_document_id = NULL,
                ragflow_document_name = NULL,
                ingested_document_name = NULL,
                sync_status = 'repair_required',
                parse_status = NULL,
                error_message =
                    'Legacy duplicate RAGFlow document binding quarantined by migration 0006'
            WHERE id IN (
                SELECT loser.id
                FROM files AS loser
                JOIN libraries AS loser_library
                  ON loser_library.repo_id = loser.repo_id
                JOIN files AS winner
                  ON winner.ragflow_document_id = loser.ragflow_document_id
                 AND winner.id < loser.id
                JOIN libraries AS winner_library
                  ON winner_library.repo_id = winner.repo_id
                 AND winner_library.ragflow_dataset_id = loser_library.ragflow_dataset_id
                WHERE loser.ragflow_document_id IS NOT NULL
                  AND loser_library.ragflow_dataset_id IS NOT NULL
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO file_document_versions (
                file_id, repo_id, normalized_path, dataset_id, document_id,
                document_name, source_content_sha256, ingested_content_sha256,
                ingested_mime, state, parse_status, poll_count, retry_count,
                error_message,
                created_at, updated_at, promoted_at
            )
            SELECT
                files.id, files.repo_id, files.normalized_path,
                libraries.ragflow_dataset_id, files.ragflow_document_id,
                COALESCE(files.ragflow_document_name, files.ingested_document_name),
                files.source_content_sha256, files.ingested_content_sha256,
                files.ingested_mime, 'current', files.parse_status, 0,
                files.retry_count, files.error_message,
                files.created_at, files.updated_at, files.updated_at
            FROM files
            JOIN libraries ON libraries.repo_id = files.repo_id
            WHERE files.ragflow_document_id IS NOT NULL
              AND libraries.ragflow_dataset_id IS NOT NULL
              AND COALESCE(files.ragflow_document_name, files.ingested_document_name) IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_cleanup_subscriptions_outbox",
        table_name="workflow_cleanup_subscriptions",
    )
    op.drop_table("workflow_cleanup_subscriptions")
    op.drop_index("ix_cleanup_outbox_run_status", table_name="cleanup_outbox")
    op.drop_index("ix_cleanup_outbox_repo_status", table_name="cleanup_outbox")
    op.drop_index("ix_cleanup_outbox_status_run_after", table_name="cleanup_outbox")
    op.drop_table("cleanup_outbox")
    op.drop_index(
        "ix_file_document_versions_repo_state",
        table_name="file_document_versions",
    )
    op.drop_index(
        "ix_file_document_versions_file_state",
        table_name="file_document_versions",
    )
    op.drop_table("file_document_versions")
    op.drop_table("sync_cursors")
    op.drop_index(
        "ix_source_snapshot_entries_object",
        table_name="source_snapshot_entries",
    )
    op.drop_table("source_snapshot_entries")
    op.drop_index("ix_source_snapshots_repo_state", table_name="source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_index(
        "ix_workflow_job_subscriptions_job",
        table_name="workflow_job_subscriptions",
    )
    op.drop_table("workflow_job_subscriptions")
    op.drop_index("ix_sync_runs_status_started", table_name="sync_runs")
    op.drop_index("ix_sync_runs_repo_started", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("repo_mutation_leases")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("sync_jobs") as batch_op:
            batch_op.drop_column("cancel_requested_at")
            batch_op.drop_column("fence_token")
            batch_op.drop_column("run_id")
        with op.batch_alter_table("libraries") as batch_op:
            batch_op.drop_column("deletion_state")
            batch_op.drop_column("missing_observations")
            batch_op.drop_column("missing_since")
            batch_op.drop_column("last_missing_observation_at")
            batch_op.drop_column("last_seen_at")
    else:
        op.drop_column("sync_jobs", "cancel_requested_at")
        op.drop_column("sync_jobs", "fence_token")
        op.drop_column("sync_jobs", "run_id")
        op.drop_column("libraries", "deletion_state")
        op.drop_column("libraries", "missing_observations")
        op.drop_column("libraries", "missing_since")
        op.drop_column("libraries", "last_missing_observation_at")
        op.drop_column("libraries", "last_seen_at")
