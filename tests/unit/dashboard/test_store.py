from __future__ import annotations

import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.dashboard.store import (
        DashboardEventStore,
        DashboardLimits,
        safe_json,
        utcnow,
    )
    from seafile_ragflow_connector.jobs.types import JobStatus, JobType
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models import DashboardLogEntry, SyncJob
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
    create_engine = None  # type: ignore[assignment]


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class DashboardEventStoreTests(unittest.TestCase):
    def test_log_history_is_bounded_filterable_and_paginated(self) -> None:
        session_factory = _session_factory(self)
        store = DashboardEventStore(
            session_factory,
            DashboardLimits(max_log_entries=3, page_size=2, max_field_length=40),
        )

        for index in range(5):
            store.record_log(
                level="error" if index == 3 else "info",
                message=f"entry-{index}",
                component="unit",
                sync_id="sync-a" if index >= 2 else "sync-old",
            )

        page = store.list_logs(level=None, sync_id=None, query=None, limit=2, offset=0)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["limit"], 2)
        self.assertTrue(page["has_next"])
        self.assertEqual([item["message"] for item in page["items"]], ["entry-4", "entry-3"])

        filtered = store.list_logs(level="error", sync_id="sync-a", query=None, limit=10, offset=0)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["message"], "entry-3")

        with session_factory() as session:
            self.assertEqual(session.query(DashboardLogEntry).count(), 3)

    def test_sync_runs_and_changes_are_bounded(self) -> None:
        session_factory = _session_factory(self)
        store = DashboardEventStore(
            session_factory,
            DashboardLimits(max_sync_runs=2, max_event_entries=2, page_size=100),
        )

        for index in range(4):
            sync_id = f"sync-{index}"
            store.create_sync_run(
                sync_id=sync_id,
                source="seafile:repo",
                target="ragflow:dataset",
                summary="running",
            )
            store.finish_sync_run(
                sync_id=sync_id,
                status="succeeded",
                objects_checked=index,
                objects_created=index,
                objects_updated=0,
                objects_deleted=0,
                objects_skipped=0,
                summary="done",
            )
            store.record_change(
                sync_id=sync_id,
                action="upload_file",
                change_type="created",
                status="synced",
                object_name=f"file-{index}.txt",
                source_path=f"/file-{index}.txt",
                target_path=f"dataset/doc-{index}",
            )

        runs = store.list_sync_runs(status=None, limit=10, offset=0)
        changes = store.list_changes(
            sync_id=None,
            status=None,
            change_type=None,
            query=None,
            limit=10,
            offset=0,
        )

        self.assertEqual(runs["total"], 2)
        self.assertEqual(changes["total"], 2)

    def test_long_log_messages_are_truncated_and_details_are_redacted(self) -> None:
        session_factory = _session_factory(self)
        store = DashboardEventStore(
            session_factory,
            DashboardLimits(max_log_entries=10, max_field_length=10),
        )

        store.record_log(
            level="error",
            message="x" * 50,
            component="unit",
            details={"api_key": "secret", "message": "y" * 50},
        )

        logs = store.list_logs(level="error", sync_id=None, query=None, limit=1, offset=0)

        self.assertEqual(logs["items"][0]["message"], "xxxxxxxxx…")
        self.assertEqual(logs["items"][0]["details"]["api_key"], "***")
        self.assertEqual(logs["items"][0]["details"]["message"], "yyyyyyyyy…")

    def test_safe_json_masks_secrets_and_truncates_long_values(self) -> None:
        data = safe_json(
            {
                "api_key": "secret",
                "nested": {"password": "pw"},
                "message": "abcdef",
            },
            max_length=5,
        )

        self.assertEqual(data["api_key"], "***")
        self.assertEqual(data["nested"]["password"], "***")
        self.assertEqual(data["message"], "abcd…")

    def test_dead_job_cleanup_marks_jobs_cancelled_and_clears_maintenance_state(self) -> None:
        session_factory = _session_factory(self)
        store = DashboardEventStore(session_factory, DashboardLimits())
        with session_factory() as session:
            session.add(
                SyncJob(
                    job_type=JobType.SYNC_LIBRARY_FULL.value,
                    repo_id="repo-1",
                    payload={},
                    status=JobStatus.DEAD.value,
                    error_message="old failure",
                )
            )
            session.commit()

        before = store.connector_status(started_at=utcnow())
        result = store.cleanup_dead_jobs()
        after = store.connector_status(started_at=utcnow())

        self.assertEqual(before["state"], "wartung erforderlich")
        self.assertEqual(before["failed_jobs"], 1)
        self.assertEqual(result["cleaned_jobs"], 1)
        self.assertEqual(result["remaining_dead_jobs"], 0)
        self.assertEqual(after["state"], "wartend")
        self.assertEqual(after["failed_jobs"], 0)
        with session_factory() as session:
            job = session.query(SyncJob).one()
            self.assertEqual(job.status, JobStatus.CANCELLED.value)
            log = session.query(DashboardLogEntry).one()
            self.assertEqual(log.message, "dead_jobs.cleaned")
            self.assertEqual(log.details["cleaned_jobs"], 1)


if __name__ == "__main__":
    unittest.main()
