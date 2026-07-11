from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

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
    assert current == expected == "0005_sync_job_deduplication"
    assert "dedup_key" in columns
