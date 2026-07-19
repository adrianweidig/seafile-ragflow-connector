from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.persistence.models.admin_control import (
    LibraryControlState,
    WorkflowControlState,
)

GLOBAL_CONTROL_ID = 1
ControlAuditWriter = Callable[
    [Session, dict[str, object], dict[str, object]],
    None,
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _actor(value: str) -> str:
    return (value.strip() or "system")[:255]


@dataclass(frozen=True)
class WorkflowControl:
    automation_enabled: bool
    queue_paused: bool
    updated_at: datetime
    updated_by: str

    @property
    def state(self) -> str:
        if self.automation_enabled and not self.queue_paused:
            return "running"
        if self.automation_enabled and self.queue_paused:
            return "paused"
        if self.queue_paused:
            return "stopped"
        return "deactivated"

    def to_payload(self) -> dict[str, object]:
        return {
            "automation_enabled": self.automation_enabled,
            "queue_paused": self.queue_paused,
            "state": self.state,
            "updated_at": _as_utc(self.updated_at).isoformat().replace("+00:00", "Z"),
            "updated_by": self.updated_by,
        }


@dataclass(frozen=True)
class LibraryControl:
    repo_id: str
    enabled: bool
    paused: bool
    updated_at: datetime
    updated_by: str

    @property
    def state(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.paused:
            return "paused"
        return "active"

    @property
    def runnable(self) -> bool:
        return self.enabled and not self.paused

    def to_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "paused": self.paused,
            "state": self.state,
            "updated_at": _as_utc(self.updated_at).isoformat().replace("+00:00", "Z"),
            "updated_by": self.updated_by,
        }


class AdminControlStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def workflow(self) -> WorkflowControl:
        with self.session_factory() as session:
            row = self._workflow_row(session)
            session.commit()
            return self._workflow_snapshot(row)

    def initialize_workflow(
        self,
        initial_state: Literal["running", "stopped"],
    ) -> WorkflowControl:
        """Create the global row once without overwriting persisted operator state."""
        with self.session_factory() as session:
            self._begin_sqlite_write(session)
            self._insert_workflow_default(session, initial_state=initial_state)
            row = self._workflow_row(session, lock=True)
            session.commit()
            return self._workflow_snapshot(row)

    def update_workflow(
        self,
        *,
        updated_by: str,
        automation_enabled: bool | None = None,
        queue_paused: bool | None = None,
        audit_writer: ControlAuditWriter | None = None,
    ) -> tuple[WorkflowControl, WorkflowControl]:
        with self.session_factory() as session:
            self._begin_sqlite_write(session)
            row = self._workflow_row(session, lock=True)
            before = self._workflow_snapshot(row)
            if automation_enabled is not None:
                row.automation_enabled = automation_enabled
            if queue_paused is not None:
                row.queue_paused = queue_paused
            row.updated_at = datetime.now(UTC)
            row.updated_by = _actor(updated_by)
            after = self._workflow_snapshot(row)
            if audit_writer is not None:
                audit_writer(session, before.to_payload(), after.to_payload())
            session.commit()
            return before, after

    def library(self, repo_id: str) -> LibraryControl:
        normalized_repo_id = repo_id.strip()
        if not normalized_repo_id:
            raise ValueError("repo_id must not be empty")
        return self.libraries([normalized_repo_id])[normalized_repo_id]

    def libraries(
        self,
        repo_ids: list[str] | set[str] | tuple[str, ...],
    ) -> dict[str, LibraryControl]:
        normalized = list(
            dict.fromkeys(str(value).strip() for value in repo_ids if str(value).strip())
        )
        if not normalized:
            return {}
        with self.session_factory() as session:
            rows = {
                row.repo_id: row
                for row in session.scalars(
                    select(LibraryControlState).where(
                        LibraryControlState.repo_id.in_(normalized)
                    )
                ).all()
            }
            now = datetime.now(UTC)
            return {
                repo_id: (
                    self._library_snapshot(rows[repo_id])
                    if repo_id in rows
                    else LibraryControl(
                        repo_id=repo_id,
                        enabled=True,
                        paused=False,
                        updated_at=now,
                        updated_by="system",
                    )
                )
                for repo_id in normalized
            }

    def update_library(
        self,
        repo_id: str,
        *,
        updated_by: str,
        enabled: bool | None = None,
        paused: bool | None = None,
        audit_writer: ControlAuditWriter | None = None,
    ) -> tuple[LibraryControl, LibraryControl]:
        normalized_repo_id = repo_id.strip()
        if not normalized_repo_id:
            raise ValueError("repo_id must not be empty")
        with self.session_factory() as session:
            self._begin_sqlite_write(session)
            self._insert_library_default(session, normalized_repo_id)
            row = session.scalar(
                select(LibraryControlState)
                .where(LibraryControlState.repo_id == normalized_repo_id)
                .with_for_update()
            )
            if row is None:  # pragma: no cover - unsupported database fallback
                raise RuntimeError("library control row could not be initialized")
            before = self._library_snapshot(row)
            if enabled is not None:
                row.enabled = enabled
            if paused is not None:
                row.paused = paused
            row.updated_at = datetime.now(UTC)
            row.updated_by = _actor(updated_by)
            after = self._library_snapshot(row)
            if audit_writer is not None:
                audit_writer(session, before.to_payload(), after.to_payload())
            session.commit()
            return before, after

    def automation_enabled(self) -> bool:
        return self.workflow().automation_enabled

    def queue_paused(self) -> bool:
        return self.workflow().queue_paused

    def library_runnable(self, repo_id: str) -> bool:
        return self.library(repo_id).runnable

    @staticmethod
    def _begin_sqlite_write(session: Session) -> None:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    def _workflow_row(session: Session, *, lock: bool = False) -> WorkflowControlState:
        stmt = select(WorkflowControlState).where(
            WorkflowControlState.id == GLOBAL_CONTROL_ID
        )
        if lock:
            stmt = stmt.with_for_update()
        row = session.scalar(stmt)
        if row is None:
            AdminControlStore._insert_workflow_default(session)
            row = session.scalar(stmt)
        if row is None:  # pragma: no cover - unsupported database fallback
            raise RuntimeError("workflow control row could not be initialized")
        return row

    @staticmethod
    def _insert_workflow_default(
        session: Session,
        *,
        initial_state: Literal["running", "stopped"] = "running",
    ) -> None:
        stopped = initial_state == "stopped"
        values = {
            "id": GLOBAL_CONTROL_ID,
            "automation_enabled": not stopped,
            "queue_paused": stopped,
            "updated_at": datetime.now(UTC),
            "updated_by": "system:initial-state",
        }
        dialect_name = session.get_bind().dialect.name
        if dialect_name in {"postgresql", "sqlite"}:
            insert_factory = (
                postgresql_insert if dialect_name == "postgresql" else sqlite_insert
            )
            session.execute(
                insert_factory(WorkflowControlState)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[WorkflowControlState.id])
            )
            return
        if session.get(WorkflowControlState, GLOBAL_CONTROL_ID) is None:
            session.add(WorkflowControlState(**values))
            session.flush()

    @staticmethod
    def _insert_library_default(session: Session, repo_id: str) -> None:
        values = {
            "repo_id": repo_id,
            "enabled": True,
            "paused": False,
            "updated_at": datetime.now(UTC),
            "updated_by": "system",
        }
        dialect_name = session.get_bind().dialect.name
        if dialect_name in {"postgresql", "sqlite"}:
            insert_factory = (
                postgresql_insert if dialect_name == "postgresql" else sqlite_insert
            )
            session.execute(
                insert_factory(LibraryControlState)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[LibraryControlState.repo_id])
            )
            return
        if session.get(LibraryControlState, repo_id) is None:
            session.add(LibraryControlState(**values))
            session.flush()

    @staticmethod
    def _workflow_snapshot(row: WorkflowControlState) -> WorkflowControl:
        return WorkflowControl(
            automation_enabled=bool(row.automation_enabled),
            queue_paused=bool(row.queue_paused),
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
        )

    @staticmethod
    def _library_snapshot(row: LibraryControlState) -> LibraryControl:
        return LibraryControl(
            repo_id=row.repo_id,
            enabled=bool(row.enabled),
            paused=bool(row.paused),
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
        )
