from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import typer
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.app.cli import (
    _active_dataset_bindings,
    _build_job_handlers,
    _cleanup_outbox_payload,
    _cleanup_status_filter,
    _discover_job_specs,
    _emit_job_result,
    _ensure_search_answer_chat,
    _exit_for_invalid_configuration,
    _format_payload,
    _guard_job_handler,
    _job_payload,
    _job_status_filter,
    _standalone_dashboard_context,
    _sync_openwebui_controller_guarded,
    _sync_openwebui_if_enabled,
    _wait_for_parse,
    check_config,
    check_live,
    controller,
)
from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
from seafile_ragflow_connector.jobs.context import (
    JobDeferredError,
    activate_job_execution,
    activate_job_pause,
)
from seafile_ragflow_connector.jobs.job_store import JobStore
from seafile_ragflow_connector.jobs.types import JobSpec, JobStatus, JobType
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.sync_state import FileDocumentVersion
from seafile_ragflow_connector.persistence.sync_state import SyncStateStore
from seafile_ragflow_connector.sync.orchestrator import SyncCancelledError


class _RequiredConfiguration(BaseModel):
    required_value: str


class _FakeInteractiveRAGFlowClient:
    def __init__(self) -> None:
        self.chats: list[dict[str, object]] = []
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    def list_chats(self, *, name: str | None = None):
        if name:
            return [chat for chat in self.chats if chat.get("name") == name]
        return list(self.chats)

    def create_chat(self, payload: dict[str, object]):
        self.created.append(payload)
        created = {"id": "chat-1", **payload}
        self.chats.append(created)
        return created

    def update_chat(self, chat_id: str, payload: dict[str, object]):
        self.updated.append((chat_id, payload))
        updated = {"id": chat_id, **payload}
        self.chats = [updated if chat.get("id") == chat_id else chat for chat in self.chats]
        return updated


class _FakeOrchestrator:
    def __init__(
        self,
        *,
        automation_enabled: bool = True,
        queue_paused: bool = False,
        library_runnable: bool = True,
    ) -> None:
        self.admin_control_store = _FakeAdminControlStore(
            automation_enabled=automation_enabled,
            queue_paused=queue_paused,
            library_runnable=library_runnable,
        )
        self.full_syncs: list[tuple[str, str]] = []

    def discover_job_specs(self) -> list[JobSpec]:
        return [JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo-1")]

    def sync_library_full(self, repo_id: str, *, scope: str = "/") -> None:
        self.full_syncs.append((repo_id, scope))


class _FakeAdminControlStore:
    def __init__(
        self,
        *,
        automation_enabled: bool,
        queue_paused: bool,
        library_runnable: bool,
    ) -> None:
        self.automation_enabled = automation_enabled
        self.queue_paused = queue_paused
        self.library_runnable = library_runnable

    def workflow(self):
        state = (
            "paused"
            if self.automation_enabled and self.queue_paused
            else "stopped"
            if self.queue_paused
            else "running"
            if self.automation_enabled
            else "deactivated"
        )
        return SimpleNamespace(
            automation_enabled=self.automation_enabled,
            queue_paused=self.queue_paused,
            state=state,
        )

    def library(self, repo_id: str):
        _ = repo_id
        return SimpleNamespace(
            runnable=self.library_runnable,
            state="active" if self.library_runnable else "paused",
        )


class _FakeOpenWebUIService:
    def __init__(self) -> None:
        self.calls = 0
        self.repo_ids: list[set[str] | None] = []

    def sync_once(self, **kwargs):
        self.calls += 1
        self.repo_ids.append(kwargs.get("repo_ids"))
        return SimpleNamespace(datasets_seen=1, tools_created=1, pipes_created=1)


class _FailingOpenWebUIService:
    def __init__(self) -> None:
        self.calls = 0

    def sync_once(self):
        self.calls += 1
        raise ConnectionError("ragflow unavailable")


class _FakeLog:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object]]] = []
        self.infos: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.warnings.append((event, kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self.infos.append((event, kwargs))


class _ParseWaitOrchestrator:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.checked: list[tuple[str, str]] = []
        self.discover_called = False
        self.ensure_called = False

    def discover_libraries(self):
        self.discover_called = True
        return []

    def ensure_dataset_for_repo(self, repo_id: str) -> str:
        self.ensure_called = True
        return f"dataset-{repo_id}"

    def check_parse_status(self, repo_id: str, dataset_id: str) -> int:
        self.checked.append((repo_id, dataset_id))
        return 1


class _ParseWaitRAGFlow:
    def __init__(self, runs: dict[str, str] | None = None) -> None:
        self.runs = runs or {}

    def iter_documents(self, dataset_id: str):
        return iter(
            [
                {
                    "id": f"doc-{dataset_id}",
                    "run": self.runs.get(dataset_id, "DONE"),
                }
            ]
        )


def _runtime(
    mode: str,
    service: _FakeOpenWebUIService | None = None,
    *,
    automation_enabled: bool = True,
    queue_paused: bool = False,
    library_runnable: bool = True,
):
    return SimpleNamespace(
        settings=SimpleNamespace(openwebui_effective_sync_mode=mode),
        orchestrator=_FakeOrchestrator(
            automation_enabled=automation_enabled,
            queue_paused=queue_paused,
            library_runnable=library_runnable,
        ),
        openwebui_sync_service=service,
    )


def _test_session_factory(test_case: unittest.TestCase):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class CliSyncHelpersTests(unittest.TestCase):
    def test_check_live_verifies_interactive_owner_and_filtered_reads(self) -> None:
        settings = SimpleNamespace(
            database_url="sqlite://",
            redis_url="redis://local",
            ragflow_template_dataset_name="connector_template",
            ragflow_interactive_api_key="interactive-token",
        )
        calls: list[str] = []
        interactive = SimpleNamespace(
            verify_artifact_owner=lambda: calls.append("verify"),
            list_chats=lambda: calls.append("chats") or [{"id": "chat-1"}],
            list_searches=lambda: calls.append("searches") or [{"id": "search-1"}],
        )
        closed: list[bool] = []
        runtime = SimpleNamespace(
            admin_client=SimpleNamespace(list_libraries=lambda per_page: ["library"]),
            ragflow_client=SimpleNamespace(list_datasets=lambda name: [{"id": "dataset"}]),
            interactive_ragflow_client=interactive,
            close=lambda: closed.append(True),
        )

        with (
            patch("seafile_ragflow_connector.app.cli._bootstrap", return_value=settings),
            patch("seafile_ragflow_connector.app.cli.check_database"),
            patch("seafile_ragflow_connector.app.cli.check_redis"),
            patch(
                "seafile_ragflow_connector.app.cli.database_revisions",
                return_value=("head", "head"),
            ),
            patch("seafile_ragflow_connector.app.cli.build_runtime", return_value=runtime),
            patch(
                "seafile_ragflow_connector.app.cli._retry_until",
                side_effect=lambda action, _label: action(),
            ),
            patch("seafile_ragflow_connector.app.cli._emit_payload") as emit,
        ):
            check_live(json_output=True)

        payload = emit.call_args.args[0]
        self.assertEqual(calls, ["verify", "chats", "searches"])
        self.assertTrue(payload["ragflow_interactive_owner_verified"])
        self.assertEqual(payload["ragflow_interactive_chats_visible"], 1)
        self.assertEqual(payload["ragflow_interactive_searches_visible"], 1)
        self.assertNotIn("ragflow_interactive_api_key", payload)
        self.assertEqual(closed, [True])

    def test_check_live_fails_closed_on_interactive_owner_mismatch(self) -> None:
        settings = SimpleNamespace(
            database_url="sqlite://",
            redis_url="redis://local",
            ragflow_template_dataset_name="connector_template",
            ragflow_interactive_api_key="interactive-token",
        )

        def reject_owner() -> None:
            raise ApiError("owner mismatch", status_code=200)

        closed: list[bool] = []
        runtime = SimpleNamespace(
            admin_client=SimpleNamespace(list_libraries=lambda per_page: ["library"]),
            ragflow_client=SimpleNamespace(list_datasets=lambda name: [{"id": "dataset"}]),
            interactive_ragflow_client=SimpleNamespace(
                verify_artifact_owner=reject_owner,
                list_chats=lambda: [],
                list_searches=lambda: [],
            ),
            close=lambda: closed.append(True),
        )
        with (
            patch("seafile_ragflow_connector.app.cli._bootstrap", return_value=settings),
            patch("seafile_ragflow_connector.app.cli.check_database"),
            patch("seafile_ragflow_connector.app.cli.check_redis"),
            patch(
                "seafile_ragflow_connector.app.cli.database_revisions",
                return_value=("head", "head"),
            ),
            patch("seafile_ragflow_connector.app.cli.build_runtime", return_value=runtime),
            patch(
                "seafile_ragflow_connector.app.cli._retry_until",
                side_effect=lambda action, _label: action(),
            ),
            self.assertRaisesRegex(ApiError, "owner mismatch"),
        ):
            check_live(json_output=True)

        self.assertEqual(closed, [True])

    def test_search_answer_chat_uses_interactive_client_and_model(self) -> None:
        primary = _FakeInteractiveRAGFlowClient()
        interactive = _FakeInteractiveRAGFlowClient()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(
                search_answer_generation_mode="ragflow_chat",
                ragflow_search_answer_chat_auto_create=True,
                ragflow_search_answer_chat_name="connector_search_answer",
                ragflow_interactive_chat_model_id="model@provider",
            ),
            ragflow_client=primary,
            interactive_ragflow_client=interactive,
        )
        log = SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )

        _ensure_search_answer_chat(runtime, log)  # type: ignore[arg-type]

        self.assertEqual(primary.created, [])
        self.assertEqual(len(interactive.created), 1)
        self.assertEqual(interactive.created[0]["llm_id"], "model@provider")

    def test_standalone_dashboard_initializes_configured_control_state_once(self) -> None:
        session_factory = _test_session_factory(self)
        store = DashboardEventStore(session_factory, DashboardLimits())

        context = _standalone_dashboard_context(
            store,
            SimpleNamespace(connector_automation_initial_state="stopped"),  # type: ignore[arg-type]
        )

        assert context.control_store is not None
        self.assertEqual(context.control_store.workflow().state, "stopped")

        second = _standalone_dashboard_context(
            store,
            SimpleNamespace(connector_automation_initial_state="running"),  # type: ignore[arg-type]
        )
        assert second.control_store is not None
        self.assertEqual(second.control_store.workflow().state, "stopped")

    def test_check_config_exposes_automation_initial_state(self) -> None:
        settings = SimpleNamespace(
            app_env="test",
            seafile_base_url="https://seafile.test",
            ragflow_base_url="https://ragflow.test",
            allow_unknown_text_files=False,
            dataset_settings_source="template",
            connector_dashboard_enabled=True,
            connector_dashboard_control_enabled=True,
            connector_automation_initial_state="stopped",
            connector_dashboard_host="127.0.0.1",
            connector_dashboard_port=8787,
            authz_api_enabled=False,
            authz_api_fail_closed=True,
            authz_api_max_acl_age_seconds=3600,
            search_acl_sync_enabled=False,
            search_acl_sync_interval_seconds=300,
            openwebui_integration_enabled=False,
            openwebui_effective_sync_mode="disabled",
            openwebui_base_url="https://openwebui.test",
            openwebui_create_tools=False,
            openwebui_create_pipes=False,
            openwebui_authz_enabled=False,
        )

        with (
            patch("seafile_ragflow_connector.app.cli._bootstrap", return_value=settings),
            patch(
                "seafile_ragflow_connector.app.cli.localizer_for",
                return_value=SimpleNamespace(language="de"),
            ),
            patch("seafile_ragflow_connector.app.cli._emit_payload") as emit,
        ):
            check_config(json_output=True)

        payload = emit.call_args.args[0]
        self.assertEqual(payload["connector_automation_initial_state"], "stopped")
        self.assertTrue(emit.call_args.kwargs["json_output"])

    def test_controller_runs_stale_recovery_while_automation_is_deactivated(self) -> None:
        calls: list[tuple[str, int]] = []
        scheduler_enabled: list[object | None] = []

        class _JobStore:
            def requeue_stale_running_jobs(self, *, older_than_seconds: int):
                calls.append(("stale", older_than_seconds))
                return SimpleNamespace(retrying=1, dead=0)

            def purge_completed_jobs(self, *, older_than_days: int) -> int:
                calls.append(("purge", older_than_days))
                return 2

        class _Scheduler:
            enabled: object | None = None

            def __init__(self, tasks, **kwargs):
                self.tasks = tasks
                self.enabled = kwargs.get("enabled")
                scheduler_enabled.append(self.enabled)

            def run_forever(self) -> None:
                next(task for task in self.tasks if task.name == "maintenance").run()
                raise RuntimeError("scheduler stopped")

        closed: list[bool] = []
        runtime = SimpleNamespace(
            orchestrator=_FakeOrchestrator(automation_enabled=False),
            job_store=_JobStore(),
            signal_queue=SimpleNamespace(),
            openwebui_sync_service=None,
            dashboard_store=None,
            close=lambda: closed.append(True),
        )
        settings = SimpleNamespace(
            connector_dashboard_enabled=False,
            openwebui_effective_sync_mode="disabled",
            authz_api_enabled=False,
            discovery_interval_seconds=60,
            delta_sync_interval_seconds=30,
            job_lease_seconds=120,
            job_history_retention_days=7,
            ragflow_template_refresh_seconds=300,
            ragflow_search_template_refresh_seconds=300,
            search_acl_sync_enabled=False,
            connector_automation_initial_state="stopped",
        )

        with (
            patch("seafile_ragflow_connector.app.cli._bootstrap", return_value=settings),
            patch("seafile_ragflow_connector.app.cli.build_runtime", return_value=runtime),
            patch("seafile_ragflow_connector.app.cli.SimpleScheduler", _Scheduler),
            self.assertRaisesRegex(RuntimeError, "scheduler stopped"),
        ):
            controller()

        self.assertEqual(calls, [("stale", 120), ("purge", 7)])
        self.assertEqual(scheduler_enabled, [None])
        self.assertEqual(closed, [True])

    def test_format_payload_can_emit_stable_json(self) -> None:
        output = _format_payload({"message": "für", "count": 2}, json_output=True)

        self.assertEqual(json.loads(output), {"message": "für", "count": 2})
        self.assertEqual(output, '{"count": 2, "message": "für"}')

    def test_format_payload_keeps_legacy_dict_output_by_default(self) -> None:
        self.assertEqual(_format_payload({"status": "ok"}), "{'status': 'ok'}")

    def test_emit_job_result_fails_after_rendering_dead_job(self) -> None:
        payload = {"job": {"status": JobStatus.DEAD.value}}

        with patch("typer.echo") as echo, self.assertRaises(typer.Exit) as raised:
            _emit_job_result(payload, json_output=True)

        self.assertEqual(raised.exception.exit_code, 1)
        echo.assert_called_once()

    def test_emit_job_result_fails_after_rendering_timeout(self) -> None:
        payload = {"timed_out": True, "job": {"status": JobStatus.RUNNING.value}}

        with patch("typer.echo"), self.assertRaises(typer.Exit) as raised:
            _emit_job_result(payload)

        self.assertEqual(raised.exception.exit_code, 1)

    def test_invalid_configuration_is_concise_and_exits_with_usage_code(self) -> None:
        try:
            _RequiredConfiguration()  # type: ignore[call-arg]
        except ValidationError as exc:
            validation_error = exc
        else:  # pragma: no cover - Pydantic contract guard
            self.fail("validation error expected")

        with patch("typer.echo") as echo, self.assertRaises(typer.Exit) as raised:
            _exit_for_invalid_configuration(validation_error)

        self.assertEqual(raised.exception.exit_code, 2)
        message = str(echo.call_args.args[0])
        self.assertIn("required_value", message)
        self.assertNotIn("https://errors.pydantic.dev", message)

    def test_job_status_filter_accepts_comma_separated_unique_values(self) -> None:
        self.assertEqual(
            _job_status_filter("queued, dead,queued"),
            (JobStatus.QUEUED, JobStatus.DEAD),
        )

    def test_cleanup_status_filter_accepts_superseded_and_deduplicates(self) -> None:
        self.assertEqual(
            _cleanup_status_filter("dead, superseded,dead"),
            ("dead", "superseded"),
        )

    def test_cleanup_outbox_payload_exposes_retry_context(self) -> None:
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id=8,
            repo_id="repo-1",
            run_id="run-1",
            target_type="ragflow_document",
            target_id="doc-1",
            dataset_id="dataset-1",
            action="delete",
            status="dead",
            attempts=5,
            run_after=now,
            error_message="HTTP 503",
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

        payload = _cleanup_outbox_payload(row)

        self.assertEqual(payload["id"], 8)
        self.assertEqual(payload["status"], "dead")
        self.assertEqual(payload["run_after"], now.isoformat())

    def test_job_payload_redacts_nested_secrets(self) -> None:
        now = datetime.now(UTC)
        job = SimpleNamespace(
            id=7,
            job_type="SYNC_LIBRARY_DELTA",
            repo_id="repo-1",
            file_path="/wissen.md",
            status="queued",
            priority=100,
            attempts=0,
            max_attempts=5,
            run_id=None,
            fence_token=None,
            cancel_requested_at=None,
            run_after=now,
            locked_by=None,
            locked_at=None,
            error_message=None,
            payload={"scope": "/", "api_key": "nicht-ausgeben"},
            created_at=now,
            updated_at=now,
        )

        payload = _job_payload(job)

        self.assertEqual(payload["payload"]["api_key"], "***")
        self.assertEqual(payload["run_after"], now.isoformat())

    def test_discovery_adds_openwebui_sync_job_when_enabled(self) -> None:
        specs = _discover_job_specs(_runtime("sync"))  # type: ignore[arg-type]

        self.assertEqual(
            [spec.job_type for spec in specs],
            [JobType.SYNC_LIBRARY_FULL, JobType.SYNC_OPENWEBUI],
        )
        self.assertTrue(all("trigger" not in spec.payload for spec in specs))
        self.assertEqual(
            specs[0].dedup_key(),
            JobSpec(JobType.SYNC_LIBRARY_FULL, repo_id="repo-1").dedup_key(),
        )

    def test_discovery_stops_new_automatic_jobs_when_deactivated(self) -> None:
        specs = _discover_job_specs(
            _runtime("sync", automation_enabled=False)  # type: ignore[arg-type]
        )

        self.assertEqual(specs, [])

    def test_discovery_stops_automatic_jobs_while_queue_is_paused(self) -> None:
        specs = _discover_job_specs(
            _runtime("sync", queue_paused=True)  # type: ignore[arg-type]
        )

        self.assertEqual(specs, [])

    def test_discovery_does_not_add_openwebui_sync_job_when_disabled(self) -> None:
        specs = _discover_job_specs(_runtime("disabled"))  # type: ignore[arg-type]

        self.assertEqual([spec.job_type for spec in specs], [JobType.SYNC_LIBRARY_FULL])

    def test_combined_sync_persists_openwebui_as_workflow_child_before_mutation(
        self,
    ) -> None:
        session_factory = _test_session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo"))
            session.commit()
        job_store = JobStore(session_factory)
        workflow_run_id = SyncStateStore(session_factory).create_run(
            repo_id=None,
            mode="workflow",
            status="queued",
        )
        spec = JobSpec(
            JobType.SYNC_LIBRARY_FULL,
            repo_id="repo-1",
            payload={
                "workflow_run_id": workflow_run_id,
                "sync_openwebui": True,
                "trigger": "manual",
            },
        )
        parent_job_id = job_store.enqueue(spec)
        job_store.subscribe_workflow(
            workflow_run_id,
            parent_job_id,
            is_root=True,
            owns_job=True,
        )
        signals: list[int] = []
        service = _FakeOpenWebUIService()
        orchestrator = _FakeOrchestrator()
        runtime = SimpleNamespace(
            orchestrator=orchestrator,
            job_store=job_store,
            signal_queue=SimpleNamespace(signal=signals.append),
            openwebui_sync_service=service,
            ragflow_client=SimpleNamespace(),
        )
        handlers = _build_job_handlers(runtime)  # type: ignore[arg-type]

        with activate_job_execution(parent_job_id, workflow_run_id):
            handlers[JobType.SYNC_LIBRARY_FULL](spec)

        workflow_jobs = job_store.workflow_jobs(workflow_run_id)
        child = next(
            job for job in workflow_jobs if job.job_type == JobType.SYNC_OPENWEBUI.value
        )
        self.assertEqual(service.calls, 0)
        self.assertEqual(child.status, JobStatus.QUEUED.value)
        self.assertEqual(child.payload["repo_ids"], ["repo-1"])
        self.assertEqual(signals, [child.id])
        self.assertEqual(orchestrator.full_syncs, [("repo-1", "/")])

        with activate_job_execution(int(child.id), workflow_run_id):
            handlers[JobType.SYNC_OPENWEBUI](job_store.to_spec(child))

        self.assertEqual(service.calls, 1)
        self.assertEqual(service.repo_ids, [{"repo-1"}])

    def test_combined_sync_pause_stops_before_openwebui_child_is_created(self) -> None:
        session_factory = _test_session_factory(self)
        with session_factory() as session:
            session.add(Library(repo_id="repo-1", name="Demo", name_slug="demo"))
            session.commit()
        job_store = JobStore(session_factory)
        spec = JobSpec(
            JobType.SYNC_LIBRARY_FULL,
            repo_id="repo-1",
            payload={"sync_openwebui": True, "trigger": "manual"},
        )
        parent_job_id = job_store.enqueue(spec)
        runtime = SimpleNamespace(
            orchestrator=_FakeOrchestrator(),
            job_store=job_store,
            signal_queue=SimpleNamespace(signal=lambda _job_id: None),
            openwebui_sync_service=_FakeOpenWebUIService(),
            ragflow_client=SimpleNamespace(),
        )
        handlers = _build_job_handlers(runtime)  # type: ignore[arg-type]

        with (
            activate_job_execution(parent_job_id, None),
            activate_job_pause(lambda: True),
            self.assertRaisesRegex(SyncCancelledError, "scheduling interrupted"),
        ):
            handlers[JobType.SYNC_LIBRARY_FULL](spec)

        self.assertEqual(len(job_store.list_jobs(limit=10)), 1)

    def test_sync_once_runs_openwebui_summary_when_enabled(self) -> None:
        service = _FakeOpenWebUIService()
        summary = _sync_openwebui_if_enabled(_runtime("sync", service))  # type: ignore[arg-type]

        self.assertEqual(summary, {"datasets_seen": 1, "tools_created": 1, "pipes_created": 1})
        self.assertEqual(service.calls, 1)

    def test_sync_once_skips_openwebui_when_disabled(self) -> None:
        service = _FakeOpenWebUIService()
        summary = _sync_openwebui_if_enabled(
            _runtime("disabled", service)  # type: ignore[arg-type]
        )

        self.assertIsNone(summary)
        self.assertEqual(service.calls, 0)

    def test_controller_guard_runs_openwebui_sync_when_enabled(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("sync", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 1)
        self.assertEqual(log.warnings, [])

    def test_controller_guard_logs_openwebui_sync_failure(self) -> None:
        service = _FailingOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("sync", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 1)
        self.assertEqual(log.warnings[0][0], "controller.openwebui_sync.failed")
        self.assertEqual(log.warnings[0][1]["error_class"], "ConnectionError")

    def test_controller_guard_skips_openwebui_when_disabled(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("disabled", service),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 0)
        self.assertEqual(log.warnings, [])

    def test_controller_guard_skips_startup_sync_when_automation_is_deactivated(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime(
                "sync",
                service,
                automation_enabled=False,
            ),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 0)
        self.assertEqual(log.warnings, [])

    def test_controller_guard_skips_openwebui_while_queue_is_paused(self) -> None:
        service = _FakeOpenWebUIService()
        log = _FakeLog()

        _sync_openwebui_controller_guarded(
            _runtime("sync", service, queue_paused=True),  # type: ignore[arg-type]
            log,
        )

        self.assertEqual(service.calls, 0)
        self.assertEqual(log.warnings, [])

    def test_job_handler_defers_controlled_library_without_calling_handler(self) -> None:
        calls: list[JobSpec] = []
        runtime = _runtime("sync", library_runnable=False)
        handler = _guard_job_handler(
            runtime,  # type: ignore[arg-type]
            calls.append,
        )
        spec = JobSpec(
            JobType.SYNC_LIBRARY_FULL,
            repo_id="repo-1",
            payload={"trigger": "manual"},
        )

        with self.assertRaises(JobDeferredError):
            handler(spec)

        self.assertEqual(calls, [])

    def test_wait_for_parse_only_checks_active_dataset_bindings(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-active",
                        name="Active",
                        name_slug="active",
                        status="active",
                        ragflow_dataset_id="dataset-active",
                    ),
                    Library(
                        repo_id="repo-error",
                        name="Error",
                        name_slug="error",
                        status="error",
                        ragflow_dataset_id="dataset-error",
                        last_error="HTTP 403",
                    ),
                ]
            )
            session.commit()
        orchestrator = _ParseWaitOrchestrator(session_factory)
        runtime = SimpleNamespace(orchestrator=orchestrator, ragflow_client=_ParseWaitRAGFlow())

        self.assertEqual(
            _active_dataset_bindings(runtime),  # type: ignore[arg-type]
            [("repo-active", "dataset-active")],
        )

        _wait_for_parse(runtime, timeout_seconds=1)  # type: ignore[arg-type]

        self.assertEqual(orchestrator.checked, [("repo-active", "dataset-active")])
        self.assertFalse(orchestrator.discover_called)
        self.assertFalse(orchestrator.ensure_called)

    def test_wait_for_parse_keeps_running_state_across_multiple_datasets(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-running",
                        name="Running",
                        name_slug="running",
                        status="active",
                        ragflow_dataset_id="dataset-running",
                    ),
                    Library(
                        repo_id="repo-done",
                        name="Done",
                        name_slug="done",
                        status="active",
                        ragflow_dataset_id="dataset-done",
                    ),
                ]
            )
            running_file = File(
                repo_id="repo-running",
                path="/running.pdf",
                normalized_path="/running.pdf",
            )
            session.add(running_file)
            session.flush()
            session.add(
                FileDocumentVersion(
                    file_id=running_file.id,
                    repo_id="repo-running",
                    normalized_path="/running.pdf",
                    dataset_id="dataset-running",
                    document_id="doc-running",
                    document_name="running.pdf",
                    state="parsing",
                    parse_status="RUNNING",
                )
            )
            session.commit()
        runtime = SimpleNamespace(
            orchestrator=_ParseWaitOrchestrator(session_factory),
            ragflow_client=_ParseWaitRAGFlow(
                {"dataset-running": "RUNNING", "dataset-done": "DONE"}
            ),
        )

        with patch(
            "seafile_ragflow_connector.app.cli.time.sleep",
            side_effect=RuntimeError("poll requested"),
        ), self.assertRaisesRegex(RuntimeError, "poll requested"):
            _wait_for_parse(runtime, timeout_seconds=30)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
