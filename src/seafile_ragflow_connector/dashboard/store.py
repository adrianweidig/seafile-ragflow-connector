from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.jobs.types import JobStatus
from seafile_ragflow_connector.persistence.models.dashboard import (
    DashboardChangeEvent,
    DashboardLogEntry,
    DashboardSyncRun,
)
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.job import SyncJob
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.utils.redaction import redact_mapping

MAX_LIMIT = 500
DEFAULT_FIELD_LIMIT = 4000


@dataclass(frozen=True)
class DashboardLimits:
    max_sync_runs: int = 1000
    max_event_entries: int = 10000
    max_log_entries: int = 5000
    page_size: int = 100
    max_field_length: int = DEFAULT_FIELD_LIMIT


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_sync_id(repo_id: str | None = None) -> str:
    prefix = "sync"
    if repo_id:
        prefix = f"{prefix}-{repo_id.replace('-', '')[:8]}"
    return f"{prefix}-{utcnow().strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"


def isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def clamp_limit(value: int | None, default: int, *, maximum: int = MAX_LIMIT) -> int:
    if value is None or value <= 0:
        return min(default, maximum)
    return min(value, maximum)


def clamp_offset(value: int | None) -> int:
    if value is None or value < 0:
        return 0
    return value


def safe_text(value: Any, *, max_length: int = DEFAULT_FIELD_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def safe_json(value: Any, *, max_length: int = DEFAULT_FIELD_LIMIT) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = {"value": value}
    redacted = redact_mapping(value)
    try:
        encoded = json.dumps(redacted, ensure_ascii=False, default=str)
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return {"value": safe_text(redacted, max_length=max_length)}
    return _truncate_json(decoded, max_length=max_length)


def _truncate_json(value: Any, *, max_length: int) -> Any:
    if isinstance(value, str):
        return safe_text(value, max_length=max_length)
    if isinstance(value, list):
        return [_truncate_json(item, max_length=max_length) for item in value[:50]]
    if isinstance(value, dict):
        return {
            str(key): _truncate_json(item, max_length=max_length)
            for key, item in list(value.items())[:100]
        }
    return value


class DashboardEventStore:
    def __init__(self, session_factory: sessionmaker[Session], limits: DashboardLimits) -> None:
        self.session_factory = session_factory
        self.limits = limits

    def create_sync_run(
        self,
        *,
        sync_id: str,
        source: str,
        target: str,
        summary: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        started_at = utcnow()
        with self._session() as session:
            session.merge(
                DashboardSyncRun(
                    sync_id=sync_id,
                    source=source,
                    target=target,
                    status="running",
                    summary=safe_text(summary, max_length=self.limits.max_field_length),
                    started_at=started_at,
                    details=safe_json(details or {}, max_length=self.limits.max_field_length),
                )
            )
            session.commit()
            self._prune_table(
                session,
                DashboardSyncRun,
                DashboardSyncRun.sync_id,
                DashboardSyncRun.started_at,
                self.limits.max_sync_runs,
            )

    def finish_sync_run(
        self,
        *,
        sync_id: str,
        status: str,
        objects_checked: int,
        objects_created: int,
        objects_updated: int,
        objects_deleted: int,
        objects_skipped: int,
        errors_count: int = 0,
        warnings_count: int = 0,
        summary: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        ended_at = utcnow()
        with self._session() as session:
            run = session.get(DashboardSyncRun, sync_id)
            if run is None:
                return
            run.status = status
            run.ended_at = ended_at
            started_at = run.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            run.duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            run.objects_checked = objects_checked
            run.objects_created = objects_created
            run.objects_updated = objects_updated
            run.objects_deleted = objects_deleted
            run.objects_skipped = objects_skipped
            run.errors_count = errors_count
            run.warnings_count = warnings_count
            if summary is not None:
                run.summary = safe_text(summary, max_length=self.limits.max_field_length)
            if details is not None:
                run.details = safe_json(details, max_length=self.limits.max_field_length)
            session.commit()

    def record_change(
        self,
        *,
        sync_id: str | None,
        action: str,
        change_type: str,
        status: str,
        object_name: str | None = None,
        source_path: str | None = None,
        target_path: str | None = None,
        previous_name: str | None = None,
        new_name: str | None = None,
        error_message: str | None = None,
        source_system: str = "seafile",
        target_system: str = "ragflow",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            session.add(
                DashboardChangeEvent(
                    sync_id=sync_id,
                    occurred_at=utcnow(),
                    action=safe_text(action, max_length=128) or "",
                    object_name=safe_text(object_name, max_length=self.limits.max_field_length),
                    source_path=safe_text(source_path, max_length=self.limits.max_field_length),
                    target_path=safe_text(target_path, max_length=self.limits.max_field_length),
                    previous_name=safe_text(previous_name, max_length=self.limits.max_field_length),
                    new_name=safe_text(new_name, max_length=self.limits.max_field_length),
                    change_type=safe_text(change_type, max_length=128) or "unknown",
                    status=safe_text(status, max_length=128) or "unknown",
                    error_message=safe_text(error_message, max_length=self.limits.max_field_length),
                    source_system=source_system,
                    target_system=target_system,
                    details=safe_json(details or {}, max_length=self.limits.max_field_length),
                )
            )
            session.commit()
            self._prune_table(
                session,
                DashboardChangeEvent,
                DashboardChangeEvent.id,
                DashboardChangeEvent.occurred_at,
                self.limits.max_event_entries,
            )

    def record_log(
        self,
        *,
        level: str,
        message: str,
        component: str | None = None,
        sync_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            session.add(
                DashboardLogEntry(
                    occurred_at=utcnow(),
                    level=(safe_text(level, max_length=64) or "info").lower(),
                    component=safe_text(component, max_length=255),
                    message=safe_text(message, max_length=self.limits.max_field_length) or "",
                    sync_id=safe_text(sync_id, max_length=255),
                    details=safe_json(details or {}, max_length=self.limits.max_field_length),
                )
            )
            session.commit()
            self._prune_table(
                session,
                DashboardLogEntry,
                DashboardLogEntry.id,
                DashboardLogEntry.occurred_at,
                self.limits.max_log_entries,
            )

    def connector_status(self, *, started_at: datetime) -> dict[str, Any]:
        try:
            with self._session() as session:
                running_jobs = self._count(
                    session,
                    SyncJob,
                    SyncJob.status == JobStatus.RUNNING.value,
                )
                queued_jobs = self._count(
                    session,
                    SyncJob,
                    SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]),
                )
                failed_jobs = self._count(session, SyncJob, SyncJob.status == JobStatus.DEAD.value)
                errors = self._count(
                    session,
                    DashboardLogEntry,
                    DashboardLogEntry.level.in_(["error", "critical"]),
                )
                warnings = self._count(
                    session,
                    DashboardLogEntry,
                    DashboardLogEntry.level == "warning",
                )
                changes = self._count(session, DashboardChangeEvent)
                processed = self._sum_runs(session, "objects_checked")
                last_success = self._last_run(session, "succeeded")
                last_failed = self._last_run(session, "failed")
                state = "synchronisiert gerade" if running_jobs else "wartend"
                if failed_jobs:
                    state = "fehlerhaft"
                return {
                    "state": state,
                    "started_at": isoformat(started_at),
                    "uptime_seconds": int((utcnow() - started_at).total_seconds()),
                    "running_jobs": running_jobs,
                    "queued_or_retrying_jobs": queued_jobs,
                    "failed_jobs": failed_jobs,
                    "last_successful_sync": last_success,
                    "last_failed_sync": last_failed,
                    "objects_processed": processed,
                    "changes_detected": changes,
                    "errors_count": errors,
                    "warnings_count": warnings,
                }
        except SQLAlchemyError as exc:
            return {
                "state": "unbekannt",
                "started_at": isoformat(started_at),
                "uptime_seconds": int((utcnow() - started_at).total_seconds()),
                "error": safe_text(exc, max_length=self.limits.max_field_length),
            }

    def metrics(self) -> dict[str, Any]:
        with self._session() as session:
            return {
                "libraries": self._count(session, Library),
                "files": self._count(session, File),
                "sync_runs": self._count(session, DashboardSyncRun),
                "changes": self._count(session, DashboardChangeEvent),
                "logs": self._count(session, DashboardLogEntry),
                "jobs_by_status": self._group_count(session, SyncJob.status),
                "files_by_status": self._group_count(session, File.sync_status),
            }

    def systems(self) -> dict[str, Any]:
        with self._session() as session:
            libraries = session.scalars(
                select(Library).order_by(Library.name.asc()).limit(200)
            ).all()
            return {
                "source": {
                    "name": "Seafile",
                    "libraries": [
                        {
                            "repo_id": library.repo_id,
                            "name": library.name,
                            "status": library.status,
                            "last_error": library.last_error,
                            "head_commit_id": library.head_commit_id,
                            "last_synced_commit_id": library.last_synced_commit_id,
                        }
                        for library in libraries
                    ],
                },
                "target": {
                    "name": "RAGFlow",
                    "datasets": [
                        {
                            "repo_id": library.repo_id,
                            "dataset_id": library.ragflow_dataset_id,
                            "dataset_name": library.ragflow_dataset_name,
                            "template_hash": library.template_hash,
                        }
                        for library in libraries
                    ],
                },
            }

    def list_sync_runs(
        self,
        *,
        status: str | None,
        limit: int | None,
        offset: int | None,
    ) -> dict[str, Any]:
        limit_value = clamp_limit(limit, self.limits.page_size)
        offset_value = clamp_offset(offset)
        with self._session() as session:
            stmt = select(DashboardSyncRun)
            count_stmt = select(func.count()).select_from(DashboardSyncRun)
            if status:
                stmt = stmt.where(DashboardSyncRun.status == status)
                count_stmt = count_stmt.where(DashboardSyncRun.status == status)
            stmt = (
                stmt.order_by(DashboardSyncRun.started_at.desc())
                .limit(limit_value)
                .offset(offset_value)
            )
            runs = session.scalars(stmt).all()
            total = int(session.scalar(count_stmt) or 0)
            return self._page(
                [serialize_sync_run(run) for run in runs],
                total,
                limit_value,
                offset_value,
            )

    def get_sync_run(self, sync_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            run = session.get(DashboardSyncRun, sync_id)
            if run is None:
                return None
            changes = session.scalars(
                select(DashboardChangeEvent)
                .where(DashboardChangeEvent.sync_id == sync_id)
                .order_by(DashboardChangeEvent.occurred_at.asc())
                .limit(MAX_LIMIT)
            ).all()
            logs = session.scalars(
                select(DashboardLogEntry)
                .where(DashboardLogEntry.sync_id == sync_id)
                .order_by(DashboardLogEntry.occurred_at.asc())
                .limit(MAX_LIMIT)
            ).all()
            return {
                **serialize_sync_run(run),
                "changes": [serialize_change(event) for event in changes],
                "logs": [serialize_log(entry) for entry in logs],
            }

    def list_changes(
        self,
        *,
        sync_id: str | None,
        status: str | None,
        change_type: str | None,
        query: str | None,
        limit: int | None,
        offset: int | None,
    ) -> dict[str, Any]:
        limit_value = clamp_limit(limit, self.limits.page_size)
        offset_value = clamp_offset(offset)
        with self._session() as session:
            stmt = select(DashboardChangeEvent)
            count_stmt = select(func.count()).select_from(DashboardChangeEvent)
            filters = []
            if sync_id:
                filters.append(DashboardChangeEvent.sync_id == sync_id)
            if status:
                filters.append(DashboardChangeEvent.status == status)
            if change_type:
                filters.append(DashboardChangeEvent.change_type == change_type)
            if query:
                like = f"%{query}%"
                filters.append(
                    or_(
                        DashboardChangeEvent.object_name.ilike(like),
                        DashboardChangeEvent.source_path.ilike(like),
                        DashboardChangeEvent.target_path.ilike(like),
                        DashboardChangeEvent.error_message.ilike(like),
                    )
                )
            for item in filters:
                stmt = stmt.where(item)
                count_stmt = count_stmt.where(item)
            stmt = (
                stmt.order_by(DashboardChangeEvent.occurred_at.desc())
                .limit(limit_value)
                .offset(offset_value)
            )
            total = int(session.scalar(count_stmt) or 0)
            return self._page(
                [serialize_change(event) for event in session.scalars(stmt).all()],
                total,
                limit_value,
                offset_value,
            )

    def list_logs(
        self,
        *,
        level: str | None,
        sync_id: str | None,
        query: str | None,
        limit: int | None,
        offset: int | None,
    ) -> dict[str, Any]:
        limit_value = clamp_limit(limit, self.limits.page_size)
        offset_value = clamp_offset(offset)
        with self._session() as session:
            stmt = select(DashboardLogEntry)
            count_stmt = select(func.count()).select_from(DashboardLogEntry)
            filters = []
            if level:
                filters.append(DashboardLogEntry.level == level.lower())
            if sync_id:
                filters.append(DashboardLogEntry.sync_id == sync_id)
            if query:
                like = f"%{query}%"
                filters.append(
                    or_(
                        DashboardLogEntry.message.ilike(like),
                        DashboardLogEntry.component.ilike(like),
                    )
                )
            for item in filters:
                stmt = stmt.where(item)
                count_stmt = count_stmt.where(item)
            stmt = (
                stmt.order_by(DashboardLogEntry.occurred_at.desc())
                .limit(limit_value)
                .offset(offset_value)
            )
            total = int(session.scalar(count_stmt) or 0)
            return self._page(
                [serialize_log(entry) for entry in session.scalars(stmt).all()],
                total,
                limit_value,
                offset_value,
            )

    def diagnostics(self, safe_config: Mapping[str, Any]) -> dict[str, Any]:
        with self._session() as session:
            return {
                "configuration": safe_json(safe_config, max_length=self.limits.max_field_length),
                "limits": {
                    "max_sync_runs": self.limits.max_sync_runs,
                    "max_event_entries": self.limits.max_event_entries,
                    "max_log_entries": self.limits.max_log_entries,
                    "page_size": self.limits.page_size,
                    "max_field_length": self.limits.max_field_length,
                },
                "database": {
                    "libraries": self._count(session, Library),
                    "files": self._count(session, File),
                    "jobs": self._count(session, SyncJob),
                    "dashboard_sync_runs": self._count(session, DashboardSyncRun),
                    "dashboard_change_events": self._count(session, DashboardChangeEvent),
                    "dashboard_log_entries": self._count(session, DashboardLogEntry),
                },
            }

    def _session(self) -> Session:
        return self.session_factory()

    def _prune_table(
        self,
        session: Session,
        model: Any,
        key_column: Any,
        order_column: Any,
        keep: int,
    ) -> None:
        if keep <= 0:
            return
        stale_ids = session.scalars(
            select(key_column).order_by(order_column.desc()).offset(keep)
        ).all()
        if stale_ids:
            session.execute(delete(model).where(key_column.in_(stale_ids)))
            session.commit()

    @staticmethod
    def _count(session: Session, model: Any, *filters: Any) -> int:
        stmt = select(func.count()).select_from(model)
        for item in filters:
            stmt = stmt.where(item)
        return int(session.scalar(stmt) or 0)

    @staticmethod
    def _group_count(session: Session, column: Any) -> dict[str, int]:
        rows = session.execute(select(column, func.count()).group_by(column)).all()
        return {str(key): int(value) for key, value in rows}

    @staticmethod
    def _sum_runs(session: Session, column_name: str) -> int:
        column = getattr(DashboardSyncRun, column_name)
        return int(session.scalar(select(func.coalesce(func.sum(column), 0))) or 0)

    @staticmethod
    def _last_run(session: Session, status: str) -> dict[str, Any] | None:
        run = session.scalar(
            select(DashboardSyncRun)
            .where(DashboardSyncRun.status == status)
            .order_by(DashboardSyncRun.ended_at.desc())
            .limit(1)
        )
        return serialize_sync_run(run) if run else None

    @staticmethod
    def _page(items: list[dict[str, Any]], total: int, limit: int, offset: int) -> dict[str, Any]:
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_next": offset + limit < total,
        }


def serialize_sync_run(run: DashboardSyncRun) -> dict[str, Any]:
    return {
        "sync_id": run.sync_id,
        "source": run.source,
        "target": run.target,
        "status": run.status,
        "summary": run.summary,
        "started_at": isoformat(run.started_at),
        "ended_at": isoformat(run.ended_at),
        "duration_ms": run.duration_ms,
        "objects_checked": run.objects_checked,
        "objects_created": run.objects_created,
        "objects_updated": run.objects_updated,
        "objects_deleted": run.objects_deleted,
        "objects_skipped": run.objects_skipped,
        "errors_count": run.errors_count,
        "warnings_count": run.warnings_count,
        "details": run.details or {},
    }


def serialize_change(event: DashboardChangeEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "sync_id": event.sync_id,
        "occurred_at": isoformat(event.occurred_at),
        "action": event.action,
        "object_name": event.object_name,
        "source_path": event.source_path,
        "target_path": event.target_path,
        "previous_name": event.previous_name,
        "new_name": event.new_name,
        "change_type": event.change_type,
        "status": event.status,
        "error_message": event.error_message,
        "source_system": event.source_system,
        "target_system": event.target_system,
        "details": event.details or {},
    }


def serialize_log(entry: DashboardLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "occurred_at": isoformat(entry.occurred_at),
        "level": entry.level,
        "component": entry.component,
        "message": entry.message,
        "sync_id": entry.sync_id,
        "details": entry.details or {},
    }
