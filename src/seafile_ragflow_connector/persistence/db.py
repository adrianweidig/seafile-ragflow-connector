from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql import text

DATABASE_INIT_ADVISORY_LOCK_ID = 0x5EA71F10


class Base(DeclarativeBase):
    pass


def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False)


def init_database(database_url: str) -> None:
    from seafile_ragflow_connector.persistence import models  # noqa: F401

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
                    Base.metadata.create_all(connection)
                finally:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": DATABASE_INIT_ADVISORY_LOCK_ID},
                    )
            else:
                Base.metadata.create_all(connection)
    finally:
        engine.dispose()


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
