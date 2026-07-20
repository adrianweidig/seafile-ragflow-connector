from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from seafile_ragflow_connector.domain.naming import slugify
    from seafile_ragflow_connector.openwebui.artifacts import build_pipe_id, build_tool_id
    from seafile_ragflow_connector.openwebui.sync import _chat_name
    from seafile_ragflow_connector.persistence.db import Base
    from seafile_ragflow_connector.persistence.models.library import Library
    from seafile_ragflow_connector.sync.target_cleanup import TargetCleanupService
    from seafile_ragflow_connector.utils.hashing import sha256_text
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
    create_engine = None  # type: ignore[assignment]


class _FakeRAGFlowClient:
    def __init__(self) -> None:
        active_chat_name = _chat_name("ragflow", ACTIVE_DATASET_NAME, "active-ds")
        self.datasets = [
            {"id": "active-ds", "name": ACTIVE_DATASET_NAME},
            {"id": "orphan-ds", "name": "RAG_old_repoorph"},
            {"id": "legacy-orphan-ds", "name": "seafile__old__repoorph"},
            {"id": "manual-ds", "name": "manual"},
        ]
        self.chats = [
            {
                "id": "active-chat",
                "name": active_chat_name,
                "dataset_ids": ["active-ds"],
            },
            {
                "id": "orphan-chat",
                "name": _chat_name("ragflow", "RAG_old_repoorph", "orphan-ds"),
                "dataset_ids": ["orphan-ds"],
            },
            {
                "id": "legacy-orphan-chat",
                "name": _legacy_chat_name(
                    "ragflow",
                    "seafile__old__repoorph",
                    "legacy-orphan-ds",
                ),
                "dataset_ids": ["legacy-orphan-ds"],
            },
            {"id": "manual-chat", "name": "manual", "dataset_ids": ["manual-ds"]},
            {
                "id": "manual-rag-chat",
                "name": f"RAG_manual_{sha256_text('orphan-ds')[:8]}",
                "dataset_ids": ["orphan-ds"],
            },
            {
                "id": "manual-legacy-chat",
                "name": (
                    "owui__ragflow__manual__"
                    f"{sha256_text('legacy-orphan-ds')[:8]}"
                ),
                "dataset_ids": ["legacy-orphan-ds"],
            },
        ]
        self.deleted_datasets: list[list[str]] = []
        self.deleted_chats: list[list[str]] = []

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None):
        if name is not None:
            return [item for item in self.datasets if item["name"] == name]
        return self.datasets

    def delete_datasets(self, dataset_ids: list[str]):
        self.deleted_datasets.append(dataset_ids)
        return True

    def list_chats(self, *, name: str | None = None, chat_id: str | None = None):
        return self.chats

    def delete_chats(self, chat_ids: list[str]):
        self.deleted_chats.append(chat_ids)
        return True


class _FakeOpenWebUIClient:
    def __init__(self) -> None:
        owned = {"content": "owner: seafile-ragflow-connector"}
        active_tool_id = build_tool_id("ragflow", ACTIVE_DATASET_NAME, "active-ds")
        active_pipe_id = build_pipe_id("ragflow", ACTIVE_DATASET_NAME, "active-ds")
        self.tools = [
            {"id": active_tool_id, **owned},
            {"id": "ragflow_tool_old_orphan_ds", **owned},
            {"id": "foreign", "content": "manual"},
        ]
        self.functions = [
            {"id": active_pipe_id, **owned},
            {"id": "ragflow_pipe_old_orphan_ds", **owned},
        ]
        self.deleted_tools: list[str] = []
        self.deleted_functions: list[str] = []

    def list_tools(self):
        return self.tools

    def delete_tool(self, tool_id: str):
        self.deleted_tools.append(tool_id)
        return True

    def list_functions(self):
        return self.functions

    def delete_function(self, function_id: str):
        self.deleted_functions.append(function_id)
        return True


class _DatasetOnlyRAGFlowClient:
    def __init__(self) -> None:
        self.datasets = [
            {"id": "orphan-ds", "name": "RAG_old_repoorph"},
            {"id": "legacy-orphan-ds", "name": "seafile__old__repoorph"},
        ]
        self.chats = [
            {
                "id": "legacy-orphan-chat",
                "name": _legacy_chat_name(
                    "ragflow",
                    "seafile__old__repoorph",
                    "legacy-orphan-ds",
                ),
                "dataset_ids": ["legacy-orphan-ds"],
            }
        ]
        self.deleted_datasets: list[list[str]] = []
        self.deleted_chats: list[list[str]] = []

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None):
        if name is not None:
            return [item for item in self.datasets if item["name"] == name]
        return self.datasets

    def delete_datasets(self, dataset_ids: list[str]):
        self.deleted_datasets.append(dataset_ids)
        return True

    def list_chats(self, *, name: str | None = None, chat_id: str | None = None):
        return self.chats

    def delete_chats(self, chat_ids: list[str]):
        self.deleted_chats.append(chat_ids)
        return True


class _ChatOnlyRAGFlowClient:
    def __init__(self) -> None:
        self.chats = [
            {
                "id": "orphan-chat",
                "name": _chat_name("ragflow", "RAG_old_repoorph", "orphan-ds"),
                "dataset_ids": ["orphan-ds"],
            },
            {
                "id": "manual-rag-chat",
                "name": f"RAG_manual_{sha256_text('orphan-ds')[:8]}",
                "dataset_ids": ["orphan-ds"],
            },
        ]
        self.deleted_chats: list[list[str]] = []

    def list_datasets(self, *, name: str | None = None, parse_status: str | None = None):
        raise AssertionError("The chat RAGFlow client must not list datasets")

    def delete_datasets(self, dataset_ids: list[str]):
        raise AssertionError("The chat RAGFlow client must not delete datasets")

    def list_chats(self, *, name: str | None = None, chat_id: str | None = None):
        return self.chats

    def delete_chats(self, chat_ids: list[str]):
        self.deleted_chats.append(chat_ids)
        return True


def _session_factory(test_case: unittest.TestCase):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_case.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _legacy_chat_name(namespace: str, dataset_name: str, dataset_id: str) -> str:
    slug = slugify(dataset_name, fallback="dataset").replace("-", "_")
    return f"owui__{namespace}__{slug}__{sha256_text(dataset_id)[:8]}"


ACTIVE_DATASET_NAME = "RAG_active_repoacti"


@unittest.skipIf(create_engine is None, "sqlalchemy is not installed in this Python environment")
class TargetCleanupServiceTests(unittest.TestCase):
    def test_split_owner_cleanup_routes_only_deterministic_chats_to_their_owner(self) -> None:
        session_factory = _session_factory(self)
        primary = _DatasetOnlyRAGFlowClient()
        interactive = _ChatOnlyRAGFlowClient()
        service = TargetCleanupService(
            session_factory=session_factory,
            ragflow_client=primary,  # type: ignore[arg-type]
            ragflow_chat_client=interactive,  # type: ignore[arg-type]
        )

        summary = service.cleanup([], execute=True)

        self.assertEqual(
            summary.planned["ragflow_datasets"],
            ["orphan-ds", "legacy-orphan-ds"],
        )
        self.assertEqual(
            summary.planned["ragflow_chats"],
            ["legacy-orphan-chat", "orphan-chat"],
        )
        self.assertEqual(primary.deleted_datasets, [["orphan-ds", "legacy-orphan-ds"]])
        self.assertEqual(primary.deleted_chats, [["legacy-orphan-chat"]])
        self.assertEqual(interactive.deleted_chats, [["orphan-chat"]])

    def test_dry_run_plans_only_connector_owned_orphans(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repoactive",
                    name="Active",
                    name_slug="active",
                    status="active",
                    ragflow_dataset_id="active-ds",
                    ragflow_dataset_name=ACTIVE_DATASET_NAME,
                )
            )
            session.commit()
        service = TargetCleanupService(
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.cleanup(
            [SimpleNamespace(repo_id="repoactive", name="Active")],
            execute=False,
        )

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.planned["ragflow_datasets"], ["orphan-ds", "legacy-orphan-ds"])
        self.assertEqual(
            summary.planned["ragflow_chats"],
            ["orphan-chat", "legacy-orphan-chat"],
        )
        self.assertEqual(summary.planned["openwebui_tools"], ["ragflow_tool_old_orphan_ds"])
        self.assertEqual(
            summary.planned["openwebui_functions"],
            ["ragflow_pipe_old_orphan_ds"],
        )

    def test_execute_deletes_planned_orphans(self) -> None:
        session_factory = _session_factory(self)
        with session_factory() as session:
            session.add(
                Library(
                    repo_id="repoactive",
                    name="Active",
                    name_slug="active",
                    status="active",
                    ragflow_dataset_id="active-ds",
                    ragflow_dataset_name=ACTIVE_DATASET_NAME,
                )
            )
            session.commit()
        ragflow = _FakeRAGFlowClient()
        openwebui = _FakeOpenWebUIClient()
        service = TargetCleanupService(
            session_factory=session_factory,
            ragflow_client=ragflow,  # type: ignore[arg-type]
            openwebui_client=openwebui,  # type: ignore[arg-type]
        )

        summary = service.cleanup(
            [SimpleNamespace(repo_id="repoactive", name="Active")],
            execute=True,
        )

        self.assertFalse(summary.dry_run)
        self.assertEqual(ragflow.deleted_datasets, [["orphan-ds", "legacy-orphan-ds"]])
        self.assertEqual(ragflow.deleted_chats, [["orphan-chat", "legacy-orphan-chat"]])
        self.assertEqual(openwebui.deleted_tools, ["ragflow_tool_old_orphan_ds"])
        self.assertEqual(openwebui.deleted_functions, ["ragflow_pipe_old_orphan_ds"])

    def test_existing_current_ragflow_dataset_protects_openwebui_artifacts_after_state_loss(
        self,
    ) -> None:
        session_factory = _session_factory(self)
        service = TargetCleanupService(
            session_factory=session_factory,
            ragflow_client=_FakeRAGFlowClient(),  # type: ignore[arg-type]
            openwebui_client=_FakeOpenWebUIClient(),  # type: ignore[arg-type]
        )

        summary = service.cleanup(
            [SimpleNamespace(repo_id="repoactive", name="Active")],
            execute=False,
        )

        active_tool_id = build_tool_id("ragflow", ACTIVE_DATASET_NAME, "active-ds")
        active_pipe_id = build_pipe_id("ragflow", ACTIVE_DATASET_NAME, "active-ds")
        self.assertNotIn(active_tool_id, summary.planned["openwebui_tools"])
        self.assertNotIn(active_pipe_id, summary.planned["openwebui_functions"])


if __name__ == "__main__":
    unittest.main()
