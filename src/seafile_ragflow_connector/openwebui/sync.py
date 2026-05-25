from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.clients.openwebui import OpenWebUICapabilities, OpenWebUIClient
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, new_sync_id, safe_text
from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.openwebui.artifacts import (
    ARTIFACT_VERSION,
    DatasetArtifactInputs,
    OpenWebUIArtifactSpec,
    build_model_name,
    build_pipe_spec,
    build_tool_spec,
)
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import (
    OpenWebUIDatasetMapping,
    OpenWebUISyncState,
)
from seafile_ragflow_connector.utils.hashing import sha256_text
from seafile_ragflow_connector.utils.redaction import redact_mapping


@dataclass
class OpenWebUISyncSummary:
    datasets_seen: int = 0
    chats_created: int = 0
    chats_reused: int = 0
    tools_created: int = 0
    tools_updated: int = 0
    tools_reused: int = 0
    tools_deleted: int = 0
    pipes_created: int = 0
    pipes_updated: int = 0
    pipes_reused: int = 0
    pipes_deleted: int = 0
    chats_deleted: int = 0
    manual_required: int = 0
    failed: int = 0
    dry_run: bool = False


class OpenWebUISyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        ragflow_client: RAGFlowClient,
        openwebui_client: OpenWebUIClient | None = None,
        dashboard_store: DashboardEventStore | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.ragflow_client = ragflow_client
        self.openwebui_client = openwebui_client
        self.dashboard_store = dashboard_store
        self.log = structlog.get_logger(__name__)

    def sync_once(
        self,
        *,
        mode_override: Literal["disabled", "dry-run", "sync", "repair"] | None = None,
    ) -> OpenWebUISyncSummary:
        mode = mode_override or self.settings.openwebui_effective_sync_mode
        summary = OpenWebUISyncSummary(dry_run=mode == "dry-run")
        if mode == "disabled":
            self._write_global_state(status="disabled", mode=mode, summary=summary)
            self.log.info("openwebui.integration.disabled")
            return summary

        sync_id = new_sync_id("openwebui")
        started = time.perf_counter()
        self._write_global_state(status="running", mode=mode, summary=summary, sync_started=True)
        self._create_dashboard_run(sync_id, mode)
        self.log.info("openwebui.sync.started", sync_id=sync_id, mode=mode, dry_run=summary.dry_run)
        capabilities = self._probe_capabilities(mode)
        blocker = self._sync_blocker(mode, capabilities)
        if blocker:
            summary.failed += 1
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._write_global_state(
                status="failed",
                mode=mode,
                summary=summary,
                capabilities=capabilities,
                sync_finished=True,
                error=blocker,
            )
            self._finish_dashboard_run(sync_id, "failed", summary, duration_ms)
            self.log.warning(
                "openwebui.healthcheck.failed",
                sync_id=sync_id,
                mode=mode,
                error=blocker,
            )
            self.log.info(
                "openwebui.sync.completed",
                sync_id=sync_id,
                mode=mode,
                duration_ms=duration_ms,
                **summary.__dict__,
            )
            return summary
        try:
            self._sync_deleted_library_mappings(
                mode=mode,
                capabilities=capabilities,
                summary=summary,
                sync_id=sync_id,
            )
            for library in self._discover_libraries():
                summary.datasets_seen += 1
                self.log.info(
                    "openwebui.sync.dataset.discovered",
                    sync_id=sync_id,
                    repo_id=library.repo_id,
                    dataset_id=library.ragflow_dataset_id,
                    dataset_name=library.ragflow_dataset_name,
                )
                try:
                    self._sync_library(
                        library,
                        mode=mode,
                        capabilities=capabilities,
                        summary=summary,
                        sync_id=sync_id,
                    )
                except Exception as exc:
                    summary.failed += 1
                    self._mark_dataset_failed(library, str(exc), capabilities)
                    self.log.warning(
                        "openwebui.sync.dataset.failed",
                        sync_id=sync_id,
                        repo_id=library.repo_id,
                        dataset_id=library.ragflow_dataset_id,
                        error=str(exc),
                    )
        finally:
            if summary.failed:
                status = "failed"
            elif summary.manual_required:
                status = "manual_required"
            else:
                status = "succeeded"
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._write_global_state(
                status=status,
                mode=mode,
                summary=summary,
                capabilities=capabilities,
                sync_finished=True,
            )
            self._finish_dashboard_run(sync_id, status, summary, duration_ms)
            self.log.info(
                "openwebui.sync.completed",
                sync_id=sync_id,
                mode=mode,
                duration_ms=duration_ms,
                **summary.__dict__,
            )
        return summary

    def _sync_library(
        self,
        library: Library,
        *,
        mode: str,
        capabilities: OpenWebUICapabilities,
        summary: OpenWebUISyncSummary,
        sync_id: str,
    ) -> None:
        dataset_id = str(library.ragflow_dataset_id)
        dataset_name = str(library.ragflow_dataset_name or library.name)
        mapping = self._ensure_mapping(library, capabilities)
        previous_tool_hash = mapping.tool_definition_hash
        previous_pipe_hash = mapping.pipe_definition_hash
        previous_tool_id = mapping.openwebui_tool_id
        previous_pipe_id = mapping.openwebui_pipe_id
        previous_chat_id = mapping.ragflow_chat_id
        chat_name = _chat_name(self.settings.openwebui_function_namespace, dataset_name, dataset_id)
        chat_id, created = self._ensure_chat(mapping, chat_name, dataset_id, mode)
        if chat_id:
            if created:
                summary.chats_created += 1
                self.log.info(
                    "openwebui.sync.ragflow_chat.created",
                    sync_id=sync_id,
                    repo_id=library.repo_id,
                    dataset_id=dataset_id,
                    ragflow_chat_id=chat_id,
                )
            else:
                summary.chats_reused += 1
                self.log.info(
                    "openwebui.sync.ragflow_chat.reused",
                    sync_id=sync_id,
                    repo_id=library.repo_id,
                    dataset_id=dataset_id,
                    ragflow_chat_id=chat_id,
                )

        inputs = DatasetArtifactInputs(
            namespace=self.settings.openwebui_function_namespace,
            repo_id=library.repo_id,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            ragflow_chat_id=chat_id,
            proxy_base_url=self.settings.openwebui_proxy_base_url_for_functions,
            proxy_verify_ssl=self.settings.openwebui_proxy_verify_ssl,
            proxy_ca_bundle=self.settings.openwebui_proxy_ca_bundle,
            language=self.settings.connector_language or "de",
        )
        tool_spec = build_tool_spec(inputs)
        pipe_spec = build_pipe_spec(inputs)
        self._cleanup_replaced_artifacts(
            mode=mode,
            capabilities=capabilities,
            summary=summary,
            sync_id=sync_id,
            dataset_id=dataset_id,
            previous_tool_id=previous_tool_id,
            next_tool_id=tool_spec.artifact_id if self.settings.openwebui_create_tools else None,
            previous_pipe_id=previous_pipe_id,
            next_pipe_id=pipe_spec.artifact_id if self.settings.openwebui_create_pipes else None,
            previous_chat_id=previous_chat_id,
            next_chat_id=chat_id,
        )
        mapping_id = mapping.id
        with self.session_factory() as session:
            stored_mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if stored_mapping is None:
                raise RuntimeError("OpenWebUI mapping vanished during sync")
            stored_mapping.ragflow_chat_id = chat_id
            stored_mapping.openwebui_tool_id = (
                tool_spec.artifact_id if self.settings.openwebui_create_tools else None
            )
            stored_mapping.openwebui_pipe_id = (
                pipe_spec.artifact_id if self.settings.openwebui_create_pipes else None
            )
            stored_mapping.openwebui_model_name = build_model_name(
                self.settings.openwebui_function_namespace,
                dataset_name,
                dataset_id,
            )
            stored_mapping.artifact_version = ARTIFACT_VERSION
            stored_mapping.tool_definition_hash = tool_spec.definition_hash
            stored_mapping.pipe_definition_hash = pipe_spec.definition_hash
            stored_mapping.openwebui_tool_payload = dict(redact_mapping(tool_spec.payload))
            stored_mapping.openwebui_pipe_payload = dict(redact_mapping(pipe_spec.payload))
            stored_mapping.capabilities_snapshot = capabilities.as_dict()
            stored_mapping.last_sync_attempt_at = _utcnow()
            session.commit()

        artifact_actions: list[str] = []
        if self.settings.openwebui_create_tools:
            action = self._sync_tool(
                mapping_id,
                tool_spec,
                mode,
                capabilities,
                previous_tool_hash,
            )
            artifact_actions.append(action)
            _count_action(summary, "tool", action)
            self._record_change(
                sync_id,
                "openwebui_tool",
                action,
                tool_spec.artifact_id,
                dataset_id,
            )
        if self.settings.openwebui_create_pipes:
            action = self._sync_pipe(
                mapping_id,
                pipe_spec,
                mode,
                capabilities,
                previous_pipe_hash,
            )
            artifact_actions.append(action)
            _count_action(summary, "pipe", action)
            self._record_change(
                sync_id,
                "openwebui_pipe",
                action,
                pipe_spec.artifact_id,
                dataset_id,
            )

        with self.session_factory() as session:
            stored_mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if stored_mapping:
                if "manual_required" in artifact_actions:
                    stored_mapping.sync_status = "manual_required"
                elif mode == "dry-run":
                    stored_mapping.sync_status = "planned"
                    stored_mapping.last_error = None
                elif (
                    not self.settings.openwebui_create_tools
                    or not self.settings.openwebui_create_pipes
                ):
                    stored_mapping.sync_status = "partial"
                    stored_mapping.last_error = None
                else:
                    stored_mapping.sync_status = "synced"
                    stored_mapping.last_error = None
                if mode != "dry-run" and stored_mapping.sync_status in {"partial", "synced"}:
                    stored_mapping.last_successful_sync_at = _utcnow()
                session.commit()

    def _discover_libraries(self) -> list[Library]:
        allowlist = set(self.settings.openwebui_dataset_allowlist)
        with self.session_factory() as session:
            rows = session.scalars(
                select(Library)
                .where(Library.status == "active")
                .where(Library.ragflow_dataset_id.is_not(None))
                .order_by(Library.name.asc())
            ).all()
            result = []
            for row in rows:
                if (
                    allowlist
                    and row.repo_id not in allowlist
                    and row.ragflow_dataset_id not in allowlist
                ):
                    continue
                session.expunge(row)
                result.append(row)
            return result

    def _ensure_mapping(
        self,
        library: Library,
        capabilities: OpenWebUICapabilities,
    ) -> OpenWebUIDatasetMapping:
        now = _utcnow()
        with self.session_factory() as session:
            mapping = session.scalar(
                select(OpenWebUIDatasetMapping).where(
                    OpenWebUIDatasetMapping.repo_id == library.repo_id
                )
            )
            if mapping is None:
                mapping = OpenWebUIDatasetMapping(
                    repo_id=library.repo_id,
                    ragflow_dataset_id=str(library.ragflow_dataset_id),
                    ragflow_dataset_name=str(library.ragflow_dataset_name or library.name),
                    sync_status="pending",
                    last_sync_attempt_at=now,
                    capabilities_snapshot=capabilities.as_dict(),
                )
                session.add(mapping)
            else:
                mapping.ragflow_dataset_id = str(library.ragflow_dataset_id)
                mapping.ragflow_dataset_name = str(library.ragflow_dataset_name or library.name)
                mapping.last_sync_attempt_at = now
                mapping.capabilities_snapshot = capabilities.as_dict()
            session.commit()
            session.refresh(mapping)
            session.expunge(mapping)
            return mapping

    def _ensure_chat(
        self,
        mapping: OpenWebUIDatasetMapping,
        chat_name: str,
        dataset_id: str,
        mode: str,
    ) -> tuple[str | None, bool]:
        if mapping.ragflow_chat_id:
            chat = self.ragflow_client.get_chat(mapping.ragflow_chat_id)
            if chat and _chat_has_dataset(chat, dataset_id):
                return str(chat.get("id") or mapping.ragflow_chat_id), False
        existing = self.ragflow_client.list_chats(name=chat_name)
        for chat in existing:
            if _chat_has_dataset(chat, dataset_id):
                return str(chat.get("id")), False
        if mode == "dry-run":
            return f"dry-run-{sha256_text(chat_name)[:12]}", True
        if existing and mode == "repair":
            chat_id = str(existing[0].get("id"))
            updated = self.ragflow_client.update_chat(
                chat_id,
                {"name": chat_name, "dataset_ids": [dataset_id]},
            )
            return str(updated.get("id") or chat_id), False
        created = self.ragflow_client.create_chat({"name": chat_name, "dataset_ids": [dataset_id]})
        return str(created.get("id")), True

    def _sync_tool(
        self,
        mapping_id: int,
        spec: OpenWebUIArtifactSpec,
        mode: str,
        capabilities: OpenWebUICapabilities,
        previous_hash: str | None,
    ) -> str:
        if mode == "dry-run":
            return "planned"
        if not capabilities.tools_write or self.openwebui_client is None:
            self._set_mapping_status(
                mapping_id,
                "manual_required",
                "OpenWebUI tool API is not writable",
            )
            return "manual_required"
        valves = _valves_with_secret(spec.valves, self.settings.openwebui_proxy_shared_secret)
        existing = self.openwebui_client.get_tool(spec.artifact_id)
        if existing is None:
            self.openwebui_client.create_tool(spec.payload)
            self.openwebui_client.update_tool_valves(spec.artifact_id, valves)
            self.log.info("openwebui.sync.tool.created", openwebui_tool_id=spec.artifact_id)
            return "created"
        if not _is_connector_owned(existing):
            self._set_mapping_status(
                mapping_id,
                "manual_required",
                "OpenWebUI tool ID exists but is not connector-owned",
            )
            return "manual_required"
        if previous_hash == spec.definition_hash and _remote_content_matches(existing, spec):
            self.log.info("openwebui.sync.tool.reused", openwebui_tool_id=spec.artifact_id)
            return "reused"
        self.openwebui_client.update_tool(spec.artifact_id, spec.payload)
        self.openwebui_client.update_tool_valves(spec.artifact_id, valves)
        self.log.info("openwebui.sync.tool.updated", openwebui_tool_id=spec.artifact_id)
        return "updated"

    def _sync_pipe(
        self,
        mapping_id: int,
        spec: OpenWebUIArtifactSpec,
        mode: str,
        capabilities: OpenWebUICapabilities,
        previous_hash: str | None,
    ) -> str:
        if mode == "dry-run":
            return "planned"
        if not capabilities.functions_write or self.openwebui_client is None:
            self._set_mapping_status(
                mapping_id,
                "manual_required",
                "OpenWebUI function API is not writable",
            )
            return "manual_required"
        valves = _valves_with_secret(spec.valves, self.settings.openwebui_proxy_shared_secret)
        existing = self.openwebui_client.get_function(spec.artifact_id)
        if existing is None:
            self.openwebui_client.create_function(spec.payload)
            self.openwebui_client.update_function_valves(spec.artifact_id, valves)
            self.openwebui_client.ensure_function_active(spec.artifact_id)
            self.log.info("openwebui.sync.pipe.created", openwebui_pipe_id=spec.artifact_id)
            return "created"
        if not _is_connector_owned(existing):
            self._set_mapping_status(
                mapping_id,
                "manual_required",
                "OpenWebUI function ID exists but is not connector-owned",
            )
            return "manual_required"
        if previous_hash == spec.definition_hash and _remote_content_matches(existing, spec):
            self.openwebui_client.ensure_function_active(spec.artifact_id)
            self.log.info("openwebui.sync.pipe.reused", openwebui_pipe_id=spec.artifact_id)
            return "reused"
        self.openwebui_client.update_function(spec.artifact_id, spec.payload)
        self.openwebui_client.update_function_valves(spec.artifact_id, valves)
        self.openwebui_client.ensure_function_active(spec.artifact_id)
        self.log.info("openwebui.sync.pipe.updated", openwebui_pipe_id=spec.artifact_id)
        return "updated"

    def _probe_capabilities(self, mode: str) -> OpenWebUICapabilities:
        if mode == "dry-run" and self.openwebui_client is None:
            return OpenWebUICapabilities(
                reachable=False,
                error="not probed in dry-run without API key",
            )
        if self.openwebui_client is None:
            return OpenWebUICapabilities(
                reachable=False,
                error="OpenWebUI client is not configured",
            )
        capabilities = self.openwebui_client.probe_capabilities()
        self._write_global_state(
            status="validated",
            mode=mode,
            capabilities=capabilities,
            healthcheck=True,
        )
        self.log.info("openwebui.config.validated", **capabilities.as_dict())
        return capabilities

    def _sync_blocker(self, mode: str, capabilities: OpenWebUICapabilities) -> str | None:
        if mode == "dry-run":
            return None
        if not capabilities.reachable:
            return capabilities.error or "OpenWebUI API is not reachable"
        if self.settings.openwebui_create_tools and not capabilities.tools_write:
            return "OpenWebUI tool API is not writable"
        if self.settings.openwebui_create_pipes and not capabilities.functions_write:
            return "OpenWebUI function API is not writable"
        return None

    def _set_mapping_status(self, mapping_id: int, status: str, error: str | None = None) -> None:
        with self.session_factory() as session:
            mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if mapping:
                mapping.sync_status = status
                mapping.last_error = safe_text(error, max_length=4000)
                session.commit()

    def _mark_dataset_failed(
        self,
        library: Library,
        error: str,
        capabilities: OpenWebUICapabilities,
    ) -> None:
        with self.session_factory() as session:
            mapping = session.scalar(
                select(OpenWebUIDatasetMapping).where(
                    OpenWebUIDatasetMapping.repo_id == library.repo_id
                )
            )
            if mapping is None and library.ragflow_dataset_id:
                mapping = OpenWebUIDatasetMapping(
                    repo_id=library.repo_id,
                    ragflow_dataset_id=str(library.ragflow_dataset_id),
                    ragflow_dataset_name=str(library.ragflow_dataset_name or library.name),
                )
                session.add(mapping)
            if mapping:
                mapping.sync_status = "failed"
                mapping.last_error = safe_text(error, max_length=4000)
                mapping.last_sync_attempt_at = _utcnow()
                mapping.capabilities_snapshot = capabilities.as_dict()
            session.commit()

    def _write_global_state(
        self,
        *,
        status: str,
        mode: str,
        summary: OpenWebUISyncSummary | None = None,
        capabilities: OpenWebUICapabilities | None = None,
        sync_started: bool = False,
        sync_finished: bool = False,
        healthcheck: bool = False,
        error: str | None = None,
    ) -> None:
        now = _utcnow()
        with self.session_factory() as session:
            state = session.get(OpenWebUISyncState, "default")
            if state is None:
                state = OpenWebUISyncState(id="default")
                session.add(state)
            state.enabled = self.settings.openwebui_integration_enabled
            state.mode = mode
            state.status = status
            state.base_url = self.settings.openwebui_base_url
            if healthcheck:
                state.last_healthcheck_at = now
            if sync_started:
                state.last_sync_started_at = now
            if sync_finished:
                state.last_sync_finished_at = now
                if status == "succeeded":
                    state.last_successful_sync_at = now
                    state.last_error = None
            if summary is not None:
                state.summary = summary.__dict__
                if summary.dry_run:
                    state.dry_run_plan = summary.__dict__
            if capabilities is not None:
                state.capabilities_snapshot = capabilities.as_dict()
                if capabilities.error:
                    state.last_error = safe_text(capabilities.error, max_length=4000)
            if error:
                state.last_error = safe_text(error, max_length=4000)
            session.commit()

    def _create_dashboard_run(self, sync_id: str, mode: str) -> None:
        if self.dashboard_store is None:
            return
        self.dashboard_store.create_sync_run(
            sync_id=sync_id,
            source="ragflow:datasets",
            target="openwebui:functions-tools",
            summary=f"OpenWebUI-Sync ({mode})",
            details={"mode": mode, "dry_run": mode == "dry-run"},
        )

    def _finish_dashboard_run(
        self,
        sync_id: str,
        status: str,
        summary: OpenWebUISyncSummary,
        duration_ms: int,
    ) -> None:
        if self.dashboard_store is None:
            return
        self.dashboard_store.finish_sync_run(
            sync_id=sync_id,
            status=status,
            objects_checked=summary.datasets_seen,
            objects_created=summary.chats_created + summary.tools_created + summary.pipes_created,
            objects_updated=summary.tools_updated + summary.pipes_updated,
            objects_deleted=summary.chats_deleted + summary.tools_deleted + summary.pipes_deleted,
            objects_skipped=summary.tools_reused + summary.pipes_reused + summary.manual_required,
            errors_count=summary.failed,
            warnings_count=summary.manual_required,
            summary=f"OpenWebUI-Sync in {duration_ms} ms",
            details=summary.__dict__,
        )

    def _sync_deleted_library_mappings(
        self,
        *,
        mode: str,
        capabilities: OpenWebUICapabilities,
        summary: OpenWebUISyncSummary,
        sync_id: str,
    ) -> None:
        with self.session_factory() as session:
            rows = session.scalars(
                select(OpenWebUIDatasetMapping)
                .join(Library, OpenWebUIDatasetMapping.repo_id == Library.repo_id)
                .where(Library.status == "deleted")
            ).all()
            mappings = []
            for row in rows:
                session.expunge(row)
                mappings.append(row)

        for mapping in mappings:
            summary.datasets_seen += 1
            try:
                self._cleanup_deleted_mapping(mapping, mode, capabilities, summary, sync_id)
            except Exception as exc:
                summary.failed += 1
                self._set_mapping_status(mapping.id, "failed", str(exc))
                self.log.warning(
                    "openwebui.sync.dataset.failed",
                    sync_id=sync_id,
                    repo_id=mapping.repo_id,
                    dataset_id=mapping.ragflow_dataset_id,
                    error=str(exc),
                )

    def _cleanup_deleted_mapping(
        self,
        mapping: OpenWebUIDatasetMapping,
        mode: str,
        capabilities: OpenWebUICapabilities,
        summary: OpenWebUISyncSummary,
        sync_id: str,
    ) -> None:
        if mode == "dry-run":
            self._set_mapping_status(mapping.id, "delete_planned")
            return

        manual_errors: list[str] = []
        if mapping.openwebui_tool_id:
            action = self._delete_openwebui_tool(mapping, capabilities)
            if action == "deleted":
                summary.tools_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_tool",
                    "deleted",
                    mapping.openwebui_tool_id,
                    mapping.ragflow_dataset_id,
                )
            elif action == "manual_required":
                manual_errors.append("OpenWebUI tool exists but is not connector-owned")

        if mapping.openwebui_pipe_id:
            action = self._delete_openwebui_pipe(mapping, capabilities)
            if action == "deleted":
                summary.pipes_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_pipe",
                    "deleted",
                    mapping.openwebui_pipe_id,
                    mapping.ragflow_dataset_id,
                )
            elif action == "manual_required":
                manual_errors.append("OpenWebUI pipe exists but is not connector-owned")

        if mapping.ragflow_chat_id:
            self.ragflow_client.delete_chats([mapping.ragflow_chat_id])
            summary.chats_deleted += 1
            self.log.info(
                "openwebui.sync.ragflow_chat.deleted",
                sync_id=sync_id,
                repo_id=mapping.repo_id,
                dataset_id=mapping.ragflow_dataset_id,
                ragflow_chat_id=mapping.ragflow_chat_id,
            )
            self._record_change(
                sync_id,
                "ragflow_chat",
                "deleted",
                mapping.ragflow_chat_id,
                mapping.ragflow_dataset_id,
            )

        if manual_errors:
            summary.manual_required += 1
            self._set_mapping_status(mapping.id, "manual_required", "; ".join(manual_errors))
            return

        with self.session_factory() as session:
            stored_mapping = session.get(OpenWebUIDatasetMapping, mapping.id)
            if stored_mapping:
                stored_mapping.sync_status = "deleted"
                stored_mapping.last_error = None
                stored_mapping.last_sync_attempt_at = _utcnow()
                stored_mapping.last_successful_sync_at = _utcnow()
                session.commit()

    def _cleanup_replaced_artifacts(
        self,
        *,
        mode: str,
        capabilities: OpenWebUICapabilities,
        summary: OpenWebUISyncSummary,
        sync_id: str,
        dataset_id: str,
        previous_tool_id: str | None,
        next_tool_id: str | None,
        previous_pipe_id: str | None,
        next_pipe_id: str | None,
        previous_chat_id: str | None,
        next_chat_id: str | None,
    ) -> None:
        if mode == "dry-run":
            return
        if previous_tool_id and next_tool_id and previous_tool_id != next_tool_id:
            deleted = self._delete_owned_tool_by_id(previous_tool_id, capabilities)
            if deleted:
                summary.tools_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_tool",
                    "deleted",
                    previous_tool_id,
                    dataset_id,
                )
        if previous_pipe_id and next_pipe_id and previous_pipe_id != next_pipe_id:
            deleted = self._delete_owned_pipe_by_id(previous_pipe_id, capabilities)
            if deleted:
                summary.pipes_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_pipe",
                    "deleted",
                    previous_pipe_id,
                    dataset_id,
                )
        if previous_chat_id and next_chat_id and previous_chat_id != next_chat_id:
            self.ragflow_client.delete_chats([previous_chat_id])
            summary.chats_deleted += 1
            self.log.info(
                "openwebui.sync.ragflow_chat.deleted",
                sync_id=sync_id,
                dataset_id=dataset_id,
                ragflow_chat_id=previous_chat_id,
            )
            self._record_change(sync_id, "ragflow_chat", "deleted", previous_chat_id, dataset_id)

    def _delete_openwebui_tool(
        self,
        mapping: OpenWebUIDatasetMapping,
        capabilities: OpenWebUICapabilities,
    ) -> str:
        if not capabilities.tools_write or self.openwebui_client is None:
            return "manual_required"
        tool_id = str(mapping.openwebui_tool_id)
        existing = self.openwebui_client.get_tool(tool_id)
        if existing is None:
            return "missing"
        if not _is_connector_owned(existing):
            return "manual_required"
        self.openwebui_client.delete_tool(tool_id)
        self.log.info("openwebui.sync.tool.deleted", openwebui_tool_id=tool_id)
        return "deleted"

    def _delete_owned_tool_by_id(
        self,
        tool_id: str,
        capabilities: OpenWebUICapabilities,
    ) -> bool:
        if not capabilities.tools_write or self.openwebui_client is None:
            return False
        existing = self.openwebui_client.get_tool(tool_id)
        if existing is None:
            return False
        if not _is_connector_owned(existing):
            self.log.warning(
                "openwebui.sync.tool_delete_skipped_foreign",
                openwebui_tool_id=tool_id,
            )
            return False
        self.openwebui_client.delete_tool(tool_id)
        self.log.info("openwebui.sync.tool.deleted", openwebui_tool_id=tool_id)
        return True

    def _delete_openwebui_pipe(
        self,
        mapping: OpenWebUIDatasetMapping,
        capabilities: OpenWebUICapabilities,
    ) -> str:
        if not capabilities.functions_write or self.openwebui_client is None:
            return "manual_required"
        pipe_id = str(mapping.openwebui_pipe_id)
        existing = self.openwebui_client.get_function(pipe_id)
        if existing is None:
            return "missing"
        if not _is_connector_owned(existing):
            return "manual_required"
        self.openwebui_client.delete_function(pipe_id)
        self.log.info("openwebui.sync.pipe.deleted", openwebui_pipe_id=pipe_id)
        return "deleted"

    def _delete_owned_pipe_by_id(
        self,
        pipe_id: str,
        capabilities: OpenWebUICapabilities,
    ) -> bool:
        if not capabilities.functions_write or self.openwebui_client is None:
            return False
        existing = self.openwebui_client.get_function(pipe_id)
        if existing is None:
            return False
        if not _is_connector_owned(existing):
            self.log.warning(
                "openwebui.sync.pipe_delete_skipped_foreign",
                openwebui_pipe_id=pipe_id,
            )
            return False
        self.openwebui_client.delete_function(pipe_id)
        self.log.info("openwebui.sync.pipe.deleted", openwebui_pipe_id=pipe_id)
        return True

    def _record_change(
        self,
        sync_id: str,
        change_type: str,
        action: str,
        artifact_id: str,
        dataset_id: str,
    ) -> None:
        if self.dashboard_store is None:
            return
        self.dashboard_store.record_change(
            sync_id=sync_id,
            action=f"openwebui.{change_type}.{action}",
            change_type=change_type,
            status="synced" if action in {"created", "updated", "reused"} else action,
            object_name=artifact_id,
            source_path=f"ragflow:{dataset_id}",
            target_path=f"openwebui:{artifact_id}",
            source_system="ragflow",
            target_system="openwebui",
            details={"action": action, "artifact_id": artifact_id, "dataset_id": dataset_id},
        )


def _chat_name(namespace: str, dataset_name: str, dataset_id: str) -> str:
    slug = slugify(dataset_name, fallback="dataset").replace("-", "_")
    return f"owui__{namespace}__{slug}__{sha256_text(dataset_id)[:8]}"


def _chat_has_dataset(chat: dict[str, Any], dataset_id: str) -> bool:
    dataset_ids = chat.get("dataset_ids") or chat.get("datasets") or []
    if isinstance(dataset_ids, list):
        for item in dataset_ids:
            if isinstance(item, dict) and str(item.get("id")) == dataset_id:
                return True
            if str(item) == dataset_id:
                return True
    return False


def _valves_with_secret(valves: dict[str, object], secret: str | None) -> dict[str, object]:
    data = dict(valves)
    if "CONNECTOR_PROXY_SHARED_SECRET" in data:
        data["CONNECTOR_PROXY_SHARED_SECRET"] = secret or ""
    return data


def _is_connector_owned(artifact: dict[str, Any]) -> bool:
    meta = artifact.get("meta")
    manifest = meta.get("manifest") if isinstance(meta, dict) else None
    if isinstance(manifest, dict) and manifest.get("owner") == "seafile-ragflow-connector":
        return True
    content = str(artifact.get("content") or "")
    return (
        "owner: seafile-ragflow-connector" in content
        or "author: Seafile RAGFlow Connector" in content
    )


def _remote_content_matches(artifact: dict[str, Any], spec: OpenWebUIArtifactSpec) -> bool:
    return str(artifact.get("content") or "") == spec.content


def _count_action(summary: OpenWebUISyncSummary, kind: str, action: str) -> None:
    if action == "created":
        setattr(summary, f"{kind}s_created", getattr(summary, f"{kind}s_created") + 1)
    elif action == "updated":
        setattr(summary, f"{kind}s_updated", getattr(summary, f"{kind}s_updated") + 1)
    elif action == "reused":
        setattr(summary, f"{kind}s_reused", getattr(summary, f"{kind}s_reused") + 1)
    elif action == "manual_required":
        summary.manual_required += 1


def _utcnow() -> datetime:
    return datetime.now(UTC)
