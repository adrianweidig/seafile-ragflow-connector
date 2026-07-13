from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.jobs.types import JobType
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
from seafile_ragflow_connector.sync.delta_sync import SnapshotEntry
from seafile_ragflow_connector.sync.reconcile import Reconciler


class _RAGFlow:
    def iter_documents(self, dataset_id: str):
        return [{"id": "remote-present", "run": "DONE"}]


def _source(path: str, object_id: str) -> SnapshotEntry:
    return SnapshotEntry(path, path, object_id, 1, 1, False, {})


def test_reconcile_builds_conservative_plan_from_source_local_and_target_state() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add(Library(repo_id="repo", name="Demo", name_slug="demo"))
        missing_target = File(
            repo_id="repo",
            path="/missing-target.pdf",
            normalized_path="/missing-target.pdf",
            ragflow_document_id="remote-missing",
        )
        missing_source = File(
            repo_id="repo",
            path="/removed.pdf",
            normalized_path="/removed.pdf",
            ragflow_document_id="remote-present",
        )
        session.add_all([missing_target, missing_source])
        session.flush()
        session.add(
            FileDocumentVersion(
                file_id=missing_target.id,
                repo_id="repo",
                normalized_path=missing_target.normalized_path,
                dataset_id="dataset",
                document_id="pending-doc",
                document_name="missing-target.pdf",
                state="parsing",
            )
        )
        session.commit()

    plan = Reconciler(factory, _RAGFlow()).plan_library_reconcile(
        "repo",
        "dataset",
        source_entries=[
            _source("/missing-target.pdf", "obj-a"),
            _source("/new.pdf", "obj-b"),
        ],
    )

    assert plan.has_drift
    assert plan.categories["missing_local_state"] == [
        {"path": "/new.pdf", "object_id": "obj-b"}
    ]
    assert plan.categories["missing_source"] == [{"path": "/removed.pdf"}]
    assert plan.categories["missing_target"] == [
        {"path": "/missing-target.pdf", "document_id": "remote-missing"}
    ]
    assert plan.categories["parse_stuck"][0]["document_id"] == "pending-doc"
    assert [job.job_type for job in plan.jobs] == [
        JobType.UPLOAD_FILE,
        JobType.DELETE_FILE,
        JobType.UPLOAD_FILE,
        JobType.CHECK_PARSE_STATUS,
    ]
