from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from seafile_ragflow_connector.persistence import db


def test_legacy_schema_detection_requires_complete_sequential_revisions() -> None:
    revision_1 = set(db.LEGACY_REVISION_TABLES[0][1])
    revision_2 = set(db.LEGACY_REVISION_TABLES[1][1])
    revision_3 = set(db.LEGACY_REVISION_TABLES[2][1])

    assert db._legacy_schema_revision(revision_1) == "0001_initial_state"
    assert db._legacy_schema_revision(revision_1 | revision_2) == "0002_dashboard_state"
    with pytest.raises(RuntimeError, match="incomplete"):
        db._legacy_schema_revision(revision_1 | {next(iter(revision_2))})
    with pytest.raises(RuntimeError, match="not sequential"):
        db._legacy_schema_revision(revision_1 | revision_3)


def test_unversioned_create_all_era_database_is_stamped_then_upgraded(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    command.upgrade(db._alembic_config(database_url), "0004_acl_search_profiles")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE alembic_version")
    finally:
        engine.dispose()

    db.init_database(database_url)

    current, expected = db.database_revisions(database_url)
    engine = create_engine(database_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("sync_jobs")}
    finally:
        engine.dispose()
    assert current == expected == "0007_dashboard_admin_control"
    assert "dedup_key" in columns


def test_0007_adds_persistent_admin_control_and_job_pause(tmp_path: Path) -> None:
    database_path = tmp_path / "admin-control-upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = db._alembic_config(database_url)
    command.upgrade(config, "0006_sync_consistency_state")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO libraries (repo_id, name, name_slug) "
                    "VALUES ('repo', 'Demo', 'demo')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sync_jobs "
                    "(job_type, dedup_key, status, priority, attempts, max_attempts) "
                    "VALUES ('SYNC_LIBRARY_FULL', 'existing', 'queued', 100, 0, 5)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        job_columns = {
            column["name"] for column in inspector.get_columns("sync_jobs")
        }
        with engine.connect() as connection:
            workflow_count = connection.scalar(
                text("SELECT count(*) FROM workflow_control_state")
            )
            library = connection.execute(
                text(
                    "SELECT repo_id, enabled, paused, updated_by "
                    "FROM library_control_states"
                )
            ).one()
            pause_requested_at = connection.scalar(
                text("SELECT pause_requested_at FROM sync_jobs")
            )
    finally:
        engine.dispose()

    assert {"workflow_control_state", "library_control_states"} <= tables
    assert "pause_requested_at" in job_columns
    assert workflow_count == 0
    assert tuple(library) == ("repo", 1, 0, "migration")
    assert pause_requested_at is None


def test_0006_adds_recovery_tables_and_backfills_current_document(tmp_path: Path) -> None:
    database_path = tmp_path / "upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = db._alembic_config(database_url)
    command.upgrade(config, "0005_sync_job_deduplication")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO libraries "
                    "(repo_id, name, name_slug, ragflow_dataset_id) "
                    "VALUES ('repo', 'Demo', 'demo', 'dataset')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO files "
                    "(repo_id, path, normalized_path, ragflow_document_id, "
                    "ragflow_document_name) "
                    "VALUES ('repo', '/a.pdf', '/a.pdf', 'doc', 'a.pdf')"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        library_columns = {column["name"] for column in inspector.get_columns("libraries")}
        with engine.connect() as connection:
            backfilled = connection.execute(
                text(
                    "SELECT repo_id, dataset_id, document_id, state "
                    "FROM file_document_versions"
                )
            ).one()
    finally:
        engine.dispose()

    assert {
        "repo_mutation_leases",
        "sync_runs",
        "source_snapshots",
        "source_snapshot_entries",
        "sync_cursors",
        "file_document_versions",
        "cleanup_outbox",
    } <= tables
    assert {"last_seen_at", "missing_since", "missing_observations", "deletion_state"} <= (
        library_columns
    )
    assert tuple(backfilled) == ("repo", "dataset", "doc", "current")


def test_0006_quarantines_legacy_duplicate_document_bindings_before_backfill(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "duplicate-upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = db._alembic_config(database_url)
    command.upgrade(config, "0005_sync_job_deduplication")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO libraries "
                    "(repo_id, name, name_slug, ragflow_dataset_id) "
                    "VALUES ('repo', 'Demo', 'demo', 'dataset')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO files "
                    "(repo_id, path, normalized_path, ragflow_document_id, "
                    "ragflow_document_name) VALUES "
                    "('repo', '/winner.pdf', '/winner.pdf', 'same', 'winner.pdf'), "
                    "('repo', '/loser.pdf', '/loser.pdf', 'same', 'loser.pdf')"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            files = connection.execute(
                text(
                    "SELECT path, ragflow_document_id, ragflow_document_name, "
                    "sync_status, error_message FROM files ORDER BY id"
                )
            ).all()
            versions = connection.execute(
                text(
                    "SELECT normalized_path, dataset_id, document_id, state "
                    "FROM file_document_versions"
                )
            ).all()
    finally:
        engine.dispose()

    assert tuple(files[0]) == (
        "/winner.pdf",
        "same",
        "winner.pdf",
        "pending",
        None,
    )
    assert files[1][0:4] == (
        "/loser.pdf",
        None,
        None,
        "repair_required",
    )
    assert "quarantined" in str(files[1][4])
    assert [tuple(row) for row in versions] == [
        ("/winner.pdf", "dataset", "same", "current")
    ]
