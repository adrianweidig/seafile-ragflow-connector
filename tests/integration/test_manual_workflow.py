from __future__ import annotations

import unittest
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from seafile_ragflow_connector.clients.openwebui import OpenWebUICapabilities
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, DashboardLimits
from seafile_ragflow_connector.domain.file_classification import FilePolicy
from seafile_ragflow_connector.openwebui.sync import OpenWebUISyncService
from seafile_ragflow_connector.persistence.db import Base
from seafile_ragflow_connector.persistence.models.file import File
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import (
    OpenWebUIDatasetMapping,
    OpenWebUISyncState,
)
from seafile_ragflow_connector.sync.orchestrator import SyncOrchestrator

WORKFLOW_REPO_ID = "manual-workflow-repo-20260601"
WORKFLOW_LIBRARY_NAME = "Codex Workflow Check"
WORKFLOW_FOLDER = "/manual-workflow-check"
WORKFLOW_FILE = f"{WORKFLOW_FOLDER}/seafile-ragflow-openwebui-check.md"
WORKFLOW_CONTENT = (
    b"# Codex Workflow Check\n\n"
    b"Diese Datei belegt den manuellen Seafile-zu-RAGFlow-zu-OpenWebUI-Ablauf.\n"
)


class _FakeSeafileAdminClient:
    def __init__(self) -> None:
        self.libraries = [
            {
                "id": WORKFLOW_REPO_ID,
                "name": WORKFLOW_LIBRARY_NAME,
                "owner": "workflow-check@example.local",
                "encrypted": False,
                "virtual": False,
                "mtime": 1_717_171_717,
                "head_commit_id": "workflow-head-001",
            }
        ]

    def iter_libraries(self):
        return iter(self.libraries)


class _FakeSeafileSyncClient:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, str]] = []

    def list_dir(self, repo_id: str, path: str):
        if repo_id != WORKFLOW_REPO_ID:
            return []
        if path == "/":
            return [{"name": WORKFLOW_FOLDER.strip("/"), "type": "dir"}]
        if path == WORKFLOW_FOLDER:
            return [
                {
                    "name": "seafile-ragflow-openwebui-check.md",
                    "type": "file",
                    "id": "seafile-file-workflow-001",
                    "size": len(WORKFLOW_CONTENT),
                    "mtime": 1_717_171_718,
                }
            ]
        return []

    def download_file(self, repo_id: str, path: str) -> bytes:
        self.downloads.append((repo_id, path))
        if repo_id != WORKFLOW_REPO_ID or path != WORKFLOW_FILE:
            raise FileNotFoundError(f"unexpected Seafile test path: {repo_id}:{path}")
        return WORKFLOW_CONTENT


class _FakeRAGFlowClient:
    def __init__(self) -> None:
        self.datasets_by_name: dict[str, dict[str, Any]] = {}
        self.documents_by_dataset: dict[str, list[dict[str, Any]]] = {}
        self.created_datasets: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.metadata_updates: list[tuple[str, str, dict[str, object]]] = []
        self.parsed_documents: list[tuple[str, list[str]]] = []
        self.chats: dict[str, dict[str, Any]] = {}
        self.created_chats: list[dict[str, Any]] = []
        self.deleted_chats: list[list[str]] = []
        self._next_chat_id = 1

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None):
        _ = parse_status
        datasets = list(self.datasets_by_name.values())
        if name is not None:
            return [dataset for dataset in datasets if dataset.get("name") == name]
        return datasets

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        for dataset in self.datasets_by_name.values():
            if dataset.get("id") == dataset_id:
                return dataset
        raise KeyError(f"unknown RAGFlow dataset in manual workflow test: {dataset_id}")

    def create_dataset(self, payload: dict[str, object]) -> dict[str, Any]:
        name = str(payload["name"])
        dataset_id = "dataset-template" if name == "connector_template" else "dataset-workflow"
        dataset = {"id": dataset_id, **payload}
        self.datasets_by_name[name] = dataset
        self.created_datasets.append(dataset)
        return dataset

    def update_dataset(
        self,
        dataset_id: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        for name, dataset in self.datasets_by_name.items():
            if dataset.get("id") == dataset_id:
                updated = {**dataset, **payload}
                self.datasets_by_name[name] = updated
                return updated
        return {"id": dataset_id, **payload}

    def list_documents(
        self,
        dataset_id: str,
        *,
        keywords: str | None = None,
        page_size: int | None = None,
    ):
        _ = page_size
        documents = list(self.documents_by_dataset.get(dataset_id, []))
        if keywords:
            return [document for document in documents if keywords in str(document.get("name"))]
        return documents

    def iter_documents(
        self,
        dataset_id: str,
        *,
        run: str | None = None,
        keywords: str | None = None,
        page_size: int = 100,
    ):
        _ = (run, page_size)
        return iter(self.list_documents(dataset_id, keywords=keywords))

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        documents = self.documents_by_dataset.get(dataset_id, [])
        self.documents_by_dataset[dataset_id] = [
            document for document in documents if document.get("id") not in document_ids
        ]

    def delete_datasets(self, dataset_ids: list[str]) -> None:
        self.datasets_by_name = {
            name: dataset
            for name, dataset in self.datasets_by_name.items()
            if dataset.get("id") not in dataset_ids
        }

    def upload_document(
        self,
        dataset_id: str,
        *,
        document_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, str]:
        document_id = f"doc-workflow-{len(self.uploads) + 1}"
        self.uploads.append(
            {
                "dataset_id": dataset_id,
                "document_name": document_name,
                "content": content,
                "mime_type": mime_type,
            }
        )
        self.documents_by_dataset.setdefault(dataset_id, []).append(
            {"id": document_id, "name": document_name, "run": "RUNNING"}
        )
        return {"id": document_id}

    def update_document_metadata(
        self,
        dataset_id: str,
        document_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        self.metadata_updates.append((dataset_id, document_id, metadata))
        for document in self.documents_by_dataset.get(dataset_id, []):
            if document.get("id") == document_id:
                document["metadata"] = dict(metadata)
        return {"id": document_id, "metadata": metadata}

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self.parsed_documents.append((dataset_id, document_ids))
        for document in self.documents_by_dataset.get(dataset_id, []):
            if document.get("id") in document_ids:
                document["run"] = "DONE"

    def get_chat(self, chat_id: str):
        return self.chats.get(chat_id)

    def list_chats(self, *, name: str | None = None, chat_id: str | None = None):
        chats = list(self.chats.values())
        if chat_id:
            chats = [chat for chat in chats if str(chat.get("id")) == chat_id]
        if name:
            chats = [chat for chat in chats if chat.get("name") == name]
        return chats

    def create_chat(self, payload: dict[str, object]) -> dict[str, Any]:
        chat_id = f"chat-workflow-{self._next_chat_id}"
        self._next_chat_id += 1
        chat = {"id": chat_id, **payload}
        self.chats[chat_id] = chat
        self.created_chats.append(chat)
        return chat

    def update_chat(self, chat_id: str, payload: dict[str, object]) -> dict[str, Any]:
        chat = {"id": chat_id, **payload}
        self.chats[chat_id] = chat
        return chat

    def delete_chats(self, chat_ids: list[str]) -> bool:
        self.deleted_chats.append(chat_ids)
        for chat_id in chat_ids:
            self.chats.pop(chat_id, None)
        return True


class _FakeOpenWebUIClient:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, object]] = {}
        self.functions: dict[str, dict[str, object]] = {}
        self.tool_valves: dict[str, dict[str, object]] = {}
        self.function_valves: dict[str, dict[str, object]] = {}

    def probe_capabilities(self) -> OpenWebUICapabilities:
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
        self.tool_valves[tool_id] = dict(valves)
        return valves

    def get_function(self, function_id: str):
        return self.functions.get(function_id)

    def create_function(self, payload: dict[str, object]):
        self.functions[str(payload["id"])] = {**payload, "is_active": True}
        return payload

    def update_function(self, function_id: str, payload: dict[str, object]):
        self.functions[function_id] = {**payload, "is_active": True}
        return payload

    def update_function_valves(self, function_id: str, valves: dict[str, object]):
        self.function_valves[function_id] = dict(valves)
        return valves

    def ensure_function_active(self, function_id: str):
        function = self.functions.setdefault(function_id, {"id": function_id})
        function["is_active"] = True
        return function


class _UnreachableOpenWebUIClient(_FakeOpenWebUIClient):
    def probe_capabilities(self) -> OpenWebUICapabilities:
        return OpenWebUICapabilities(
            reachable=False,
            error="OpenWebUI API ist für den manuellen Workflow-Test nicht erreichbar",
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


def _settings() -> Settings:
    return Settings(
        seafile_base_url="http://seafile.local",
        seafile_admin_token="seafile-admin-token",
        seafile_sync_user_token="seafile-sync-token",
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key="ragflow-api-key",
        database_url="sqlite://",
        redis_url="redis://127.0.0.1:1/0",
        connector_language="de",
        openwebui_integration_enabled=True,
        openwebui_base_url="http://openwebui.local",
        openwebui_admin_api_key="openwebui-admin-key",
        openwebui_sync_mode="sync",
        openwebui_proxy_internal_base_url="http://connector:8080",
        openwebui_proxy_public_base_url="https://connector.top.secret",
        openwebui_proxy_shared_secret="proxy-secret",
        openwebui_source_preview_mode="connector_viewer",
    )


class ManualWorkflowIntegrationTests(unittest.TestCase):
    def test_seafile_file_sync_creates_ragflow_dataset_and_openwebui_pipe(self) -> None:
        session_factory = _session_factory(self)
        dashboard_store = DashboardEventStore(session_factory, DashboardLimits())
        seafile_sync = _FakeSeafileSyncClient()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()

        orchestrator = SyncOrchestrator(
            session_factory,
            admin_client=_FakeSeafileAdminClient(),  # type: ignore[arg-type]
            sync_client=seafile_sync,  # type: ignore[arg-type]
            ragflow_client=ragflow,  # type: ignore[arg-type]
            file_policy=FilePolicy(),
            template_dataset_name="connector_template",
            dashboard_store=dashboard_store,
        )

        sync_summary = orchestrator.sync_once()

        self.assertEqual(sync_summary.libraries_seen, 1)
        self.assertEqual(sync_summary.libraries_synced, 1)
        self.assertEqual(sync_summary.files_seen, 1)
        self.assertEqual(sync_summary.files_uploaded, 1)
        self.assertEqual(seafile_sync.downloads, [(WORKFLOW_REPO_ID, WORKFLOW_FILE)])

        with session_factory() as session:
            library = session.get(Library, WORKFLOW_REPO_ID)
            self.assertIsNotNone(library)
            self.assertEqual(library.status, "active")
            self.assertEqual(library.ragflow_dataset_id, "dataset-workflow")
            self.assertTrue(str(library.ragflow_dataset_name).startswith("RAG_"))
            stored_file = session.query(File).one()
            self.assertEqual(stored_file.normalized_path, WORKFLOW_FILE)
            self.assertEqual(stored_file.sync_status, "uploaded")
            self.assertEqual(stored_file.ragflow_document_id, "doc-workflow-1")

        self.assertEqual(
            [dataset["name"] for dataset in ragflow.created_datasets][0],
            "connector_template",
        )
        self.assertEqual(ragflow.uploads[0]["dataset_id"], "dataset-workflow")
        self.assertTrue(str(ragflow.uploads[0]["document_name"]).endswith(".md.txt"))
        self.assertEqual(ragflow.metadata_updates[0][2]["repo_id"], WORKFLOW_REPO_ID)
        self.assertEqual(ragflow.metadata_updates[0][2]["source_path"], WORKFLOW_FILE)
        self.assertEqual(ragflow.parsed_documents, [("dataset-workflow", ["doc-workflow-1"])])

        openwebui_summary = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
            dashboard_store=dashboard_store,
        ).sync_once()

        self.assertEqual(openwebui_summary.datasets_seen, 1)
        self.assertEqual(openwebui_summary.chats_created, 1)
        self.assertEqual(openwebui_summary.tools_created, 1)
        self.assertEqual(openwebui_summary.pipes_created, 1)
        dataset_chat = next(
            chat
            for chat in ragflow.created_chats
            if chat.get("dataset_ids") == ["dataset-workflow"]
        )

        with session_factory() as session:
            mapping = session.query(OpenWebUIDatasetMapping).one()
            self.assertEqual(mapping.repo_id, WORKFLOW_REPO_ID)
            self.assertEqual(mapping.ragflow_dataset_id, "dataset-workflow")
            self.assertEqual(mapping.ragflow_chat_id, dataset_chat["id"])
            self.assertEqual(mapping.sync_status, "synced")
            self.assertEqual(
                mapping.openwebui_pipe_payload["meta"]["manifest"]["ragflow_dataset_id"],
                "dataset-workflow",
            )
            self.assertEqual(
                mapping.openwebui_pipe_payload["meta"]["manifest"]["repo_id"],
                WORKFLOW_REPO_ID,
            )

        pipe_id = next(iter(openwebui.functions))
        pipe_valves = openwebui.function_valves[pipe_id]
        self.assertEqual(pipe_valves["DATASET_ID"], "dataset-workflow")
        self.assertEqual(pipe_valves["RAGFLOW_CHAT_ID"], dataset_chat["id"])
        self.assertEqual(pipe_valves["CONNECTOR_PROXY_BASE_URL"], "http://connector:8080")
        self.assertEqual(pipe_valves["CONNECTOR_PROXY_SHARED_SECRET"], "proxy-secret")
        self.assertIn(pipe_id, openwebui.functions)
        self.assertTrue(openwebui.functions[pipe_id]["is_active"])

        systems = dashboard_store.systems()
        self.assertEqual(systems["source"]["libraries"][0]["repo_id"], WORKFLOW_REPO_ID)
        self.assertEqual(systems["target"]["datasets"][0]["dataset_id"], "dataset-workflow")
        self.assertEqual(systems["openwebui"]["counts"]["synced_or_planned"], 1)

    def test_openwebui_reachability_error_is_visible_in_state(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id=WORKFLOW_REPO_ID,
                    name=WORKFLOW_LIBRARY_NAME,
                    name_slug="codex-workflow-check",
                    ragflow_dataset_id="dataset-workflow",
                    ragflow_dataset_name="RAG_codex_workflow_check_manualw",
                    status="active",
                )
            )
            session.commit()

        summary = OpenWebUISyncService(
            settings=_settings(),
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=_UnreachableOpenWebUIClient(),  # type: ignore[arg-type]
            dashboard_store=DashboardEventStore(session_factory, DashboardLimits()),
        ).sync_once()

        self.assertEqual(summary.failed, 1)
        with session_factory() as session:
            state = session.get(OpenWebUISyncState, "default")
            self.assertIsNotNone(state)
            self.assertEqual(state.status, "failed")
            self.assertIn("nicht erreichbar", state.last_error or "")


if __name__ == "__main__":
    unittest.main()
