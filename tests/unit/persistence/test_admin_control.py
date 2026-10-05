from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
from seafile_ragflow_connector.persistence import Base
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
from seafile_ragflow_connector.persistence.models.admin_control import (
    LibraryControlState,
    WorkflowControlState,
)
from seafile_ragflow_connector.persistence.models.dashboard import DashboardChangeEvent


def _store() -> AdminControlStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return AdminControlStore(
        sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    )


def test_workflow_control_defaults_and_changes_are_persistent() -> None:
    store = _store()

    initial = store.workflow()
    before, stopped = store.update_workflow(
        automation_enabled=False,
        queue_paused=True,
        updated_by="admin",
    )
    reloaded = AdminControlStore(store.session_factory).workflow()

    assert initial.automation_enabled is True
    assert initial.queue_paused is False
    assert before == initial
    assert stopped.state == "stopped"
    assert reloaded == stopped
    assert reloaded.updated_by == "admin"


def test_workflow_initial_state_is_applied_once() -> None:
    store = _store()

    stopped = store.initialize_workflow("stopped")
    preserved = store.initialize_workflow("running")

    assert stopped.state == "stopped"
    assert stopped.updated_by == "system:initial-state"
    assert preserved == stopped
    with store.session_factory() as session:
        assert len(session.scalars(select(WorkflowControlState)).all()) == 1


def test_workflow_running_initial_state_keeps_compatible_default() -> None:
    store = _store()

    running = store.initialize_workflow("running")

    assert running.state == "running"
    assert running.automation_enabled is True
    assert running.queue_paused is False


def test_workflow_initialization_never_overwrites_operator_state() -> None:
    store = _store()
    store.initialize_workflow("stopped")
    _before, running = store.update_workflow(
        updated_by="admin",
        automation_enabled=True,
        queue_paused=False,
    )

    preserved = store.initialize_workflow("stopped")

    assert running.state == "running"
    assert preserved == running
    assert preserved.updated_by == "admin"


def test_workflow_update_commits_state_and_audit_in_one_transaction() -> None:
    control_store = _store()
    event_store = DashboardEventStore(control_store.session_factory, DashboardLimits())

    def audit_writer(
        session: Session,
        before: dict[str, object],
        after: dict[str, object],
    ) -> None:
        event_store.stage_change(
            session,
            sync_id=None,
            action="dashboard.admin.pause",
            change_type="admin_global_action",
            status="pending",
            details={"before": before, "after": after},
        )

    _before, paused = control_store.update_workflow(
        updated_by="admin",
        queue_paused=True,
        audit_writer=audit_writer,
    )

    with control_store.session_factory() as session:
        event = session.scalar(select(DashboardChangeEvent))
        assert event is not None
        assert event.details["before"]["state"] == "running"
        assert event.details["after"]["state"] == "paused"
    assert paused.state == "paused"


def test_workflow_update_rolls_back_when_audit_writer_fails() -> None:
    control_store = _store()
    initial = control_store.workflow()
    event_store = DashboardEventStore(control_store.session_factory, DashboardLimits())

    def failing_writer(
        session: Session,
        before: dict[str, object],
        after: dict[str, object],
    ) -> None:
        event_store.stage_change(
            session,
            sync_id=None,
            action="dashboard.admin.pause",
            change_type="admin_global_action",
            status="pending",
            details={"before": before, "after": after},
        )
        raise RuntimeError("audit unavailable")

    try:
        control_store.update_workflow(
            updated_by="admin",
            queue_paused=True,
            audit_writer=failing_writer,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("audit failure must abort the control update")

    assert control_store.workflow() == initial
    with control_store.session_factory() as session:
        assert session.scalar(select(DashboardChangeEvent)) is None


def test_library_update_rolls_back_default_row_when_audit_writer_fails() -> None:
    control_store = _store()

    def failing_writer(
        _session: Session,
        _before: dict[str, object],
        _after: dict[str, object],
    ) -> None:
        raise RuntimeError("audit unavailable")

    try:
        control_store.update_library(
            "new-library",
            updated_by="admin",
            paused=True,
            audit_writer=failing_writer,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("audit failure must abort the control update")

    with control_store.session_factory() as session:
        assert session.get(LibraryControlState, "new-library") is None


def test_library_defaults_are_read_only_until_an_admin_change() -> None:
    store = _store()

    default = store.library("not-yet-discovered")
    with store.session_factory() as session:
        assert session.scalar(select(LibraryControlState)) is None

    before, paused = store.update_library(
        "not-yet-discovered",
        paused=True,
        updated_by="operator",
    )

    assert before.state == "active"
    assert default.state == "active"
    assert paused.state == "paused"
    assert store.library("not-yet-discovered") == paused
    assert store.library("  not-yet-discovered  ") == paused


def test_library_rejects_an_empty_repo_id() -> None:
    store = _store()

    try:
        store.library("  ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty repo_id must be rejected")
