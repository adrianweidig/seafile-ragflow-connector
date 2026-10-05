from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql import text

DATABASE_INIT_ADVISORY_LOCK_ID = 0x5EA71F10
LEGACY_REVISION_TABLES = (
    (
        "0001_initial_state",
        frozenset(
            {
                "libraries",
                "files",
                "sync_jobs",
                "template_state",
                "dataset_settings_snapshots",
            }
        ),
    ),
    (
        "0002_dashboard_state",
        frozenset(
            {
                "dashboard_sync_runs",
                "dashboard_change_events",
                "dashboard_log_entries",
            }
        ),
    ),
    (
        "0003_openwebui_integration_state",
        frozenset({"openwebui_dataset_mappings", "openwebui_sync_state"}),
    ),
    (
        "0004_acl_search_profiles",
        frozenset(
            {
                "library_acl_subjects",
                "library_acl_effective_users",
                "search_profiles",
            }
        ),
    ),
)


class Base(DeclarativeBase):
    pass


def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False)


def init_database(database_url: str) -> None:
    engine = get_engine(database_url)
    dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
    try:
        with engine.begin() as connection:
            if dialect_name == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": DATABASE_INIT_ADVISORY_LOCK_ID},
                )
                try:
                    config = _alembic_config(database_url, connection)
                    _stamp_legacy_schema_if_needed(connection, config)
                    command.upgrade(config, "head")
                finally:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": DATABASE_INIT_ADVISORY_LOCK_ID},
                    )
            else:
                config = _alembic_config(database_url, connection)
                _stamp_legacy_schema_if_needed(connection, config)
                command.upgrade(config, "head")
    finally:
        engine.dispose()


def database_revisions(database_url: str) -> tuple[str | None, str]:
    config = _alembic_config(database_url)
    expected = ScriptDirectory.from_config(config).get_current_head()
    if expected is None:
        raise RuntimeError("Alembic has no head revision")
    engine = get_engine(database_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    return current, expected


def _alembic_config(database_url: str, connection: Connection | None = None) -> Config:
    repository_root = Path(__file__).resolve().parents[3]
    source_migrations = repository_root / "migrations"
    installed_migrations = Path(__file__).resolve().parents[1] / "migrations"
    migrations_path = source_migrations if source_migrations.is_dir() else installed_migrations
    config_path = repository_root / "alembic.ini"
    config = Config(str(config_path)) if config_path.is_file() else Config()
    if not migrations_path.is_dir():
        raise RuntimeError("Alembic migration scripts are missing from the installation")
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _stamp_legacy_schema_if_needed(connection: Connection, config: Config) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "alembic_version" in table_names:
        current_revision = MigrationContext.configure(connection).get_current_revision()
        if current_revision is not None:
            return
    known_tables = set().union(*(tables for _revision, tables in LEGACY_REVISION_TABLES))
    present_known_tables = table_names & known_tables
    if not present_known_tables:
        return
    revision = _legacy_schema_revision(table_names)
    if revision == "0004_acl_search_profiles":
        sync_job_columns = {column["name"] for column in inspector.get_columns("sync_jobs")}
        sync_job_indexes = {index["name"] for index in inspector.get_indexes("sync_jobs")}
        has_dedup_column = "dedup_key" in sync_job_columns
        has_dedup_index = "uq_sync_jobs_active_dedup" in sync_job_indexes
        if has_dedup_column != has_dedup_index:
            raise RuntimeError("legacy sync_jobs deduplication schema is incomplete")
        if has_dedup_column:
            revision = "0005_sync_job_deduplication"
    command.stamp(config, revision)


def _legacy_schema_revision(table_names: set[str]) -> str:
    revision: str | None = None
    missing_revision_seen = False
    for candidate_revision, required_tables in LEGACY_REVISION_TABLES:
        present = table_names & required_tables
        if present and present != required_tables:
            raise RuntimeError(f"legacy database schema is incomplete at {candidate_revision}")
        if required_tables <= table_names:
            if missing_revision_seen:
                raise RuntimeError("legacy database schema revisions are not sequential")
            revision = candidate_revision
        else:
            missing_revision_seen = True
    if revision is None:
        raise RuntimeError("legacy database schema cannot be identified")
    return revision


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
