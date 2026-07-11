from __future__ import annotations

import os

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from seafile_ragflow_connector.persistence.db import _alembic_config, database_revisions


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is required for the PostgreSQL migration test",
)
def test_previous_release_revision_upgrades_to_head_on_postgresql() -> None:
    database_url = os.environ["TEST_POSTGRES_URL"]
    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0004_acl_search_profiles")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO sync_jobs (job_type, status, priority, attempts, max_attempts) "
                    "VALUES ('SYNC_LIBRARY_FULL', 'queued', 100, 0, 5)"
                )
            )
        command.upgrade(config, "head")
        columns = {column["name"] for column in inspect(engine).get_columns("sync_jobs")}
        indexes = {index["name"] for index in inspect(engine).get_indexes("sync_jobs")}
        with engine.connect() as connection:
            dedup_key = connection.scalar(text("SELECT dedup_key FROM sync_jobs LIMIT 1"))
        current, expected = database_revisions(database_url)

        assert "dedup_key" in columns
        assert "uq_sync_jobs_active_dedup" in indexes
        assert str(dedup_key).startswith("legacy:")
        assert current == expected == "0005_sync_job_deduplication"
    finally:
        engine.dispose()
