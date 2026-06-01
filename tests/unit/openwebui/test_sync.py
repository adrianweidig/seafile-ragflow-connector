from __future__ import annotations

import unittest

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.clients.openwebui import OpenWebUICapabilities
    from seafile_ragflow_connector.config.settings import Settings
    from seafile_ragflow_connector.openwebui.sync import OpenWebUISyncService
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.persistence.models.openwebui import (
        OpenWebUIDatasetMapping,
        OpenWebUISyncState,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"pydantic", "sqlalchemy"}:
        raise
    create_engine = None  # type: ignore[assignment]


class _FakeRAGFlowClient:
    def __init__(self) -> None:
        self.created_chats: list[dict[str, object]] = []
        self.updated_chats: list[tuple[str, dict[str, object]]] = []
        self.chats: dict[str, dict[str, object]] = {}
        self.deleted_chats: list[list[str]] = []
        self.next_chat_id = 1

    def get_chat(self, chat_id: str):
        return self.chats.get(chat_id)

    def list_chats(self, *, name: str | None = None, chat_id: str | None = None):
        chats = list(self.chats.values())
        if chat_id:
            chats = [chat for chat in chats if str(chat.get("id")) == chat_id]
        if name:
            chats = [chat for chat in chats if chat.get("name") == name]
        return chats

    def create_chat(self, payload: dict[str, object]):
        self.created_chats.append(payload)
        chat_id = f"chat-{self.next_chat_id}"
        self.next_chat_id += 1
        chat = {"id": chat_id, **payload}
        self.chats[chat_id] = chat
        return chat

    def update_chat(self, chat_id: str, payload: dict[str, object]):
        self.updated_chats.append((chat_id, payload))
        chat = {"id": chat_id, **payload}
        self.chats[chat_id] = chat
        return chat

    def delete_chats(self, chat_ids: list[str]):
        self.deleted_chats.append(chat_ids)
        return True


class _FakeOpenWebUIClient:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, object]] = {}
        self.functions: dict[str, dict[str, object]] = {}
        self.deleted_tools: list[str] = []
        self.deleted_functions: list[str] = []
        self.tool_valve_updates: list[str] = []
        self.function_valve_updates: list[str] = []
        self.tool_valves: dict[str, dict[str, object]] = {}
        self.function_valves: dict[str, dict[str, object]] = {}

    def probe_capabilities(self):
        return OpenWebUICapabilities(
            reachable=True,
            functions_list=True,
            functions_write=True,
            functions_valves=True,
            tools_list=True,
            tools_write=True,
            tools_valves=True,
        )

    def get_tool(self, tool_id: str):
        return self.tools.get(tool_id)

    def create_tool(self, payload: dict[str, object]):
        self.tools[str(payload["id"])] = dict(payload)
        return payload

    def update_tool(self, tool_id: str, payload: dict[str, object]):
        self.tools[tool_id] = dict(payload)
        return payload

    def update_tool_valves(self, tool_id: str, valves: dict[str, object]):
        self.tool_valve_updates.append(tool_id)
        self.tool_valves[tool_id] = dict(valves)
        return valves

    def delete_tool(self, tool_id: str):
        self.deleted_tools.append(tool_id)
        self.tools.pop(tool_id, None)
        return True

    def get_function(self, function_id: str):
        return self.functions.get(function_id)

    def create_function(self, payload: dict[str, object]):
        self.functions[str(payload["id"])] = {**payload, "is_active": True}
        return payload

    def update_function(self, function_id: str, payload: dict[str, object]):
        self.functions[function_id] = {**payload, "is_active": True}
        return payload

    def update_function_valves(self, function_id: str, valves: dict[str, object]):
        self.function_valve_updates.append(function_id)
        self.function_valves[function_id] = dict(valves)
        return valves

    def ensure_function_active(self, function_id: str):
        return {"id": function_id, "is_active": True}

    def delete_function(self, function_id: str):
        self.deleted_functions.append(function_id)
        self.functions.pop(function_id, None)
        return True


class _UnreachableOpenWebUIClient(_FakeOpenWebUIClient):
    def probe_capabilities(self):
        return OpenWebUICapabilities(reachable=False, error="unauthorized")


def _settings(*, mode: str = "sync", answer_synthesis: bool = False) -> Settings:
    return Settings(
        seafile_base_url="http://seafile.local",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key="ragflow-token",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
        openwebui_integration_enabled=True,
        openwebui_sync_mode=mode,
        openwebui_admin_api_key="admin-key" if mode != "dry-run" else None,
        openwebui_proxy_shared_secret="proxy-secret",
        openwebui_proxy_internal_base_url="http://connector:8080",
        openwebui_pipe_answer_synthesis_enabled=answer_synthesis,
        openwebui_pipe_answer_llm_base_url=(
            "http://litellm:4000/v1" if answer_synthesis else None
        ),
        openwebui_pipe_answer_llm_model="groq-rag-quality" if answer_synthesis else None,
        openwebui_pipe_answer_llm_api_key="litellm-key" if answer_synthesis else None,
    )


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@unittest.skipIf(
    create_engine is None,
    "pydantic or sqlalchemy is not installed in this environment",
)
class OpenWebUISyncServiceTests(unittest.TestCase):
    def test_dry_run_creates_planned_mapping_without_writes(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.commit()

        service = OpenWebUISyncService(
            settings=_settings(mode="dry-run"),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=None,
        )

        summary = service.sync_once()

        self.assertTrue(summary.dry_run)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "planned")
            self.assertEqual(mapping.openwebui_model_name, "ragflow/demo_dataset_dataset1")

    def test_sync_creates_chat_tool_and_pipe_once_then_reuses(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        first = service.sync_once()
        second = service.sync_once()

        self.assertEqual(first.chats_created, 1)
        self.assertEqual(first.tools_created, 1)
        self.assertEqual(first.pipes_created, 1)
        self.assertEqual(second.tools_reused, 1)
        self.assertEqual(second.pipes_reused, 1)
        self.assertEqual(openwebui.tool_valve_updates, ["ragflow_tool_demo_dataset_dataset1"])
        self.assertEqual(openwebui.function_valve_updates, ["ragflow_pipe_demo_dataset_dataset1"])
        template_chat = next(
            payload
            for payload in ragflow.created_chats
            if payload["name"] == "connector_template_chat"
        )
        dataset_chat = next(
            payload
            for payload in ragflow.created_chats
            if str(payload["name"]).startswith("owui__ragflow__demo_dataset__")
        )
        self.assertNotIn("dataset_ids", template_chat)
        self.assertEqual(dataset_chat["dataset_ids"], ["dataset-1"])
        self.assertEqual(dataset_chat["top_n"], 10)
        self.assertEqual(dataset_chat["vector_similarity_weight"], 0.35)
        prompt_config = dataset_chat["prompt_config"]
        self.assertIsInstance(prompt_config, dict)
        self.assertTrue(prompt_config["quote"])
        self.assertTrue(prompt_config["keyword"])
        self.assertEqual(
            prompt_config["reference_metadata"]["fields"][:3],
            ["repo_id", "path", "source_path"],
        )
        self.assertEqual(ragflow.updated_chats, [])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.artifact_version, "20")

    def test_sync_can_be_scoped_to_selected_repo_ids(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-1",
                        name="Alpha",
                        name_slug="alpha",
                        ragflow_dataset_id="dataset-1",
                        ragflow_dataset_name="Alpha Dataset",
                        status="active",
                    ),
                    Library(
                        repo_id="repo-2",
                        name="Beta",
                        name_slug="beta",
                        ragflow_dataset_id="dataset-2",
                        ragflow_dataset_name="Beta Dataset",
                        status="active",
                    ),
                ]
            )
            session.commit()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once(repo_ids={"repo-2"})

        self.assertEqual(summary.datasets_seen, 1)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.repo_id, "repo-2")
            self.assertEqual(mapping.ragflow_dataset_id, "dataset-2")

    def test_pipe_sync_can_inject_answer_synthesis_valves(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.commit()
        openwebui = _FakeOpenWebUIClient()
        service = OpenWebUISyncService(
            settings=_settings(answer_synthesis=True),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        service.sync_once()

        valves = openwebui.function_valves["ragflow_pipe_demo_dataset_dataset1"]
        self.assertTrue(valves["ENABLE_ANSWER_SYNTHESIS_FALLBACK"])
        self.assertEqual(valves["ANSWER_LLM_BASE_URL"], "http://litellm:4000/v1")
        self.assertEqual(valves["ANSWER_LLM_MODEL"], "groq-rag-quality")
        self.assertEqual(valves["ANSWER_LLM_API_KEY"], "litellm-key")
        self.assertEqual(valves["CONNECTOR_PROXY_SHARED_SECRET"], "proxy-secret")

    def test_foreign_openwebui_artifact_keeps_manual_required_status(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.commit()
        openwebui = _FakeOpenWebUIClient()
        openwebui.tools["ragflow_tool_demo_dataset_dataset1"] = {
            "id": "ragflow_tool_demo_dataset_dataset1",
            "content": "manually managed tool",
        }
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.manual_required, 1)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "manual_required")
            self.assertIn("not connector-owned", mapping.last_error or "")
            state = session.get(OpenWebUISyncState, "default")
            self.assertIsNotNone(state)
            self.assertEqual(state.status, "manual_required")

    def test_sync_does_not_create_ragflow_chat_when_openwebui_is_unreachable(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=_UnreachableOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.failed, 1)
        self.assertEqual(ragflow.created_chats, [])

    def test_deleted_library_removes_owned_openwebui_artifacts_and_ragflow_chat(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    status="deleted",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                    openwebui_model_name="ragflow/demo",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        owned_payload = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-1"] = dict(owned_payload)
        openwebui.functions["pipe-1"] = dict(owned_payload)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.tools_deleted, 1)
        self.assertEqual(summary.pipes_deleted, 1)
        self.assertEqual(summary.chats_deleted, 1)
        self.assertEqual(openwebui.deleted_tools, ["tool-1"])
        self.assertEqual(openwebui.deleted_functions, ["pipe-1"])
        self.assertEqual(ragflow.deleted_chats, [["chat-1"]])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "deleted")

    def test_active_dataset_id_change_removes_replaced_openwebui_artifacts(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-new",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-old",
                    ragflow_dataset_name="Demo Dataset",
                    ragflow_chat_id="chat-old",
                    openwebui_tool_id="tool-old",
                    openwebui_pipe_id="pipe-old",
                    openwebui_model_name="ragflow/old",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        owned_payload = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-old"] = dict(owned_payload)
        openwebui.functions["pipe-old"] = dict(owned_payload)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.tools_deleted, 1)
        self.assertEqual(summary.pipes_deleted, 1)
        self.assertEqual(summary.chats_deleted, 1)
        self.assertEqual(openwebui.deleted_tools, ["tool-old"])
        self.assertEqual(openwebui.deleted_functions, ["pipe-old"])
        self.assertEqual(ragflow.deleted_chats, [["chat-old"]])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.ragflow_dataset_id, "dataset-new")
            self.assertEqual(mapping.sync_status, "synced")


if __name__ == "__main__":
    unittest.main()
