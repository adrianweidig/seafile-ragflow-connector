from __future__ import annotations

import unittest
from collections.abc import Callable
from hashlib import sha256

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.clients.http import ApiError
    from seafile_ragflow_connector.clients.openwebui import OpenWebUICapabilities
    from seafile_ragflow_connector.config.settings import Settings
    from seafile_ragflow_connector.domain.ragflow_defaults import (
        build_chat_payload,
        build_search_answer_chat_payload,
    )
    from seafile_ragflow_connector.jobs.context import activate_job_pause
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
    def __init__(self, *, artifact_owner_id: str | None = None) -> None:
        self.artifact_owner_id = artifact_owner_id
        self.created_chats: list[dict[str, object]] = []
        self.updated_chats: list[tuple[str, dict[str, object]]] = []
        self.chats: dict[str, dict[str, object]] = {}
        self.deleted_chats: list[list[str]] = []
        self.next_chat_id = 1
        self.searches: dict[str, dict[str, object]] = {}
        self.created_searches: list[dict[str, object]] = []
        self.updated_searches: list[tuple[str, dict[str, object]]] = []
        self.owner_verifications = 0

    def verify_artifact_owner(self):
        self.owner_verifications += 1

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
        for chat_id in chat_ids:
            self.chats.pop(chat_id, None)
        return True

    def list_searches(self, *, keywords: str | None = None, page_size: int | None = None):
        _ = page_size
        searches = list(self.searches.values())
        if keywords:
            searches = [search for search in searches if search.get("name") == keywords]
        return searches

    def get_search(self, search_id: str):
        return self.searches.get(search_id)

    def create_search(self, payload: dict[str, object]):
        self.created_searches.append(payload)
        search = {"id": "search-1", **payload}
        self.searches["search-1"] = search
        return search

    def update_search(self, search_id: str, payload: dict[str, object]):
        self.updated_searches.append((search_id, payload))
        search = {"id": search_id, **payload}
        self.searches[search_id] = search
        return search


def _connector_chat(chat_id: str, dataset_id: str) -> dict[str, object]:
    short_id = sha256(dataset_id.encode("utf-8")).hexdigest()[:8]
    return {
        "id": chat_id,
        "name": f"RAG_demo_{short_id}",
        "dataset_ids": [dataset_id],
    }


class _InitiallyEmptyDatasetRAGFlowClient(_FakeRAGFlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.dataset_ready = False

    def create_chat(self, payload: dict[str, object]):
        if payload.get("dataset_ids") and not self.dataset_ready:
            raise ApiError(
                "API returned an error code",
                status_code=200,
                payload={
                    "code": 102,
                    "message": "The dataset dataset-1 doesn't own parsed file",
                },
            )
        return super().create_chat(payload)


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
        self.operations: list[tuple[str, str]] = []

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
        self.operations.append(("create_tool", str(payload["id"])))
        self.tools[str(payload["id"])] = dict(payload)
        return payload

    def update_tool(self, tool_id: str, payload: dict[str, object]):
        self.operations.append(("update_tool", tool_id))
        self.tools[tool_id] = dict(payload)
        return payload

    def update_tool_valves(self, tool_id: str, valves: dict[str, object]):
        self.operations.append(("tool_valves", tool_id))
        self.tool_valve_updates.append(tool_id)
        self.tool_valves[tool_id] = dict(valves)
        if tool_id in self.tools:
            self.tools[tool_id]["valves"] = dict(valves)
        return valves

    def delete_tool(self, tool_id: str):
        self.operations.append(("delete_tool", tool_id))
        self.deleted_tools.append(tool_id)
        self.tools.pop(tool_id, None)
        return True

    def get_function(self, function_id: str):
        return self.functions.get(function_id)

    def create_function(self, payload: dict[str, object]):
        self.operations.append(("create_function", str(payload["id"])))
        self.functions[str(payload["id"])] = {**payload, "is_active": True}
        return payload

    def update_function(self, function_id: str, payload: dict[str, object]):
        self.operations.append(("update_function", function_id))
        self.functions[function_id] = {**payload, "is_active": True}
        return payload

    def update_function_valves(self, function_id: str, valves: dict[str, object]):
        self.operations.append(("function_valves", function_id))
        self.function_valve_updates.append(function_id)
        self.function_valves[function_id] = dict(valves)
        if function_id in self.functions:
            self.functions[function_id]["valves"] = dict(valves)
        return valves

    def ensure_function_active(self, function_id: str):
        self.operations.append(("activate_function", function_id))
        return {"id": function_id, "is_active": True}

    def delete_function(self, function_id: str):
        self.operations.append(("delete_function", function_id))
        self.deleted_functions.append(function_id)
        self.functions.pop(function_id, None)
        return True


class _UnreachableOpenWebUIClient(_FakeOpenWebUIClient):
    def probe_capabilities(self):
        return OpenWebUICapabilities(reachable=False, error="unauthorized")


class _FailingToolCreateOpenWebUIClient(_FakeOpenWebUIClient):
    def create_tool(self, payload: dict[str, object]):
        self.operations.append(("create_tool_failed", str(payload["id"])))
        raise RuntimeError("simulated tool create failure")


class _FailingDeleteOnceOpenWebUIClient(_FakeOpenWebUIClient):
    def __init__(self, failing_tool_id: str) -> None:
        super().__init__()
        self.failing_tool_id = failing_tool_id
        self.delete_failures = 0

    def delete_tool(self, tool_id: str):
        if tool_id == self.failing_tool_id and self.delete_failures == 0:
            self.operations.append(("delete_tool_failed", tool_id))
            self.delete_failures += 1
            raise RuntimeError("simulated transient delete failure")
        return super().delete_tool(tool_id)


class _FailingChatDeleteOnceRAGFlowClient(_FakeRAGFlowClient):
    def __init__(self, failing_chat_id: str) -> None:
        super().__init__()
        self.failing_chat_id = failing_chat_id
        self.delete_failures = 0

    def delete_chats(self, chat_ids: list[str]):
        if self.failing_chat_id in chat_ids and self.delete_failures == 0:
            self.delete_failures += 1
            raise RuntimeError("simulated transient chat delete failure")
        return super().delete_chats(chat_ids)


class _ControlSwitchingOpenWebUIClient(_FakeOpenWebUIClient):
    def __init__(self, on_first_delete: Callable[[], None]) -> None:
        super().__init__()
        self.on_first_delete = on_first_delete

    def delete_tool(self, tool_id: str):
        result = super().delete_tool(tool_id)
        if len(self.deleted_tools) == 1:
            self.on_first_delete()
        return result


def _settings(
    *,
    mode: str = "sync",
    answer_synthesis: bool = False,
    proxy_base_url: str = "http://connector:8080",
    proxy_secret: str = "proxy-secret",
    interactive: bool = False,
) -> Settings:
    return Settings(
        seafile_base_url="http://seafile.local",
        seafile_admin_token="admin-token",
        seafile_sync_user_token="sync-token",
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key="ragflow-token",
        ragflow_generated_dataset_permission="team" if interactive else "me",
        ragflow_interactive_api_key="interactive-token" if interactive else None,
        ragflow_interactive_owner_id="owner-1" if interactive else None,
        ragflow_interactive_chat_model_id="model@provider" if interactive else None,
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
        openwebui_integration_enabled=True,
        openwebui_sync_mode=mode,
        openwebui_admin_api_key="admin-key" if mode != "dry-run" else None,
        openwebui_proxy_shared_secret=proxy_secret,
        openwebui_proxy_internal_base_url=proxy_base_url,
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
    def test_interactive_client_owns_chats_and_native_search_app(self) -> None:
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
        primary = _FakeRAGFlowClient()
        interactive = _FakeRAGFlowClient(artifact_owner_id="owner-1")
        service = OpenWebUISyncService(
            settings=_settings(interactive=True),
            session_factory=session_factory,
            ragflow_client=primary,  # type: ignore[arg-type]
            interactive_ragflow_client=interactive,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        first = service.sync_once()
        second = service.sync_once()

        self.assertEqual(first.chats_created, 1)
        self.assertEqual(second.chats_reused, 1)
        self.assertEqual(primary.created_chats, [])
        self.assertTrue(interactive.created_chats)
        self.assertTrue(
            all(chat["llm_id"] == "model@provider" for chat in interactive.created_chats)
        )
        self.assertEqual(len(interactive.created_searches), 1)
        search_config = interactive.created_searches[0]["search_config"]
        self.assertEqual(search_config["kb_ids"], ["dataset-1"])
        self.assertEqual(search_config["chat_id"], "model@provider")
        self.assertEqual(interactive.updated_searches, [])

    def test_primary_owner_chat_stays_pending_until_completion_is_verified(self) -> None:
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
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo Dataset",
                    ragflow_chat_id="service-owned-chat",
                    sync_status="synced",
                )
            )
            session.commit()
        interactive = _FakeRAGFlowClient(artifact_owner_id="owner-1")
        primary = _FakeRAGFlowClient()
        primary.chats["service-owned-chat"] = _connector_chat(
            "service-owned-chat",
            "dataset-1",
        )
        service = OpenWebUISyncService(
            settings=_settings(interactive=True),
            session_factory=session_factory,
            ragflow_client=primary,  # type: ignore[arg-type]
            interactive_ragflow_client=interactive,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.chats_created, 1)
        self.assertEqual(summary.manual_required, 1)
        self.assertEqual(interactive.deleted_chats, [])
        self.assertEqual(primary.deleted_chats, [])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertNotEqual(mapping.ragflow_chat_id, "service-owned-chat")
            self.assertEqual(mapping.sync_status, "manual_required")
            pending = mapping.capabilities_snapshot["pending_replacement_cleanup"]
            self.assertEqual(
                pending["chats"],
                [
                    {
                        "id": "service-owned-chat",
                        "expected_dataset_id": "dataset-1",
                        "provenance": "owner_migration_completion_unverified",
                    }
                ],
            )

    def test_scoped_sync_keeps_all_active_datasets_in_native_search_app(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-1",
                        name="Alpha",
                        name_slug="alpha",
                        ragflow_dataset_id="dataset-1",
                        status="active",
                    ),
                    Library(
                        repo_id="repo-2",
                        name="Beta",
                        name_slug="beta",
                        ragflow_dataset_id="dataset-2",
                        status="active",
                    ),
                ]
            )
            session.commit()
        interactive = _FakeRAGFlowClient(artifact_owner_id="owner-1")
        service = OpenWebUISyncService(
            settings=_settings(interactive=True),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            interactive_ragflow_client=interactive,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once(repo_ids={"repo-1"})

        self.assertEqual(summary.datasets_seen, 1)
        search_config = interactive.created_searches[0]["search_config"]
        self.assertEqual(search_config["kb_ids"], ["dataset-1", "dataset-2"])

    def test_global_primary_owner_artifacts_are_reported_without_name_only_delete(
        self,
    ) -> None:
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
        settings = _settings(interactive=True)
        primary = _FakeRAGFlowClient()
        primary.chats["primary-template"] = {
            "id": "primary-template",
            **build_chat_payload(settings.ragflow_template_chat_name),
        }
        primary.chats["foreign-template"] = {
            "id": "foreign-template",
            "name": settings.ragflow_template_chat_name,
            "description": "foreign artifact with a matching name",
        }
        primary.chats["primary-answer"] = {
            "id": "primary-answer",
            **build_search_answer_chat_payload(settings.ragflow_search_answer_chat_name),
        }
        primary.searches["primary-search"] = {
            "id": "primary-search",
            "name": settings.ragflow_search_template_name,
            "description": (
                "Connector-verwaltetes Search-Template für nutzernahe "
                "RAGFlow-Suchen."
            ),
            "search_config": {},
        }
        primary.searches["foreign-search"] = {
            "id": "foreign-search",
            "name": settings.ragflow_search_template_name,
            "description": "foreign artifact with a matching name",
            "search_config": {},
        }
        interactive = _FakeRAGFlowClient(artifact_owner_id="owner-1")
        interactive.chats["interactive-answer"] = {
            "id": "interactive-answer",
            **build_search_answer_chat_payload(settings.ragflow_search_answer_chat_name),
            "llm_id": settings.ragflow_interactive_chat_model_id,
        }
        service = OpenWebUISyncService(
            settings=settings,
            session_factory=session_factory,
            ragflow_client=primary,  # type: ignore[arg-type]
            interactive_ragflow_client=interactive,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.manual_required, 3)
        self.assertEqual(primary.deleted_chats, [])
        with session_factory() as session:
            state = session.get(OpenWebUISyncState, "default")
            assert state is not None
            self.assertEqual(state.status, "manual_required")
            pending = state.capabilities_snapshot["pending_owner_migration"]
        self.assertEqual(
            [entry["artifact_id"] for entry in pending],
            ["primary-template", "primary-answer", "primary-search"],
        )
        self.assertTrue(
            all(entry["status"] == "operator_cleanup_required" for entry in pending)
        )
        self.assertNotIn("foreign-template", {entry["artifact_id"] for entry in pending})
        self.assertNotIn("foreign-search", {entry["artifact_id"] for entry in pending})

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
            if str(payload["name"]).startswith("RAG_demo_dataset_")
        )
        self.assertNotIn("dataset_ids", template_chat)
        self.assertEqual(dataset_chat["dataset_ids"], ["dataset-1"])
        self.assertEqual(dataset_chat["top_n"], 8)
        self.assertEqual(dataset_chat["top_k"], 1024)
        self.assertEqual(dataset_chat["similarity_threshold"], 0.2)
        self.assertEqual(dataset_chat["vector_similarity_weight"], 0.3)
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
            self.assertEqual(mapping.artifact_version, "29")

    def test_sync_defers_chat_for_empty_dataset_and_retries_after_parsing(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Empty",
                    name_slug="empty",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Empty Dataset",
                    status="active",
                )
            )
            session.commit()
        ragflow = _InitiallyEmptyDatasetRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        empty = service.sync_once()

        self.assertEqual(empty.failed, 0)
        self.assertEqual(empty.chats_created, 0)
        self.assertEqual(empty.tools_created, 1)
        self.assertEqual(empty.pipes_created, 1)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "synced")
            self.assertIsNone(mapping.ragflow_chat_id)

        ragflow.dataset_ready = True
        parsed = service.sync_once()

        self.assertEqual(parsed.failed, 0)
        self.assertEqual(parsed.chats_created, 1)
        self.assertEqual(parsed.tools_updated, 1)
        self.assertEqual(parsed.pipes_updated, 1)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.ragflow_chat_id, "chat-2")

    def test_sync_merges_search_template_chat_settings_into_dataset_chat(self) -> None:
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
        ragflow.chats["search-template"] = {
            "id": "search-template",
            "name": "search_template",
            "top_n": 14,
            "top_k": 2048,
            "similarity_threshold": 0.07,
            "vector_similarity_weight": 0.42,
            "rerank_id": "reranker@provider",
            "prompt_config": {
                "keyword": False,
                "toc_enhance": True,
                "use_kg": False,
            },
        }
        openwebui = _FakeOpenWebUIClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        service.sync_once()

        dataset_chat = next(
            payload
            for payload in ragflow.created_chats
            if str(payload["name"]).startswith("RAG_demo_dataset_")
        )
        self.assertEqual(dataset_chat["top_n"], 14)
        self.assertEqual(dataset_chat["top_k"], 2048)
        self.assertEqual(dataset_chat["similarity_threshold"], 0.07)
        self.assertEqual(dataset_chat["vector_similarity_weight"], 0.42)
        self.assertEqual(dataset_chat["rerank_id"], "reranker@provider")
        self.assertFalse(dataset_chat["prompt_config"]["keyword"])
        self.assertTrue(dataset_chat["prompt_config"]["toc_enhance"])

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
        ragflow = _FakeRAGFlowClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once(repo_ids={"repo-2"})

        self.assertEqual(summary.datasets_seen, 1)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.repo_id, "repo-2")
            self.assertEqual(mapping.ragflow_dataset_id, "dataset-2")

    def test_sync_filters_paused_and_disabled_libraries(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="active",
                        name="Active",
                        name_slug="active",
                        ragflow_dataset_id="dataset-active",
                        status="active",
                    ),
                    Library(
                        repo_id="paused",
                        name="Paused",
                        name_slug="paused",
                        ragflow_dataset_id="dataset-paused",
                        status="active",
                    ),
                    Library(
                        repo_id="disabled",
                        name="Disabled",
                        name_slug="disabled",
                        ragflow_dataset_id="dataset-disabled",
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
        service.admin_control_store.update_library(
            "paused",
            updated_by="test",
            paused=True,
        )
        service.admin_control_store.update_library(
            "disabled",
            updated_by="test",
            enabled=False,
        )

        summary = service.sync_once()

        self.assertEqual(summary.datasets_seen, 1)
        with session_factory() as session:
            mappings = session.query(OpenWebUIDatasetMapping).all()
            self.assertEqual([mapping.repo_id for mapping in mappings], ["active"])

    def test_scoped_sync_rejects_controlled_repo_and_dataset_ids(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
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
        service.admin_control_store.update_library(
            "repo-1",
            updated_by="test",
            paused=True,
        )

        for requested in ({"repo-1"}, {"dataset-1"}):
            with self.assertRaisesRegex(ValueError, "repo-1 \\(paused\\)"):
                service.sync_once(repo_ids=requested)

        self.assertEqual(ragflow.created_chats, [])
        self.assertEqual(openwebui.operations, [])

    def test_controlled_active_mapping_is_not_deleted(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    status="active",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        owned = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-1"] = dict(owned)
        openwebui.functions["pipe-1"] = dict(owned)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )
        service.admin_control_store.update_library(
            "repo-1",
            updated_by="test",
            enabled=False,
        )

        summary = service.sync_once()

        self.assertEqual(summary.datasets_seen, 0)
        self.assertEqual(openwebui.deleted_tools, [])
        self.assertEqual(openwebui.deleted_functions, [])
        self.assertEqual(ragflow.deleted_chats, [])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "synced")

    def test_empty_repo_scope_does_not_expand_to_all_libraries(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    status="active",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.sync_once(repo_ids=set())

        self.assertEqual(summary.datasets_seen, 0)
        self.assertEqual(ragflow.created_chats, [])
        self.assertEqual(ragflow.updated_chats, [])
        with session_factory() as session:
            self.assertEqual(session.query(OpenWebUIDatasetMapping).count(), 0)

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

    def test_sync_rotates_managed_valves_without_resetting_operator_valves(self) -> None:
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
        first_service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )
        first_service.sync_once()

        tool_id = "ragflow_tool_demo_dataset_dataset1"
        pipe_id = "ragflow_pipe_demo_dataset_dataset1"
        openwebui.tools[tool_id]["valves"]["TOP_K"] = 17
        openwebui.tools[tool_id]["valves"]["SHOW_SOURCE_SCORES"] = False
        openwebui.tools[tool_id]["valves"]["OPERATOR_PLUGIN_MODE"] = "curated"
        openwebui.functions[pipe_id]["valves"]["STATUS_MODE"] = "detailed"
        openwebui.functions[pipe_id]["valves"]["MAX_SOURCE_EVENTS"] = 7
        openwebui.functions[pipe_id]["valves"]["OPERATOR_PLUGIN_MODE"] = "curated"

        rotated_service = OpenWebUISyncService(
            settings=_settings(
                proxy_base_url="http://connector-v2:8080",
                proxy_secret="rotated-secret",
            ),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )
        summary = rotated_service.sync_once()

        self.assertEqual(summary.tools_updated, 1)
        self.assertEqual(summary.pipes_updated, 1)
        tool_valves = openwebui.tool_valves[tool_id]
        pipe_valves = openwebui.function_valves[pipe_id]
        self.assertEqual(tool_valves["CONNECTOR_PROXY_BASE_URL"], "http://connector-v2:8080")
        self.assertEqual(tool_valves["CONNECTOR_PROXY_SHARED_SECRET"], "rotated-secret")
        self.assertEqual(tool_valves["TOP_K"], 17)
        self.assertFalse(tool_valves["SHOW_SOURCE_SCORES"])
        self.assertEqual(tool_valves["OPERATOR_PLUGIN_MODE"], "curated")
        self.assertEqual(pipe_valves["CONNECTOR_PROXY_BASE_URL"], "http://connector-v2:8080")
        self.assertEqual(pipe_valves["CONNECTOR_PROXY_SHARED_SECRET"], "rotated-secret")
        self.assertEqual(pipe_valves["STATUS_MODE"], "detailed")
        self.assertEqual(pipe_valves["MAX_SOURCE_EVENTS"], 7)
        self.assertEqual(pipe_valves["OPERATOR_PLUGIN_MODE"], "curated")

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
        ragflow.chats["chat-1"] = _connector_chat("chat-1", "dataset-1")
        ragflow.next_chat_id = 2
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
        second_summary = service.sync_once()

        self.assertEqual(summary.tools_deleted, 1)
        self.assertEqual(summary.pipes_deleted, 1)
        self.assertEqual(summary.chats_deleted, 1)
        self.assertEqual(openwebui.deleted_tools, ["tool-1"])
        self.assertEqual(openwebui.deleted_functions, ["pipe-1"])
        self.assertEqual(ragflow.deleted_chats, [["chat-1"]])
        self.assertEqual(second_summary.tools_deleted, 0)
        self.assertEqual(second_summary.pipes_deleted, 0)
        self.assertEqual(second_summary.chats_deleted, 0)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.sync_status, "deleted")
            self.assertIsNone(mapping.openwebui_tool_id)
            self.assertIsNone(mapping.openwebui_pipe_id)
            self.assertIsNone(mapping.ragflow_chat_id)

    def test_controlled_deleted_mapping_is_preserved_until_library_is_reenabled(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    status="deleted",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        ragflow.chats["chat-1"] = _connector_chat("chat-1", "dataset-1")
        ragflow.next_chat_id = 2
        openwebui = _FakeOpenWebUIClient()
        owned = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-1"] = dict(owned)
        openwebui.functions["pipe-1"] = dict(owned)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )
        service.admin_control_store.update_library(
            "repo-1",
            updated_by="test",
            enabled=False,
        )

        protected_summary = service.sync_once()

        self.assertEqual(protected_summary.datasets_seen, 0)
        self.assertEqual(openwebui.deleted_tools, [])
        self.assertEqual(openwebui.deleted_functions, [])
        self.assertEqual(ragflow.deleted_chats, [])
        service.admin_control_store.update_library(
            "repo-1",
            updated_by="test",
            enabled=True,
        )

        cleanup_summary = service.sync_once()

        self.assertEqual(cleanup_summary.tools_deleted, 1)
        self.assertEqual(cleanup_summary.pipes_deleted, 1)
        self.assertEqual(cleanup_summary.chats_deleted, 1)

    def test_deleted_cleanup_rechecks_control_before_each_library(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add_all(
                [
                    Library(
                        repo_id="repo-1",
                        name="Alpha",
                        name_slug="alpha",
                        ragflow_dataset_id="dataset-1",
                        status="deleted",
                    ),
                    Library(
                        repo_id="repo-2",
                        name="Beta",
                        name_slug="beta",
                        ragflow_dataset_id="dataset-2",
                        status="deleted",
                    ),
                    OpenWebUIDatasetMapping(
                        repo_id="repo-1",
                        ragflow_dataset_id="dataset-1",
                        ragflow_dataset_name="Alpha",
                        openwebui_tool_id="tool-1",
                        sync_status="synced",
                    ),
                    OpenWebUIDatasetMapping(
                        repo_id="repo-2",
                        ragflow_dataset_id="dataset-2",
                        ragflow_dataset_name="Beta",
                        openwebui_tool_id="tool-2",
                        sync_status="synced",
                    ),
                ]
            )
            session.commit()
        service: OpenWebUISyncService

        def pause_second_library() -> None:
            service.admin_control_store.update_library(
                "repo-2",
                updated_by="test",
                paused=True,
            )

        openwebui = _ControlSwitchingOpenWebUIClient(pause_second_library)
        owned = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-1"] = dict(owned)
        openwebui.tools["tool-2"] = dict(owned)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        summary = service.sync_once()

        self.assertEqual(summary.datasets_seen, 1)
        self.assertEqual(summary.tools_deleted, 1)
        self.assertEqual(openwebui.deleted_tools, ["tool-1"])
        with session_factory() as session:
            mappings = {
                mapping.repo_id: mapping
                for mapping in session.query(OpenWebUIDatasetMapping).all()
            }
            self.assertEqual(mappings["repo-1"].sync_status, "deleted")
            self.assertIsNone(mappings["repo-1"].openwebui_tool_id)
            self.assertEqual(mappings["repo-2"].sync_status, "synced")
            self.assertEqual(mappings["repo-2"].openwebui_tool_id, "tool-2")

    def test_deleted_cleanup_stops_before_next_mutation_when_job_is_paused(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-1",
                    status="deleted",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-1",
                    ragflow_dataset_name="Demo",
                    ragflow_chat_id="chat-1",
                    openwebui_tool_id="tool-1",
                    openwebui_pipe_id="pipe-1",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        owned = {
            "content": "owner: seafile-ragflow-connector",
            "meta": {"manifest": {"owner": "seafile-ragflow-connector"}},
        }
        openwebui.tools["tool-1"] = dict(owned)
        openwebui.functions["pipe-1"] = dict(owned)
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        with (
            activate_job_pause(lambda: bool(openwebui.deleted_tools)),
            self.assertRaisesRegex(RuntimeError, "OpenWebUI sync interrupted"),
        ):
            service.sync_once()

        self.assertEqual(openwebui.deleted_tools, ["tool-1"])
        self.assertEqual(openwebui.deleted_functions, [])
        self.assertEqual(ragflow.deleted_chats, [])
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            state = session.get(OpenWebUISyncState, "default")
            self.assertIsNone(mapping.openwebui_tool_id)
            self.assertEqual(mapping.openwebui_pipe_id, "pipe-1")
            self.assertEqual(mapping.ragflow_chat_id, "chat-1")
            assert state is not None
            self.assertEqual(state.status, "paused")

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
        ragflow.chats["chat-old"] = _connector_chat("chat-old", "dataset-old")
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
            new_tool_id = str(mapping.openwebui_tool_id)
            new_pipe_id = str(mapping.openwebui_pipe_id)
        self.assertLess(
            openwebui.operations.index(("tool_valves", new_tool_id)),
            openwebui.operations.index(("delete_tool", "tool-old")),
        )
        self.assertLess(
            openwebui.operations.index(("activate_function", new_pipe_id)),
            openwebui.operations.index(("delete_function", "pipe-old")),
        )

    def test_chat_cleanup_keeps_provenance_across_multiple_dataset_transitions(
        self,
    ) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repo-1",
                    name="Demo",
                    name_slug="demo",
                    ragflow_dataset_id="dataset-b",
                    ragflow_dataset_name="Demo Dataset",
                    status="active",
                )
            )
            session.add(
                OpenWebUIDatasetMapping(
                    repo_id="repo-1",
                    ragflow_dataset_id="dataset-a",
                    ragflow_dataset_name="Demo Dataset",
                    ragflow_chat_id="chat-a",
                    sync_status="synced",
                )
            )
            session.commit()
        ragflow = _FailingChatDeleteOnceRAGFlowClient("chat-a")
        ragflow.chats["chat-a"] = _connector_chat("chat-a", "dataset-a")
        ragflow.chats["foreign-chat"] = {
            "id": "foreign-chat",
            "name": "foreign",
            "dataset_ids": ["dataset-a"],
        }
        service = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        first_summary = service.sync_once()

        self.assertEqual(first_summary.failed, 0)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            chat_b = str(mapping.ragflow_chat_id)
            pending = mapping.capabilities_snapshot["pending_replacement_cleanup"]
            self.assertEqual(
                pending["chats"],
                [
                    {
                        "id": "chat-a",
                        "expected_dataset_id": "dataset-a",
                        "provenance": "dataset_id_replacement",
                    }
                ],
            )
            pending = {
                **pending,
                "chats": [*pending["chats"], "foreign-chat"],
            }
            mapping.capabilities_snapshot = {
                **mapping.capabilities_snapshot,
                "pending_replacement_cleanup": pending,
            }
            library = session.get(Library, "repo-1")
            assert library is not None
            library.ragflow_dataset_id = "dataset-c"
            session.commit()

        second_summary = service.sync_once()

        self.assertEqual(second_summary.failed, 0)
        self.assertEqual(ragflow.deleted_chats, [["chat-a"], [chat_b]])
        deleted_chat_ids = {
            chat_id for ids in ragflow.deleted_chats for chat_id in ids
        }
        self.assertNotIn("foreign-chat", deleted_chat_ids)
        self.assertIn("foreign-chat", ragflow.chats)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.ragflow_dataset_id, "dataset-c")
            self.assertEqual(mapping.sync_status, "manual_required")
            pending = mapping.capabilities_snapshot["pending_replacement_cleanup"]
            self.assertEqual(
                pending["chats"],
                [
                    {
                        "id": "foreign-chat",
                        "expected_dataset_id": None,
                        "provenance": "legacy_id_only_unverified",
                    }
                ],
            )

    def test_artifact_id_change_keeps_previous_binding_when_create_fails(self) -> None:
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
        openwebui = _FailingToolCreateOpenWebUIClient()
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

        self.assertEqual(summary.failed, 1)
        self.assertEqual(openwebui.deleted_tools, [])
        self.assertEqual(openwebui.deleted_functions, [])
        self.assertEqual(ragflow.deleted_chats, [])
        self.assertIn("tool-old", openwebui.tools)
        self.assertIn("pipe-old", openwebui.functions)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.ragflow_chat_id, "chat-old")
            self.assertEqual(mapping.openwebui_tool_id, "tool-old")
            self.assertEqual(mapping.openwebui_pipe_id, "pipe-old")
            self.assertEqual(mapping.sync_status, "failed")

    def test_deferred_replacement_cleanup_is_persisted_and_retried(self) -> None:
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
        openwebui = _FailingDeleteOnceOpenWebUIClient("tool-old")
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

        first_summary = service.sync_once()

        self.assertEqual(first_summary.failed, 0)
        self.assertIn("tool-old", openwebui.tools)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            pending = mapping.capabilities_snapshot["pending_replacement_cleanup"]
            self.assertEqual(pending, {"tools": ["tool-old"], "pipes": [], "chats": []})

        second_summary = service.sync_once()

        self.assertEqual(second_summary.failed, 0)
        self.assertEqual(openwebui.deleted_tools, ["tool-old"])
        self.assertNotIn("tool-old", openwebui.tools)
        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertNotIn(
                "pending_replacement_cleanup",
                mapping.capabilities_snapshot,
            )


if __name__ == "__main__":
    unittest.main()
