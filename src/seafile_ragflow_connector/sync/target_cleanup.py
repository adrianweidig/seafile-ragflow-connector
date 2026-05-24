from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.clients import OpenWebUIClient, RAGFlowClient
from seafile_ragflow_connector.domain.naming import build_dataset_name
from seafile_ragflow_connector.openwebui.artifacts import (
    DatasetArtifactInputs,
    build_pipe_id,
    build_tool_id,
)
from seafile_ragflow_connector.openwebui.sync import _chat_name, _is_connector_owned
from seafile_ragflow_connector.persistence.models.library import Library

CONNECTOR_DATASET_PREFIX = "seafile__"


@dataclass(frozen=True)
class CleanupPlan:
    ragflow_dataset_ids: list[str] = field(default_factory=list)
    ragflow_chat_ids: list[str] = field(default_factory=list)
    openwebui_tool_ids: list[str] = field(default_factory=list)
    openwebui_function_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CleanupSummary:
    dry_run: bool
    ragflow_datasets_planned: int = 0
    ragflow_datasets_deleted: int = 0
    ragflow_chats_planned: int = 0
    ragflow_chats_deleted: int = 0
    openwebui_tools_planned: int = 0
    openwebui_tools_deleted: int = 0
    openwebui_functions_planned: int = 0
    openwebui_functions_deleted: int = 0
    warnings: list[str] = field(default_factory=list)
    planned: dict[str, list[str]] = field(default_factory=dict)


class TargetCleanupService:
    """Prune connector-owned target artifacts that no current Seafile library owns."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        ragflow_client: RAGFlowClient,
        openwebui_client: OpenWebUIClient | None = None,
        openwebui_namespace: str = "ragflow",
    ) -> None:
        self.session_factory = session_factory
        self.ragflow_client = ragflow_client
        self.openwebui_client = openwebui_client
        self.openwebui_namespace = openwebui_namespace

    def plan(self, current_libraries: Sequence[LibrarySourceLike]) -> CleanupPlan:
        expected_dataset_names = {
            build_dataset_name(library.name, library.repo_id)
            for library in current_libraries
        }
        ragflow_datasets = self.ragflow_client.list_datasets()
        expected_dataset_ids_by_name = self._expected_dataset_ids_by_name(
            expected_dataset_names,
            ragflow_datasets,
        )
        expected_dataset_ids = set(expected_dataset_ids_by_name.values())
        expected_tool_ids, expected_function_ids, expected_chat_names = (
            self._expected_openwebui_artifacts(expected_dataset_ids_by_name)
        )
        ragflow_dataset_ids = self._orphan_ragflow_dataset_ids(
            ragflow_datasets,
            expected_dataset_names,
            expected_dataset_ids_by_name,
        )
        ragflow_chat_ids = self._orphan_ragflow_chat_ids(expected_dataset_ids, expected_chat_names)
        openwebui_tool_ids: list[str] = []
        openwebui_function_ids: list[str] = []
        warnings: list[str] = []

        if self.openwebui_client is None:
            warnings.append("OpenWebUI client is not configured; OpenWebUI cleanup skipped")
        else:
            openwebui_tool_ids = self._orphan_openwebui_tool_ids(expected_tool_ids)
            openwebui_function_ids = self._orphan_openwebui_function_ids(expected_function_ids)

        return CleanupPlan(
            ragflow_dataset_ids=ragflow_dataset_ids,
            ragflow_chat_ids=ragflow_chat_ids,
            openwebui_tool_ids=openwebui_tool_ids,
            openwebui_function_ids=openwebui_function_ids,
            warnings=warnings,
        )

    def cleanup(
        self,
        current_libraries: Sequence[LibrarySourceLike],
        *,
        execute: bool,
    ) -> CleanupSummary:
        plan = self.plan(current_libraries)
        planned = {
            "ragflow_datasets": plan.ragflow_dataset_ids,
            "ragflow_chats": plan.ragflow_chat_ids,
            "openwebui_tools": plan.openwebui_tool_ids,
            "openwebui_functions": plan.openwebui_function_ids,
        }
        if not execute:
            return CleanupSummary(
                dry_run=True,
                ragflow_datasets_planned=len(plan.ragflow_dataset_ids),
                ragflow_chats_planned=len(plan.ragflow_chat_ids),
                openwebui_tools_planned=len(plan.openwebui_tool_ids),
                openwebui_functions_planned=len(plan.openwebui_function_ids),
                warnings=plan.warnings,
                planned=planned,
            )

        ragflow_datasets_deleted = 0
        if plan.ragflow_dataset_ids:
            self.ragflow_client.delete_datasets(plan.ragflow_dataset_ids)
            ragflow_datasets_deleted = len(plan.ragflow_dataset_ids)

        ragflow_chats_deleted = 0
        if plan.ragflow_chat_ids:
            self.ragflow_client.delete_chats(plan.ragflow_chat_ids)
            ragflow_chats_deleted = len(plan.ragflow_chat_ids)

        openwebui_tools_deleted = 0
        openwebui_functions_deleted = 0
        if self.openwebui_client is not None:
            for tool_id in plan.openwebui_tool_ids:
                if self.openwebui_client.delete_tool(tool_id):
                    openwebui_tools_deleted += 1
            for function_id in plan.openwebui_function_ids:
                if self.openwebui_client.delete_function(function_id):
                    openwebui_functions_deleted += 1

        return CleanupSummary(
            dry_run=False,
            ragflow_datasets_planned=len(plan.ragflow_dataset_ids),
            ragflow_datasets_deleted=ragflow_datasets_deleted,
            ragflow_chats_planned=len(plan.ragflow_chat_ids),
            ragflow_chats_deleted=ragflow_chats_deleted,
            openwebui_tools_planned=len(plan.openwebui_tool_ids),
            openwebui_tools_deleted=openwebui_tools_deleted,
            openwebui_functions_planned=len(plan.openwebui_function_ids),
            openwebui_functions_deleted=openwebui_functions_deleted,
            warnings=plan.warnings,
            planned=planned,
        )

    def _expected_dataset_ids_by_name(
        self,
        expected_dataset_names: set[str],
        ragflow_datasets: list[dict[str, Any]],
    ) -> dict[str, str]:
        expected: dict[str, str] = {}
        with self.session_factory() as session:
            rows = session.scalars(
                select(Library)
                .where(Library.status == "active")
                .where(Library.ragflow_dataset_id.is_not(None))
                .order_by(Library.name.asc())
            ).all()
            for library in rows:
                dataset_name = str(library.ragflow_dataset_name or library.name)
                if dataset_name in expected_dataset_names and library.ragflow_dataset_id:
                    expected[dataset_name] = str(library.ragflow_dataset_id)
        for dataset in ragflow_datasets:
            ragflow_dataset_name = _string_or_none(dataset.get("name"))
            dataset_id = _string_or_none(dataset.get("id"))
            if (
                ragflow_dataset_name
                and dataset_id
                and ragflow_dataset_name in expected_dataset_names
                and ragflow_dataset_name not in expected
            ):
                expected[ragflow_dataset_name] = dataset_id
        return expected

    def _expected_openwebui_artifacts(
        self,
        expected_dataset_ids_by_name: dict[str, str],
    ) -> tuple[set[str], set[str], set[str]]:
        tool_ids: set[str] = set()
        function_ids: set[str] = set()
        chat_names: set[str] = set()
        for dataset_name, dataset_id in expected_dataset_ids_by_name.items():
            inputs = DatasetArtifactInputs(
                namespace=self.openwebui_namespace,
                repo_id="",
                dataset_id=dataset_id,
                dataset_name=dataset_name,
                ragflow_chat_id=None,
                proxy_base_url=None,
            )
            tool_ids.add(build_tool_id(inputs.namespace, inputs.dataset_name, inputs.dataset_id))
            function_ids.add(
                build_pipe_id(inputs.namespace, inputs.dataset_name, inputs.dataset_id)
            )
            chat_names.add(_chat_name(inputs.namespace, inputs.dataset_name, inputs.dataset_id))
        return tool_ids, function_ids, chat_names

    def _orphan_ragflow_dataset_ids(
        self,
        ragflow_datasets: list[dict[str, Any]],
        expected_dataset_names: set[str],
        expected_dataset_ids_by_name: dict[str, str],
    ) -> list[str]:
        orphan_ids: list[str] = []
        for dataset in ragflow_datasets:
            dataset_id = _string_or_none(dataset.get("id"))
            dataset_name = _string_or_none(dataset.get("name"))
            if not dataset_id or not dataset_name:
                continue
            if not dataset_name.startswith(CONNECTOR_DATASET_PREFIX):
                continue
            bound_dataset_id = expected_dataset_ids_by_name.get(dataset_name)
            if dataset_name not in expected_dataset_names or (
                bound_dataset_id is not None and dataset_id != bound_dataset_id
            ):
                orphan_ids.append(dataset_id)
        return orphan_ids

    def _orphan_ragflow_chat_ids(
        self,
        expected_dataset_ids: set[str],
        expected_chat_names: set[str],
    ) -> list[str]:
        orphan_ids: list[str] = []
        chat_prefix = f"owui__{self.openwebui_namespace}__"
        for chat in self.ragflow_client.list_chats():
            chat_id = _string_or_none(chat.get("id"))
            chat_name = _string_or_none(chat.get("name"))
            if not chat_id or not chat_name or not chat_name.startswith(chat_prefix):
                continue
            chat_dataset_ids = _chat_dataset_ids(chat)
            if chat_name not in expected_chat_names or not chat_dataset_ids.intersection(
                expected_dataset_ids
            ):
                orphan_ids.append(chat_id)
        return orphan_ids

    def _orphan_openwebui_tool_ids(self, expected_tool_ids: set[str]) -> list[str]:
        if self.openwebui_client is None:
            raise RuntimeError("OpenWebUI cleanup requires an OpenWebUI client")
        orphan_ids: list[str] = []
        for tool in self.openwebui_client.list_tools():
            tool_id = _string_or_none(tool.get("id"))
            if tool_id and tool_id not in expected_tool_ids and _is_connector_owned(tool):
                orphan_ids.append(tool_id)
        return orphan_ids

    def _orphan_openwebui_function_ids(self, expected_function_ids: set[str]) -> list[str]:
        if self.openwebui_client is None:
            raise RuntimeError("OpenWebUI cleanup requires an OpenWebUI client")
        orphan_ids: list[str] = []
        for function in self.openwebui_client.list_functions():
            function_id = _string_or_none(function.get("id"))
            if (
                function_id
                and function_id not in expected_function_ids
                and _is_connector_owned(function)
            ):
                orphan_ids.append(function_id)
        return orphan_ids


class LibrarySourceLike(Protocol):
    repo_id: str
    name: str


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _chat_dataset_ids(chat: dict[str, Any]) -> set[str]:
    dataset_ids = chat.get("dataset_ids") or chat.get("datasets") or []
    result: set[str] = set()
    if not isinstance(dataset_ids, list):
        return result
    for item in dataset_ids:
        if isinstance(item, dict) and item.get("id"):
            result.add(str(item["id"]))
        elif item:
            result.add(str(item))
    return result
