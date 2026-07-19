from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from seafile_ragflow_connector.app.metrics import (
    openwebui_artifacts_created_total,
    openwebui_artifacts_updated_total,
    openwebui_sync_failures_total,
    openwebui_sync_runs_total,
)
from seafile_ragflow_connector.clients.http import ApiError
from seafile_ragflow_connector.clients.openwebui import OpenWebUICapabilities, OpenWebUIClient
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.dashboard.store import DashboardEventStore, new_sync_id, safe_text
from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.domain.ragflow_defaults import build_chat_payload
from seafile_ragflow_connector.domain.ragflow_search_settings import (
    ResolvedSearchTemplate,
    apply_retrieval_settings_to_chat_payload,
    config_from_settings,
    resolve_search_template,
)
from seafile_ragflow_connector.jobs.context import (
    job_cancellation_requested,
    job_pause_requested,
)
from seafile_ragflow_connector.openwebui.artifacts import (
    ARTIFACT_VERSION,
    DatasetArtifactInputs,
    OpenWebUIArtifactSpec,
    build_model_name,
    build_pipe_spec,
    build_tool_spec,
)
from seafile_ragflow_connector.persistence.admin_control import AdminControlStore
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import (
    OpenWebUIDatasetMapping,
    OpenWebUISyncState,
)
from seafile_ragflow_connector.utils.hashing import sha256_text
from seafile_ragflow_connector.utils.redaction import redact_mapping

_PENDING_REPLACEMENT_CLEANUP_KEY = "pending_replacement_cleanup"


class OpenWebUISyncInterruptedError(RuntimeError):
    """Cooperative stop signal for safe OpenWebUI mutation checkpoints."""


class _OpenWebUILibraryControlledError(RuntimeError):
    """Stop the current library when its administrator control changes."""


@dataclass
class OpenWebUISyncSummary:
    datasets_seen: int = 0
    chats_created: int = 0
    chats_updated: int = 0
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
        admin_control_store: AdminControlStore | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.ragflow_client = ragflow_client
        self.openwebui_client = openwebui_client
        self.dashboard_store = dashboard_store
        self.admin_control_store = admin_control_store or AdminControlStore(session_factory)
        self.log = structlog.get_logger(__name__)
        self._search_template_cache: ResolvedSearchTemplate | None = None

    def sync_once(
        self,
        *,
        mode_override: Literal["disabled", "dry-run", "sync", "repair"] | None = None,
        repo_ids: set[str] | None = None,
    ) -> OpenWebUISyncSummary:
        self._search_template_cache = None
        mode = mode_override or self.settings.openwebui_effective_sync_mode
        summary = OpenWebUISyncSummary(dry_run=mode == "dry-run")
        if mode == "disabled":
            self._write_global_state(status="disabled", mode=mode, summary=summary)
            self.log.info("openwebui.integration.disabled")
            return summary
        if repo_ids is not None and not repo_ids:
            self.log.info("openwebui.sync.empty_scope")
            return summary

        libraries = self._discover_libraries(repo_ids=repo_ids)

        openwebui_sync_runs_total.inc()
        sync_id = new_sync_id("openwebui")
        started = time.perf_counter()
        self._write_global_state(status="running", mode=mode, summary=summary, sync_started=True)
        self._create_dashboard_run(sync_id, mode)
        self.log.info("openwebui.sync.started", sync_id=sync_id, mode=mode, dry_run=summary.dry_run)
        capabilities = self._probe_capabilities(mode)
        blocker = self._sync_blocker(mode, capabilities)
        if blocker:
            summary.failed += 1
            openwebui_sync_failures_total.inc()
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
        interrupted_status: str | None = None
        try:
            self._raise_if_job_interrupted()
            self._ensure_template_chat(mode=mode, sync_id=sync_id)
            if repo_ids is None:
                self._sync_deleted_library_mappings(
                    mode=mode,
                    capabilities=capabilities,
                    summary=summary,
                    sync_id=sync_id,
                )
            for library in libraries:
                try:
                    self._raise_if_library_controlled(library.repo_id)
                    summary.datasets_seen += 1
                    self.log.info(
                        "openwebui.sync.dataset.discovered",
                        sync_id=sync_id,
                        repo_id=library.repo_id,
                        dataset_id=library.ragflow_dataset_id,
                        dataset_name=library.ragflow_dataset_name,
                    )
                    self._sync_library(
                        library,
                        mode=mode,
                        capabilities=capabilities,
                        summary=summary,
                        sync_id=sync_id,
                    )
                except _OpenWebUILibraryControlledError:
                    continue
                except OpenWebUISyncInterruptedError:
                    raise
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
        except OpenWebUISyncInterruptedError:
            interrupted_status = "paused" if job_pause_requested() else "cancelled"
            raise
        finally:
            if summary.failed:
                openwebui_sync_failures_total.inc()
            openwebui_artifacts_created_total.labels("tool").inc(summary.tools_created)
            openwebui_artifacts_created_total.labels("pipe").inc(summary.pipes_created)
            openwebui_artifacts_updated_total.labels("tool").inc(summary.tools_updated)
            openwebui_artifacts_updated_total.labels("pipe").inc(summary.pipes_updated)
            if interrupted_status is not None:
                status = interrupted_status
            elif summary.failed:
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

    @staticmethod
    def _raise_if_job_interrupted() -> None:
        if job_cancellation_requested():
            raise OpenWebUISyncInterruptedError("OpenWebUI sync interrupted")

    def _raise_if_library_controlled(self, repo_id: str) -> None:
        self._raise_if_job_interrupted()
        control = self.admin_control_store.library(repo_id)
        if control.runnable:
            return
        self.log.info(
            "openwebui.sync.library_controlled",
            repo_id=repo_id,
            state=control.state,
        )
        raise _OpenWebUILibraryControlledError(
            f"OpenWebUI sync skipped controlled library {repo_id} ({control.state})"
        )

    def _sync_library(
        self,
        library: Library,
        *,
        mode: str,
        capabilities: OpenWebUICapabilities,
        summary: OpenWebUISyncSummary,
        sync_id: str,
    ) -> None:
        self._raise_if_library_controlled(library.repo_id)
        dataset_id = str(library.ragflow_dataset_id)
        dataset_name = str(library.ragflow_dataset_name or library.name)
        mapping = self._ensure_mapping(library, capabilities)
        previous_tool_hash = mapping.tool_definition_hash
        previous_pipe_hash = mapping.pipe_definition_hash
        previous_tool_id = mapping.openwebui_tool_id
        previous_pipe_id = mapping.openwebui_pipe_id
        previous_chat_id = mapping.ragflow_chat_id
        chat_name = _chat_name(self.settings.openwebui_function_namespace, dataset_name, dataset_id)
        self._raise_if_library_controlled(library.repo_id)
        chat_id, chat_action = self._ensure_chat(
            mapping,
            chat_name,
            dataset_id,
            mode,
            repo_id=library.repo_id,
        )
        if chat_id:
            if chat_action == "created":
                summary.chats_created += 1
                self.log.info(
                    "openwebui.sync.ragflow_chat.created",
                    sync_id=sync_id,
                    repo_id=library.repo_id,
                    dataset_id=dataset_id,
                    ragflow_chat_id=chat_id,
                )
            elif chat_action == "updated":
                summary.chats_updated += 1
                self.log.info(
                    "openwebui.sync.ragflow_chat.updated",
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
            answer_synthesis_enabled=self.settings.openwebui_pipe_answer_synthesis_enabled,
            answer_llm_base_url=self.settings.openwebui_pipe_answer_llm_base_url,
            answer_llm_model=self.settings.openwebui_pipe_answer_llm_model,
            language=self.settings.connector_language or "de",
        )
        tool_spec = build_tool_spec(inputs)
        pipe_spec = build_pipe_spec(inputs)
        mapping_id = mapping.id
        artifact_actions: list[str] = []
        if self.settings.openwebui_create_tools:
            self._raise_if_library_controlled(library.repo_id)
            action = self._sync_tool(
                mapping_id,
                tool_spec,
                mode,
                capabilities,
                previous_tool_hash
                if previous_tool_id == tool_spec.artifact_id
                else None,
                repo_id=library.repo_id,
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
            self._raise_if_library_controlled(library.repo_id)
            action = self._sync_pipe(
                mapping_id,
                pipe_spec,
                mode,
                capabilities,
                previous_pipe_hash
                if previous_pipe_id == pipe_spec.artifact_id
                else None,
                repo_id=library.repo_id,
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

        if "manual_required" in artifact_actions:
            return

        if mode == "dry-run":
            next_status = "planned"
        elif not self.settings.openwebui_create_tools or not self.settings.openwebui_create_pipes:
            next_status = "partial"
        else:
            next_status = "synced"

        next_tool_id = tool_spec.artifact_id if self.settings.openwebui_create_tools else None
        next_pipe_id = pipe_spec.artifact_id if self.settings.openwebui_create_pipes else None
        pending_cleanup = _pending_replacement_cleanup(mapping.capabilities_snapshot)
        if mode != "dry-run":
            pending_cleanup = _replacement_cleanup_candidates(
                pending_cleanup,
                previous_tool_id=previous_tool_id,
                next_tool_id=next_tool_id,
                previous_pipe_id=previous_pipe_id,
                next_pipe_id=next_pipe_id,
                previous_chat_id=previous_chat_id,
                next_chat_id=chat_id,
            )
        with self.session_factory() as session:
            stored_mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if stored_mapping is None:
                raise RuntimeError("OpenWebUI mapping vanished during sync")
            stored_mapping.ragflow_chat_id = chat_id
            stored_mapping.openwebui_tool_id = next_tool_id
            stored_mapping.openwebui_pipe_id = next_pipe_id
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
            stored_mapping.capabilities_snapshot = _capabilities_with_pending_cleanup(
                capabilities.as_dict(),
                pending_cleanup,
            )
            stored_mapping.last_sync_attempt_at = _utcnow()
            stored_mapping.sync_status = next_status
            stored_mapping.last_error = None
            if mode != "dry-run" and next_status in {"partial", "synced"}:
                stored_mapping.last_successful_sync_at = _utcnow()
            session.commit()

        remaining_cleanup = self._cleanup_replaced_artifacts(
            mode=mode,
            capabilities=capabilities,
            summary=summary,
            sync_id=sync_id,
            dataset_id=dataset_id,
            previous_tool_id=previous_tool_id,
            next_tool_id=next_tool_id,
            previous_pipe_id=previous_pipe_id,
            next_pipe_id=next_pipe_id,
            previous_chat_id=previous_chat_id,
            next_chat_id=chat_id,
            pending_cleanup=pending_cleanup,
            repo_id=library.repo_id,
        )
        with self.session_factory() as session:
            stored_mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if stored_mapping is not None:
                stored_mapping.capabilities_snapshot = _capabilities_with_pending_cleanup(
                    capabilities.as_dict(),
                    remaining_cleanup,
                )
                session.commit()

    def _discover_libraries(self, *, repo_ids: set[str] | None = None) -> list[Library]:
        allowlist = set(self.settings.openwebui_dataset_allowlist)
        requested = None if repo_ids is None else set(repo_ids)
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
                    requested is not None
                    and row.repo_id not in requested
                    and row.ragflow_dataset_id not in requested
                ):
                    continue
                session.expunge(row)
                result.append(row)
        controls = self.admin_control_store.libraries(
            [library.repo_id for library in result]
        )
        blocked = [
            library
            for library in result
            if not controls[library.repo_id].runnable
        ]
        if requested is not None and blocked:
            blocked_states = ", ".join(
                f"{library.repo_id} ({controls[library.repo_id].state})"
                for library in blocked
            )
            raise ValueError(
                "OpenWebUI sync is not allowed for controlled libraries: "
                f"{blocked_states}"
            )
        return [
            library
            for library in result
            if controls[library.repo_id].runnable
            and (
                not allowlist
                or library.repo_id in allowlist
                or library.ragflow_dataset_id in allowlist
            )
        ]

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
                capabilities_snapshot = capabilities.as_dict()
                mapping = OpenWebUIDatasetMapping(
                    repo_id=library.repo_id,
                    ragflow_dataset_id=str(library.ragflow_dataset_id),
                    ragflow_dataset_name=str(library.ragflow_dataset_name or library.name),
                    sync_status="pending",
                    last_sync_attempt_at=now,
                    capabilities_snapshot=capabilities_snapshot,
                )
                session.add(mapping)
            else:
                capabilities_snapshot = _capabilities_with_pending_cleanup(
                    capabilities.as_dict(),
                    _pending_replacement_cleanup(mapping.capabilities_snapshot),
                )
                mapping.ragflow_dataset_id = str(library.ragflow_dataset_id)
                mapping.ragflow_dataset_name = str(library.ragflow_dataset_name or library.name)
                mapping.last_sync_attempt_at = now
                mapping.capabilities_snapshot = capabilities_snapshot
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
        *,
        repo_id: str,
    ) -> tuple[str | None, str]:
        payload = self._chat_payload_with_search_template(
            build_chat_payload(chat_name, dataset_id=dataset_id)
        )
        if mapping.ragflow_chat_id:
            chat = self.ragflow_client.get_chat(mapping.ragflow_chat_id)
            if chat and _chat_has_dataset(chat, dataset_id):
                chat_id = str(chat.get("id") or mapping.ragflow_chat_id)
                if mode != "dry-run" and _chat_needs_update(chat, payload):
                    self._raise_if_library_controlled(repo_id)
                    updated = self.ragflow_client.update_chat(chat_id, payload)
                    return str(updated.get("id") or chat_id), "updated"
                return chat_id, "reused"
        existing = self.ragflow_client.list_chats(name=chat_name)
        for chat in existing:
            if _chat_has_dataset(chat, dataset_id):
                chat_id = str(chat.get("id"))
                if mode != "dry-run" and _chat_needs_update(chat, payload):
                    self._raise_if_library_controlled(repo_id)
                    updated = self.ragflow_client.update_chat(chat_id, payload)
                    return str(updated.get("id") or chat_id), "updated"
                return chat_id, "reused"
        if mode == "dry-run":
            return f"dry-run-{sha256_text(chat_name)[:12]}", "created"
        if existing and mode == "repair":
            chat_id = str(existing[0].get("id"))
            self._raise_if_library_controlled(repo_id)
            updated = self.ragflow_client.update_chat(chat_id, payload)
            return str(updated.get("id") or chat_id), "updated"
        try:
            self._raise_if_library_controlled(repo_id)
            created = self.ragflow_client.create_chat(payload)
        except ApiError as exc:
            if not _is_dataset_without_parsed_files(exc):
                raise
            self.log.info(
                "openwebui.sync.ragflow_chat.deferred",
                dataset_id=dataset_id,
                ragflow_chat_name=chat_name,
                reason="dataset_without_parsed_files",
            )
            return None, "deferred"
        return str(created.get("id")), "created"

    def _ensure_template_chat(self, *, mode: str, sync_id: str) -> None:
        chat_name = self.settings.ragflow_template_chat_name
        payload = self._chat_payload_with_search_template(build_chat_payload(chat_name))
        existing = self.ragflow_client.list_chats(name=chat_name)
        if len(existing) > 1:
            self.log.warning(
                "openwebui.sync.template_chat_not_unique",
                sync_id=sync_id,
                ragflow_chat_name=chat_name,
                count=len(existing),
            )
            return
        if existing:
            chat = existing[0]
            chat_id = str(chat.get("id") or "")
            if mode != "dry-run" and chat_id and _chat_needs_update(chat, payload):
                self._raise_if_job_interrupted()
                self.ragflow_client.update_chat(chat_id, payload)
                self.log.info(
                    "openwebui.sync.template_chat.updated",
                    sync_id=sync_id,
                    ragflow_chat_id=chat_id,
                    ragflow_chat_name=chat_name,
                )
            return
        if mode == "dry-run":
            return
        self._raise_if_job_interrupted()
        created = self.ragflow_client.create_chat(payload)
        self.log.info(
            "openwebui.sync.template_chat.created",
            sync_id=sync_id,
            ragflow_chat_id=created.get("id"),
            ragflow_chat_name=chat_name,
        )

    def _chat_payload_with_search_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resolved = self._resolved_search_template()
        except RuntimeError:
            config = config_from_settings(self.settings)
            if config.required:
                raise
            self.log.warning(
                "openwebui.sync.search_template_unavailable",
                ragflow_search_template_name=config.name,
            )
            return payload
        return apply_retrieval_settings_to_chat_payload(payload, resolved)

    def _resolved_search_template(self) -> ResolvedSearchTemplate:
        if self._search_template_cache is None:
            self._search_template_cache = resolve_search_template(
                self.ragflow_client,
                config_from_settings(self.settings),
            )
        return self._search_template_cache

    def _sync_tool(
        self,
        mapping_id: int,
        spec: OpenWebUIArtifactSpec,
        mode: str,
        capabilities: OpenWebUICapabilities,
        previous_hash: str | None,
        *,
        repo_id: str,
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
        valves = _valves_with_secret(
            spec.valves,
            proxy_secret=self.settings.openwebui_proxy_shared_secret,
            answer_llm_api_key=self.settings.openwebui_pipe_answer_llm_api_key,
        )
        existing = self.openwebui_client.get_tool(spec.artifact_id)
        if existing is None:
            self._raise_if_library_controlled(repo_id)
            self.openwebui_client.create_tool(spec.payload)
            self._raise_if_library_controlled(repo_id)
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
        reconciled_valves = _merge_managed_valves(existing, valves, spec.managed_valve_keys)
        remote_valves = _remote_valves(existing)
        content_matches = previous_hash == spec.definition_hash and _remote_content_matches(
            existing,
            spec,
        )
        if content_matches:
            if remote_valves != reconciled_valves:
                self._raise_if_library_controlled(repo_id)
                self.openwebui_client.update_tool_valves(spec.artifact_id, reconciled_valves)
            self.log.info("openwebui.sync.tool.reused", openwebui_tool_id=spec.artifact_id)
            return "reused"
        self._raise_if_library_controlled(repo_id)
        self.openwebui_client.update_tool(spec.artifact_id, spec.payload)
        # OpenWebUI may reset valves while replacing artifact content. Reapply the
        # reconciled values afterwards so operator-owned settings survive upgrades.
        self._raise_if_library_controlled(repo_id)
        self.openwebui_client.update_tool_valves(spec.artifact_id, reconciled_valves)
        self.log.info("openwebui.sync.tool.updated", openwebui_tool_id=spec.artifact_id)
        return "updated"

    def _sync_pipe(
        self,
        mapping_id: int,
        spec: OpenWebUIArtifactSpec,
        mode: str,
        capabilities: OpenWebUICapabilities,
        previous_hash: str | None,
        *,
        repo_id: str,
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
        valves = _valves_with_secret(
            spec.valves,
            proxy_secret=self.settings.openwebui_proxy_shared_secret,
            answer_llm_api_key=self.settings.openwebui_pipe_answer_llm_api_key,
        )
        existing = self.openwebui_client.get_function(spec.artifact_id)
        if existing is None:
            self._raise_if_library_controlled(repo_id)
            self.openwebui_client.create_function(spec.payload)
            self._raise_if_library_controlled(repo_id)
            self.openwebui_client.update_function_valves(spec.artifact_id, valves)
            self._raise_if_library_controlled(repo_id)
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
        reconciled_valves = _merge_managed_valves(existing, valves, spec.managed_valve_keys)
        remote_valves = _remote_valves(existing)
        content_matches = previous_hash == spec.definition_hash and _remote_content_matches(
            existing,
            spec,
        )
        if content_matches:
            if remote_valves != reconciled_valves:
                self._raise_if_library_controlled(repo_id)
                self.openwebui_client.update_function_valves(
                    spec.artifact_id,
                    reconciled_valves,
                )
            self._raise_if_library_controlled(repo_id)
            self.openwebui_client.ensure_function_active(spec.artifact_id)
            self.log.info("openwebui.sync.pipe.reused", openwebui_pipe_id=spec.artifact_id)
            return "reused"
        self._raise_if_library_controlled(repo_id)
        self.openwebui_client.update_function(spec.artifact_id, spec.payload)
        # See _sync_tool: content replacement must not discard operator valves.
        self._raise_if_library_controlled(repo_id)
        self.openwebui_client.update_function_valves(spec.artifact_id, reconciled_valves)
        self._raise_if_library_controlled(repo_id)
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
        if self.settings.openwebui_create_tools and not capabilities.tools_valves:
            return "OpenWebUI tool valves API is not writable"
        if self.settings.openwebui_create_pipes and not capabilities.functions_write:
            return "OpenWebUI function API is not writable"
        if self.settings.openwebui_create_pipes and not capabilities.functions_valves:
            return "OpenWebUI function valves API is not writable"
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
            objects_updated=summary.chats_updated + summary.tools_updated + summary.pipes_updated,
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
                .order_by(OpenWebUIDatasetMapping.repo_id.asc())
            ).all()
            mappings = []
            for row in rows:
                session.expunge(row)
                mappings.append(row)
        for mapping in mappings:
            try:
                self._raise_if_library_controlled(mapping.repo_id)
                summary.datasets_seen += 1
                self._cleanup_deleted_mapping(mapping, mode, capabilities, summary, sync_id)
            except _OpenWebUILibraryControlledError:
                continue
            except OpenWebUISyncInterruptedError:
                raise
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
            tool_id = mapping.openwebui_tool_id
            self._raise_if_library_controlled(mapping.repo_id)
            action = self._delete_openwebui_tool(mapping, capabilities)
            if action == "deleted":
                summary.tools_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_tool",
                    "deleted",
                    tool_id,
                    mapping.ragflow_dataset_id,
                )
            elif action == "manual_required":
                manual_errors.append("OpenWebUI tool exists but is not connector-owned")
            if action in {"deleted", "missing"}:
                self._clear_deleted_mapping_artifact(mapping.id, "openwebui_tool_id")
                mapping.openwebui_tool_id = None

        if mapping.openwebui_pipe_id:
            pipe_id = mapping.openwebui_pipe_id
            self._raise_if_library_controlled(mapping.repo_id)
            action = self._delete_openwebui_pipe(mapping, capabilities)
            if action == "deleted":
                summary.pipes_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_pipe",
                    "deleted",
                    pipe_id,
                    mapping.ragflow_dataset_id,
                )
            elif action == "manual_required":
                manual_errors.append("OpenWebUI pipe exists but is not connector-owned")
            if action in {"deleted", "missing"}:
                self._clear_deleted_mapping_artifact(mapping.id, "openwebui_pipe_id")
                mapping.openwebui_pipe_id = None

        if mapping.ragflow_chat_id:
            chat_id = mapping.ragflow_chat_id
            self._raise_if_library_controlled(mapping.repo_id)
            self.ragflow_client.delete_chats([chat_id])
            self._clear_deleted_mapping_artifact(mapping.id, "ragflow_chat_id")
            mapping.ragflow_chat_id = None
            summary.chats_deleted += 1
            self.log.info(
                "openwebui.sync.ragflow_chat.deleted",
                sync_id=sync_id,
                repo_id=mapping.repo_id,
                dataset_id=mapping.ragflow_dataset_id,
                ragflow_chat_id=chat_id,
            )
            self._record_change(
                sync_id,
                "ragflow_chat",
                "deleted",
                chat_id,
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

    def _clear_deleted_mapping_artifact(
        self,
        mapping_id: int,
        field: Literal[
            "openwebui_tool_id",
            "openwebui_pipe_id",
            "ragflow_chat_id",
        ],
    ) -> None:
        with self.session_factory() as session:
            mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if mapping is not None:
                setattr(mapping, field, None)
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
        pending_cleanup: dict[str, list[str]] | None = None,
        repo_id: str,
    ) -> dict[str, list[str]]:
        candidates = _replacement_cleanup_candidates(
            pending_cleanup or {},
            previous_tool_id=previous_tool_id,
            next_tool_id=next_tool_id,
            previous_pipe_id=previous_pipe_id,
            next_pipe_id=next_pipe_id,
            previous_chat_id=previous_chat_id,
            next_chat_id=next_chat_id,
        )
        if mode == "dry-run":
            return candidates
        remaining: dict[str, list[str]] = {"tools": [], "pipes": [], "chats": []}
        for tool_id in candidates["tools"]:
            self._raise_if_library_controlled(repo_id)
            if not capabilities.tools_write or self.openwebui_client is None:
                remaining["tools"].append(tool_id)
                continue
            try:
                deleted = self._delete_owned_tool_by_id(
                    tool_id,
                    capabilities,
                    repo_id=repo_id,
                )
            except _OpenWebUILibraryControlledError:
                raise
            except OpenWebUISyncInterruptedError:
                raise
            except (ApiError, httpx.RequestError, RuntimeError, TypeError, ValueError) as exc:
                deleted = False
                remaining["tools"].append(tool_id)
                self.log.warning(
                    "openwebui.sync.replaced_tool_cleanup_deferred",
                    openwebui_tool_id=tool_id,
                    error_class=exc.__class__.__name__,
                )
            if deleted:
                summary.tools_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_tool",
                    "deleted",
                    tool_id,
                    dataset_id,
                )
        for pipe_id in candidates["pipes"]:
            self._raise_if_library_controlled(repo_id)
            if not capabilities.functions_write or self.openwebui_client is None:
                remaining["pipes"].append(pipe_id)
                continue
            try:
                deleted = self._delete_owned_pipe_by_id(
                    pipe_id,
                    capabilities,
                    repo_id=repo_id,
                )
            except _OpenWebUILibraryControlledError:
                raise
            except OpenWebUISyncInterruptedError:
                raise
            except (ApiError, httpx.RequestError, RuntimeError, TypeError, ValueError) as exc:
                deleted = False
                remaining["pipes"].append(pipe_id)
                self.log.warning(
                    "openwebui.sync.replaced_pipe_cleanup_deferred",
                    openwebui_pipe_id=pipe_id,
                    error_class=exc.__class__.__name__,
                )
            if deleted:
                summary.pipes_deleted += 1
                self._record_change(
                    sync_id,
                    "openwebui_pipe",
                    "deleted",
                    pipe_id,
                    dataset_id,
                )
        for chat_id in candidates["chats"]:
            self._raise_if_library_controlled(repo_id)
            try:
                self._raise_if_library_controlled(repo_id)
                self.ragflow_client.delete_chats([chat_id])
            except OpenWebUISyncInterruptedError:
                raise
            except (ApiError, httpx.RequestError, RuntimeError, TypeError, ValueError) as exc:
                remaining["chats"].append(chat_id)
                self.log.warning(
                    "openwebui.sync.replaced_chat_cleanup_deferred",
                    ragflow_chat_id=chat_id,
                    error_class=exc.__class__.__name__,
                )
            else:
                summary.chats_deleted += 1
                self.log.info(
                    "openwebui.sync.ragflow_chat.deleted",
                    sync_id=sync_id,
                    dataset_id=dataset_id,
                    ragflow_chat_id=chat_id,
                )
                self._record_change(
                    sync_id,
                    "ragflow_chat",
                    "deleted",
                    chat_id,
                    dataset_id,
                )
        return remaining

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
        self._raise_if_library_controlled(mapping.repo_id)
        self.openwebui_client.delete_tool(tool_id)
        self.log.info("openwebui.sync.tool.deleted", openwebui_tool_id=tool_id)
        return "deleted"

    def _delete_owned_tool_by_id(
        self,
        tool_id: str,
        capabilities: OpenWebUICapabilities,
        *,
        repo_id: str,
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
        self._raise_if_library_controlled(repo_id)
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
        self._raise_if_library_controlled(mapping.repo_id)
        self.openwebui_client.delete_function(pipe_id)
        self.log.info("openwebui.sync.pipe.deleted", openwebui_pipe_id=pipe_id)
        return "deleted"

    def _delete_owned_pipe_by_id(
        self,
        pipe_id: str,
        capabilities: OpenWebUICapabilities,
        *,
        repo_id: str,
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
        self._raise_if_library_controlled(repo_id)
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


def _chat_name(_namespace: str, dataset_name: str, dataset_id: str) -> str:
    slug = slugify(dataset_name, fallback="dataset").replace("-", "_")
    if slug.startswith("rag_"):
        slug = slug[4:] or "dataset"
    return f"RAG_{slug}_{sha256_text(dataset_id)[:8]}"


def _is_dataset_without_parsed_files(exc: ApiError) -> bool:
    payload = exc.payload
    if not isinstance(payload, dict) or payload.get("code") not in (102, "102"):
        return False
    message = str(payload.get("message", "")).lower()
    return "dataset" in message and "parsed file" in message


def _pending_replacement_cleanup(snapshot: Any) -> dict[str, list[str]]:
    pending: dict[str, list[str]] = {"tools": [], "pipes": [], "chats": []}
    if not isinstance(snapshot, dict):
        return pending
    raw = snapshot.get(_PENDING_REPLACEMENT_CLEANUP_KEY)
    if not isinstance(raw, dict):
        return pending
    for kind in pending:
        values = raw.get(kind)
        if not isinstance(values, list):
            continue
        pending[kind] = list(
            dict.fromkeys(value for value in values if isinstance(value, str) and value)
        )
    return pending


def _replacement_cleanup_candidates(
    pending: dict[str, list[str]],
    *,
    previous_tool_id: str | None,
    next_tool_id: str | None,
    previous_pipe_id: str | None,
    next_pipe_id: str | None,
    previous_chat_id: str | None,
    next_chat_id: str | None,
) -> dict[str, list[str]]:
    candidates = _pending_replacement_cleanup(
        {_PENDING_REPLACEMENT_CLEANUP_KEY: pending}
    )
    replacements = (
        ("tools", previous_tool_id, next_tool_id),
        ("pipes", previous_pipe_id, next_pipe_id),
        ("chats", previous_chat_id, next_chat_id),
    )
    for kind, previous_id, next_id in replacements:
        if previous_id and next_id and previous_id != next_id:
            candidates[kind] = list(dict.fromkeys([*candidates[kind], previous_id]))
    return candidates


def _capabilities_with_pending_cleanup(
    capabilities: dict[str, Any],
    pending: dict[str, list[str]],
) -> dict[str, Any]:
    snapshot = dict(capabilities)
    normalized = _pending_replacement_cleanup(
        {_PENDING_REPLACEMENT_CLEANUP_KEY: pending}
    )
    if any(normalized.values()):
        snapshot[_PENDING_REPLACEMENT_CLEANUP_KEY] = normalized
    else:
        snapshot.pop(_PENDING_REPLACEMENT_CLEANUP_KEY, None)
    return snapshot


def _chat_has_dataset(chat: dict[str, Any], dataset_id: str) -> bool:
    dataset_ids = chat.get("dataset_ids") or chat.get("kb_ids") or chat.get("datasets") or []
    if isinstance(dataset_ids, list):
        for item in dataset_ids:
            if isinstance(item, dict) and str(item.get("id")) == dataset_id:
                return True
            if str(item) == dataset_id:
                return True
    return False


def _chat_needs_update(chat: dict[str, Any], desired: dict[str, Any]) -> bool:
    for key, expected in desired.items():
        if key == "dataset_ids":
            if not all(_chat_has_dataset(chat, str(dataset_id)) for dataset_id in expected):
                return True
            continue
        actual = chat.get(key)
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or not _dict_contains(actual, expected):
                return True
            continue
        if actual != expected:
            return True
    return False


def _dict_contains(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict) or not _dict_contains(
                actual_value,
                expected_value,
            ):
                return False
            continue
        if actual_value != expected_value:
            return False
    return True


def _valves_with_secret(
    valves: dict[str, object],
    *,
    proxy_secret: str | None,
    answer_llm_api_key: str | None,
) -> dict[str, object]:
    data = dict(valves)
    if "CONNECTOR_PROXY_SHARED_SECRET" in data:
        data["CONNECTOR_PROXY_SHARED_SECRET"] = proxy_secret or ""
    if "ANSWER_LLM_API_KEY" in data:
        data["ANSWER_LLM_API_KEY"] = answer_llm_api_key or ""
    return data


def _remote_valves(artifact: dict[str, Any]) -> dict[str, object]:
    for key in ("user_valves", "function_valves", "tool_valves", "valves"):
        value = artifact.get(key)
        if isinstance(value, dict):
            return {str(name): item for name, item in value.items()}
    data = artifact.get("data")
    if isinstance(data, dict):
        return _remote_valves(data)
    return {}


def _merge_managed_valves(
    artifact: dict[str, Any],
    desired: dict[str, object],
    managed_keys: frozenset[str],
) -> dict[str, object]:
    remote = _remote_valves(artifact)
    merged = dict(remote)
    for key, value in desired.items():
        if key in managed_keys or key not in remote:
            merged[key] = value
    return merged


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
