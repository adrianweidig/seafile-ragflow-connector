from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from seafile_ragflow_connector.app.logging import configure_logging
from seafile_ragflow_connector.app.runtime import build_runtime
from seafile_ragflow_connector.clients.http import make_client, unwrap_response
from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.demo.recording import (
    REQUIRED_WORKFLOW_POINTS,
    DemoRecordingNames,
    OBSWebhookClient,
    OBSWebhookConfig,
    OBSWebhookError,
    build_recording_steps,
    build_workflow_validation_template,
    validate_recording_artifact,
    write_demo_markdown,
    write_recording_summary,
)
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output" / "demo-recording"


@dataclass(frozen=True)
class DemoRunPaths:
    run_dir: Path
    demo_file: Path
    summary_file: Path


@dataclass(frozen=True)
class SeafileLibraryResult:
    repo_id: str
    created: bool


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    names = DemoRecordingNames.build(args.demo_id)
    paths = _paths(args.output_dir, names)
    obs_config = OBSWebhookConfig.from_env()

    try:
        return _run(args, names, paths, obs_config)
    except OBSWebhookError as exc:
        print(f"FAILED: OBS webhook: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAILED: demo recording preparation: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute the visible Seafile -> RAGFlow -> OpenWebUI OBS demo. "
            "Default is a non-mutating dry-run."
        )
    )
    parser.add_argument("--execute", action="store_true", help="Mutate the configured test stack.")
    parser.add_argument("--record", action="store_true", help="Use OBS start/stop webhooks.")
    parser.add_argument(
        "--check-obs",
        action="store_true",
        help="Validate OBS webhook configuration even in dry-run mode.",
    )
    parser.add_argument("--demo-id", help="Stable run identifier. Defaults to a UTC timestamp.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated demo file and recording summaries.",
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright browser engine for the visible run.",
    )
    parser.add_argument("--headed", action="store_true", help="Show browser windows.")
    parser.add_argument(
        "--browser-window-x",
        type=int,
        default=int(os.environ.get("DEMO_BROWSER_WINDOW_X", "0")),
        help="Left position for the headed demo browser window.",
    )
    parser.add_argument(
        "--browser-window-y",
        type=int,
        default=int(os.environ.get("DEMO_BROWSER_WINDOW_Y", "0")),
        help="Top position for the headed demo browser window.",
    )
    parser.add_argument(
        "--browser-window-width",
        type=int,
        default=int(os.environ.get("DEMO_BROWSER_WINDOW_WIDTH", "1920")),
        help="Width for the headed demo browser window.",
    )
    parser.add_argument(
        "--browser-window-height",
        type=int,
        default=int(os.environ.get("DEMO_BROWSER_WINDOW_HEIGHT", "1080")),
        help="Height for the headed demo browser window.",
    )
    parser.add_argument(
        "--minimize-other-windows",
        action="store_true",
        help="On Windows, minimize existing windows before the visible recording run.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        help="Persistent Playwright profile directory with existing test logins.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=4.0,
        help="Visible pause between important pages during execute mode.",
    )
    parser.add_argument(
        "--wait-parse-seconds",
        type=int,
        default=300,
        help="Maximum wait time for RAGFlow parsing after upload.",
    )
    parser.add_argument(
        "--scene-name",
        default=os.environ.get("OBS_SCENE_NAME"),
        help="Optional OBS scene name when OBS_WEBHOOK_SCENE_URL is configured.",
    )
    parser.add_argument(
        "--obs-output-dir",
        type=Path,
        default=(
            Path(os.environ["OBS_RECORDING_OUTPUT_DIR"])
            if os.environ.get("OBS_RECORDING_OUTPUT_DIR")
            else None
        ),
        help="Local OBS recording output directory used to locate the generated MKV.",
    )
    parser.add_argument(
        "--obs-screenshot-width",
        type=int,
        default=int(os.environ.get("OBS_SCREENSHOT_WIDTH", "1920")),
        help="Width for OBS source screenshots captured during marker validation.",
    )
    parser.add_argument(
        "--obs-screenshot-height",
        type=int,
        default=int(os.environ.get("OBS_SCREENSHOT_HEIGHT", "1080")),
        help="Height for OBS source screenshots captured during marker validation.",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Execute API steps without Playwright page navigation.",
    )
    return parser


def _run(
    args: argparse.Namespace,
    names: DemoRecordingNames,
    paths: DemoRunPaths,
    obs_config: OBSWebhookConfig,
) -> int:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    write_demo_markdown(paths.demo_file, names)
    checks: dict[str, Any] = {
        "execute": bool(args.execute),
        "record": bool(args.record),
        "dry_run": not bool(args.execute),
        "steps": [step["id"] for step in build_recording_steps(names)],
        "workflow": build_workflow_validation_template(),
    }

    if args.check_obs or args.record:
        checks["obs_validation"] = _validate_obs(obs_config)

    if not args.execute:
        write_recording_summary(
            paths.summary_file,
            names=names,
            mode="dry-run",
            obs_config=obs_config,
            checks=checks,
        )
        print(json.dumps(_summary_payload(names, paths, checks), ensure_ascii=False, indent=2))
        return 0

    configure_logging("INFO", "console")
    recorder: OBSWebhookClient | None = None
    recording_state: dict[str, Any] = {"started": False, "started_at": None}
    webhook_payloads: list[Any] = []
    workflow_error: Exception | None = None
    recording_error: Exception | None = None

    try:
        if args.record:
            recorder = OBSWebhookClient(obs_config)
            recorder.validate()

        try:
            checks.update(
                _execute_workflow(
                    args,
                    names,
                    paths,
                    recorder,
                    checks["workflow"],
                    checks,
                    webhook_payloads,
                    recording_state,
                )
            )
        except Exception as exc:
            workflow_error = exc
            checks["error"] = {
                "phase": "workflow",
                "type": type(exc).__name__,
                "message": str(exc),
            }
    finally:
        if recorder is not None:
            try:
                if recording_state.get("started"):
                    try:
                        recorder.add_marker("demo-stop", demo_id=names.demo_id)
                        stop_payload = recorder.stop_recording(demo_id=names.demo_id)
                        webhook_payloads.append(stop_payload)
                        checks.setdefault("obs_recording", {})["stop"] = "erfüllt"
                        checks["obs_recording"]["stop_response"] = stop_payload
                    except Exception as exc:
                        recording_error = exc
                        checks.setdefault("obs_recording", {})["stop"] = "nicht erfüllt"
                        checks["obs_recording"]["stop_error"] = str(exc)
                    try:
                        status_after_stop = recorder.status()
                    except Exception as exc:
                        checks.setdefault("obs_recording", {})["status_after_stop_error"] = str(exc)
                    else:
                        if status_after_stop is not None:
                            webhook_payloads.append(status_after_stop)
                            checks.setdefault("obs_recording", {})[
                                "status_after_stop"
                            ] = status_after_stop
            finally:
                recorder.close()

    if args.record and recording_state.get("started"):
        output_dir = args.obs_output_dir or obs_config.recording_output_dir
        artifact = validate_recording_artifact(
            recording_name=names.recording_name,
            demo_id=names.demo_id,
            expected_extension=obs_config.expected_extension,
            output_dir=output_dir,
            webhook_payloads=webhook_payloads,
            started_at=recording_state.get("started_at"),
        )
        checks.setdefault("obs_recording", {})["artifact"] = artifact
        if not artifact["valid"]:
            recording_error = OBSWebhookError(
                "OBS recording did not produce a non-empty MKV artifact. "
                f"artifact={artifact}"
            )

    mode = "execute-recording" if args.record else "execute-no-recording"
    write_recording_summary(
        paths.summary_file,
        names=names,
        mode=mode,
        obs_config=obs_config,
        checks=checks,
    )
    print(json.dumps(_summary_payload(names, paths, checks), ensure_ascii=False, indent=2))

    if workflow_error is not None:
        raise workflow_error
    if recording_error is not None:
        raise recording_error
    _assert_required_workflow_complete(checks["workflow"])
    return 0


def _execute_workflow(
    args: argparse.Namespace,
    names: DemoRecordingNames,
    paths: DemoRunPaths,
    recorder: OBSWebhookClient | None,
    workflow: dict[str, dict[str, Any]],
    checks: dict[str, Any],
    webhook_payloads: list[Any],
    recording_state: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    runtime = build_runtime(settings)
    try:
        if args.headed and args.minimize_other_windows:
            _minimize_other_windows()
        pages = _open_browser_pages(args, settings) if not args.skip_browser else None
        try:
            seafile_url = settings.seafile_public_base_url or settings.seafile_base_url
            _show_pages(pages, "seafile", seafile_url)
            _ensure_browser_login(
                pages,
                "seafile",
                username=os.environ.get("SEAFILE_UI_EMAIL") or settings.seafile_sync_user_email,
                password=os.environ.get("SEAFILE_UI_PASSWORD"),
            )
            _capture_obs_checkpoint(recorder, "00-preflight-browser", names, paths, args, checks)
            _start_obs_recording(
                recorder,
                args,
                names,
                checks,
                webhook_payloads,
                recording_state,
            )
            _record_marker(recorder, "seafile-opened", names.demo_id)
            _capture_obs_checkpoint(recorder, "01-seafile-opened", names, paths, args, checks)
            _pause(args.pause_seconds)

            library = _ensure_seafile_library(settings, names.library_name)
            repo_id = library.repo_id
            _record_marker(recorder, "seafile-library-created", names.demo_id)
            _mark_workflow(
                workflow,
                "seafile_library_created",
                "erfüllt",
                f"repo_id={repo_id}; created={library.created}",
                automatic=True,
                visual=pages is not None,
            )
            _show_pages(
                pages,
                "seafile",
                _seafile_library_url(settings, repo_id, names.library_name),
            )
            root_entries = _list_seafile_root_entries(settings, repo_id)
            if root_entries:
                entry_names = ", ".join(
                    str(item.get("name") or item.get("id")) for item in root_entries[:5]
                )
                raise RuntimeError(
                    "Seafile library is not empty before upload: " + entry_names
                )
            _mark_workflow(
                workflow,
                "seafile_empty_library_shown",
                "erfüllt",
                "root file list returned 0 entries before upload",
                automatic=True,
                visual=pages is not None,
            )
            _capture_obs_checkpoint(
                recorder,
                "02-seafile-empty-library",
                names,
                paths,
                args,
                checks,
            )
            _pause(args.pause_seconds)

            runtime.orchestrator.discover_libraries()
            dataset_id = runtime.orchestrator.ensure_dataset_for_repo(repo_id)
            dataset_name = _dataset_name(runtime.orchestrator.session_factory, repo_id)
            ragflow_url = settings.ragflow_public_base_url or settings.ragflow_base_url
            _show_pages(pages, "ragflow", _ragflow_dataset_url(ragflow_url, dataset_id))
            _record_marker(recorder, "ragflow-dataset-created", names.demo_id)
            dataset = runtime.ragflow_client.get_dataset(dataset_id)
            _mark_workflow(
                workflow,
                "ragflow_dataset_created",
                "erfüllt",
                f"dataset_id={dataset_id}; name={dataset.get('name') or dataset_name}",
                automatic=True,
                visual=pages is not None,
            )
            _ensure_browser_login(
                pages,
                "ragflow",
                username=os.environ.get("RAGFLOW_UI_EMAIL"),
                password=os.environ.get("RAGFLOW_UI_PASSWORD"),
            )
            if (
                pages is not None
                and os.environ.get("RAGFLOW_UI_EMAIL")
                and os.environ.get("RAGFLOW_UI_PASSWORD")
                and "/login" in str(pages["ragflow"].url)
            ):
                raise RuntimeError("RAGFlow UI login failed; still on login page")
            _show_pages(pages, "ragflow", _ragflow_dataset_url(ragflow_url, dataset_id))
            _capture_obs_checkpoint(recorder, "03-ragflow-dataset", names, paths, args, checks)
            _pause(args.pause_seconds)

            agent = _ensure_ragflow_agent_for_dataset(settings, names, dataset_id)
            agent_id = str(agent.get("id") or "")
            if not agent_id:
                raise RuntimeError("RAGFlow agent was not created before upload")
            _record_marker(recorder, "ragflow-agent-created-before-upload", names.demo_id)
            _show_pages(pages, "ragflow", _ragflow_agent_url(ragflow_url, agent_id))
            _mark_workflow(
                workflow,
                "ragflow_chat_created",
                "erfüllt",
                f"ragflow_agent_id={agent_id}; dataset_id={dataset_id}",
                automatic=True,
                visual=pages is not None,
            )
            _capture_obs_checkpoint(
                recorder,
                "04-ragflow-agent-before-upload",
                names,
                paths,
                args,
                checks,
            )
            _pause(args.pause_seconds)

            _upload_file(settings, repo_id, paths.demo_file, library_name=names.library_name)
            _record_marker(recorder, "seafile-file-uploaded", names.demo_id)
            _show_pages(
                pages,
                "seafile",
                _seafile_library_url(settings, repo_id, names.library_name),
            )
            uploaded_entries = _list_seafile_root_entries(settings, repo_id)
            if not any(str(item.get("name") or "") == names.file_name for item in uploaded_entries):
                raise RuntimeError(f"Uploaded file is not visible in Seafile: {names.file_name}")
            _mark_workflow(
                workflow,
                "file_uploaded_after_chat",
                "erfüllt",
                f"uploaded={names.file_name}",
                automatic=True,
                visual=pages is not None,
            )
            _capture_obs_checkpoint(recorder, "05-seafile-uploaded", names, paths, args, checks)
            _pause(args.pause_seconds)

            sync_summary = runtime.orchestrator.sync_library_full(repo_id)
            documents_after_parse = _wait_for_parse(
                runtime.ragflow_client.list_documents,
                dataset_id,
                args.wait_parse_seconds,
            )
            documents = documents_after_parse or runtime.ragflow_client.list_documents(dataset_id)
            if not documents:
                raise RuntimeError("RAGFlow document list is empty after sync")
            _show_pages(pages, "ragflow", _ragflow_dataset_url(ragflow_url, dataset_id))
            _mark_workflow(
                workflow,
                "ragflow_sync_shown",
                "erfüllt",
                f"documents_visible={len(documents)}",
                automatic=True,
                visual=pages is not None,
            )
            _mark_workflow(
                workflow,
                "ragflow_parsing_shown",
                "erfüllt",
                "no RUNNING or UNSTART documents after parse wait",
                automatic=True,
                visual=pages is not None,
            )
            _record_marker(recorder, "ragflow-file-synced-and-parsed", names.demo_id)
            _capture_obs_checkpoint(
                recorder,
                "06-ragflow-synced-parsed",
                names,
                paths,
                args,
                checks,
            )
            _pause(args.pause_seconds)

            retrieval = runtime.ragflow_client.retrieve_chunks(
                dataset_id=dataset_id,
                question=names.question,
                top_k=5,
                page_size=5,
            )
            chunks = _extract_chunks(retrieval)
            if not chunks:
                raise RuntimeError("RAGFlow retrieval did not return chunks for the demo document")
            chunk_document = _select_demo_document(documents, names.file_name)
            chunk_document_id = _document_id(chunk_document)
            if not chunk_document_id:
                raise RuntimeError("RAGFlow document id is missing; cannot open chunk UI")
            chunk_ui_url = _ragflow_dataflow_url(ragflow_url, dataset_id, chunk_document_id)
            if not chunk_ui_url:
                raise RuntimeError("RAGFlow public URL is missing; cannot open chunk UI")
            _show_pages(pages, "ragflow", chunk_ui_url)
            _select_ragflow_chunk_stage(pages)
            _mark_workflow(
                workflow,
                "ragflow_chunks_shown",
                "erfüllt",
                f"retrieval_chunks={len(chunks)}; chunk_ui_url={chunk_ui_url}",
                automatic=True,
                visual=pages is not None,
            )
            _record_marker(recorder, "ragflow-chunks-opened", names.demo_id)
            _capture_obs_checkpoint(recorder, "07-ragflow-chunks", names, paths, args, checks)
            _pause(args.pause_seconds)

            if runtime.openwebui_sync_service is not None:
                openwebui_summary = runtime.openwebui_sync_service.sync_once(repo_ids={repo_id})
                if openwebui_summary.failed:
                    raise RuntimeError(
                        "OpenWebUI sync failed after RAGFlow parsing; "
                        f"failed={openwebui_summary.failed}"
                    )
            mapping = _openwebui_mapping(runtime.orchestrator.session_factory, repo_id)
            if mapping is None or not mapping.ragflow_chat_id:
                raise RuntimeError("RAGFlow chat was not created after parsing")
            _show_pages(pages, "ragflow", _ragflow_chat_url(ragflow_url, mapping.ragflow_chat_id))
            _record_marker(recorder, "ragflow-chat-created-after-parse", names.demo_id)
            _pause(args.pause_seconds)

            _show_pages(pages, "openwebui", settings.openwebui_base_url)
            _capture_obs_checkpoint(recorder, "08-openwebui-pipe", names, paths, args, checks)
            _mark_workflow(
                workflow,
                "openwebui_pipe_shown",
                "erfüllt" if mapping.openwebui_pipe_id else "nicht erfüllt",
                (
                    f"pipe_id={mapping.openwebui_pipe_id or ''}; "
                    f"model={_openwebui_model_id(mapping)}"
                ),
                automatic=bool(mapping.openwebui_pipe_id),
                visual=pages is not None,
            )
            openwebui_result = _run_openwebui_visible_question(
                pages,
                settings,
                names,
                mapping,
                paths,
                recorder,
                checks,
                args,
                pause_seconds=args.pause_seconds,
            )
            _merge_openwebui_workflow(workflow, openwebui_result, pages is not None)
            _record_marker(recorder, "openwebui-question-ready", names.demo_id)
            _pause(args.pause_seconds)

            return {
                "seafile_repo_id": repo_id,
                "ragflow_dataset_id": dataset_id,
                "ragflow_dataset_name": dataset_name,
                "openwebui_pipe_id": mapping.openwebui_pipe_id if mapping else None,
                "ragflow_chat_id": mapping.ragflow_chat_id if mapping else None,
                "ragflow_agent_id": agent_id,
                "ragflow_chunk_ui_url": chunk_ui_url,
                "files_uploaded": sync_summary.files_uploaded,
                "documents_visible": len(documents),
                "retrieval_chunks_visible": len(chunks),
                "openwebui_chat_url": openwebui_result.get("chat_url"),
                "openwebui_preview_url": openwebui_result.get("preview_url"),
                "openwebui_original_url": openwebui_result.get("original_url"),
            }
        finally:
            if pages is not None:
                close = pages.get("close")
                if callable(close):
                    close()
    finally:
        runtime.close()


def _validate_obs(config: OBSWebhookConfig) -> dict[str, Any]:
    client = OBSWebhookClient(config)
    try:
        return client.validate()
    finally:
        client.close()


def _ensure_seafile_library(settings: Any, library_name: str) -> SeafileLibraryResult:
    admin_client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_admin_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    sync_client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        for library in _extract_list(
            unwrap_response(
                admin_client.get(
                    "/api/v2.1/admin/libraries/",
                    params={"per_page": 500},
                )
            )
        ):
            name = str(library.get("name") or library.get("repo_name") or "")
            if name == library_name:
                return SeafileLibraryResult(repo_id=_repo_id(library), created=False)
        created = unwrap_response(sync_client.post("/api2/repos/", data={"name": library_name}))
        if not isinstance(created, dict):
            raise TypeError(f"unexpected Seafile create response for {library_name}")
        return SeafileLibraryResult(repo_id=_repo_id(created), created=True)
    finally:
        admin_client.close()
        sync_client.close()


def _list_seafile_root_entries(settings: Any, repo_id: str) -> list[dict[str, Any]]:
    client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        data = unwrap_response(client.get(f"/api2/repos/{repo_id}/dir/", params={"p": "/"}))
        return _extract_list(data)
    finally:
        client.close()


def _upload_file(
    settings: Any,
    repo_id: str,
    path: Path,
    *,
    library_name: str,
) -> None:
    upload_method = os.environ.get("DEMO_SEAFILE_UPLOAD_METHOD", "api").strip().lower()
    if upload_method == "webdav":
        if _upload_file_webdav(settings, library_name, path):
            return
        raise RuntimeError(
            "DEMO_SEAFILE_UPLOAD_METHOD=webdav is configured, but WebDAV upload failed"
        )
    if upload_method != "api":
        raise RuntimeError(f"unsupported DEMO_SEAFILE_UPLOAD_METHOD={upload_method!r}")

    client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        attempts = max(1, int(os.environ.get("DEMO_SEAFILE_UPLOAD_ATTEMPTS", "3")))
        upload_timeout = max(
            10.0,
            float(os.environ.get("DEMO_SEAFILE_UPLOAD_TIMEOUT_SECONDS", "60")),
        )
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            upload_link = unwrap_response(
                client.get(
                    f"/api2/repos/{repo_id}/upload-link/",
                    params={"p": "/"},
                )
            )
            if not isinstance(upload_link, str):
                raise TypeError(f"unexpected Seafile upload-link response for {repo_id}")
            try:
                with path.open("rb") as handle:
                    response = httpx.post(
                        _rewrite_local_service_url(
                            upload_link.strip().strip('"'),
                            settings.seafile_base_url,
                        ),
                        headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
                        data={"parent_dir": "/", "replace": "1"},
                        files={"file": (path.name, handle, "text/markdown")},
                        timeout=upload_timeout,
                        verify=settings.seafile_httpx_verify,
                    )
                unwrap_response(response)
                return
            except Exception as exc:
                last_error = exc
                if _file_visible_in_seafile(client, repo_id, path.name):
                    return
                if attempt < attempts:
                    time.sleep(min(10, attempt * 3))
        if _upload_file_webdav(settings, library_name, path):
            return
        if last_error is not None:
            raise last_error
    finally:
        client.close()


def _upload_file_webdav(settings: Any, library_name: str, path: Path) -> bool:
    base_url = os.environ.get("SEAFILE_WEBDAV_BASE_URL", "").strip().rstrip("/")
    username = (
        os.environ.get("SEAFILE_WEBDAV_USERNAME")
        or os.environ.get("SEAFILE_UI_EMAIL")
        or getattr(settings, "seafile_sync_user_email", "")
    )
    password = os.environ.get("SEAFILE_WEBDAV_PASSWORD") or os.environ.get("SEAFILE_UI_PASSWORD")
    if not base_url or not username or not password:
        return False
    url = f"{base_url}/{quote(library_name, safe='')}/{quote(path.name, safe='')}"
    with httpx.Client(auth=(username, password), timeout=60.0, follow_redirects=False) as client:
        response = client.put(
            url,
            content=path.read_bytes(),
            headers={"Content-Type": "text/markdown"},
        )
        if response.status_code not in {200, 201, 204}:
            return False
        check = client.get(url)
        return check.status_code == 200 and path.name in url


def _file_visible_in_seafile(client: Any, repo_id: str, file_name: str) -> bool:
    with suppress(Exception):
        data = unwrap_response(client.get(f"/api2/repos/{repo_id}/dir/", params={"p": "/"}))
        return any(str(item.get("name") or "") == file_name for item in _extract_list(data))
    return False


def _ensure_ragflow_agent_for_dataset(
    settings: Any,
    names: DemoRecordingNames,
    dataset_id: str,
) -> dict[str, Any]:
    client = make_client(
        settings.ragflow_base_url,
        headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
        timeout=120.0,
        verify=settings.ragflow_httpx_verify,
    )
    try:
        existing = _agent_list(
            unwrap_response(
                client.get(
                    "/api/v1/agents",
                    params={"title": names.chat_label, "page": 1, "page_size": 100},
                )
            )
        )
        for agent in existing:
            if str(agent.get("title") or "") == names.chat_label:
                return agent

        templates = _agent_list(unwrap_response(client.get("/api/v1/agents/templates")))
        template = _select_agent_template(templates)
        dsl = copy.deepcopy(template.get("dsl") or {})
        _bind_agent_dsl_to_dataset(dsl, dataset_id, names)
        created = unwrap_response(
            client.post(
                "/api/v1/agents",
                json={
                    "title": names.chat_label,
                    "description": (
                        "Demo-Agent für die OBS-Aufnahme. Das Retrieval-Tool ist "
                        "vor dem Seafile-Upload mit dem leeren Dataset verbunden."
                    ),
                    "canvas_category": "agent_canvas",
                    "dsl": dsl,
                    "release": False,
                },
            )
        )
        if not isinstance(created, dict):
            raise TypeError("unexpected RAGFlow agent create response")
        return created
    finally:
        client.close()


def _select_agent_template(templates: list[dict[str, Any]]) -> dict[str, Any]:
    for template in templates:
        title = template.get("title")
        title_values = title.values() if isinstance(title, dict) else [title]
        if any(str(value).lower() == "your starter dataset chatbot" for value in title_values):
            return template
    for template in templates:
        if template.get("canvas_category") == "agent_canvas" and isinstance(
            template.get("dsl"), dict
        ):
            return template
    raise RuntimeError("RAGFlow does not expose a usable agent template")


def _bind_agent_dsl_to_dataset(
    dsl: dict[str, Any],
    dataset_id: str,
    names: DemoRecordingNames,
) -> None:
    dsl["retrieval"] = [dataset_id]
    components = dsl.get("components")
    if not isinstance(components, dict):
        return
    for component in components.values():
        if not isinstance(component, dict):
            continue
        obj = component.get("obj")
        if not isinstance(obj, dict):
            continue
        params = obj.get("params")
        if not isinstance(params, dict):
            continue
        if obj.get("component_name") == "Agent":
            params["description"] = names.dataset_label
            params["sys_prompt"] = (
                "Du bist der Demo-Agent für die OBS-Aufnahme. Nutze ausschließlich "
                "das angebundene Dataset und antworte mit Quellenbezug."
            )
            for tool in params.get("tools") or []:
                if not isinstance(tool, dict) or tool.get("component_name") != "Retrieval":
                    continue
                tool_params = tool.setdefault("params", {})
                if isinstance(tool_params, dict):
                    tool_params["kb_ids"] = [dataset_id]
                    tool_params["description"] = names.dataset_label


def _agent_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("canvas", "agents", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _wait_for_parse(
    list_documents: Callable[[str], list[dict[str, Any]]],
    dataset_id: str,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        documents = list_documents(dataset_id)
        active = any(
            str(doc.get("run") or "").upper() in {"RUNNING", "UNSTART"}
            for doc in documents
        )
        if documents and not active:
            return documents
        time.sleep(5)
    raise TimeoutError(f"RAGFlow parsing did not finish within {timeout_seconds} seconds")


def _open_browser_pages(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        if exc.name != "playwright":
            raise
        raise RuntimeError(
            "Playwright is not installed. Run: uv sync --locked --all-extras"
        ) from exc

    playwright = sync_playwright().start()
    browser_type = getattr(playwright, args.browser)
    launch_args = _browser_launch_args(args)
    launch_kwargs: dict[str, Any] = {"headless": not args.headed}
    if launch_args:
        launch_kwargs["args"] = launch_args
    viewport = _browser_viewport(args)
    if args.profile_dir:
        context = browser_type.launch_persistent_context(
            user_data_dir=str(args.profile_dir),
            viewport=viewport,
            ignore_https_errors=True,
            **launch_kwargs,
        )
        browser = None
    else:
        browser = browser_type.launch(**launch_kwargs)
        context = browser.new_context(
            viewport=viewport,
            ignore_https_errors=True,
        )
    if settings.openwebui_admin_api_key:
        token = json.dumps(settings.openwebui_admin_api_key)
        context.add_init_script(
            "window.localStorage.setItem('token', "
            + token
            + "); window.localStorage.setItem('token_type', 'Bearer'); "
            "window.localStorage.setItem('locale', 'de-DE');"
        )
    pages = {
        "seafile": context.new_page(),
        "ragflow": context.new_page(),
        "openwebui": context.new_page(),
        "_focus_page": lambda page: _focus_playwright_page(page, args),
        "close": lambda: _close_playwright(context, browser, playwright),
    }
    _show_pages(pages, "seafile", settings.seafile_public_base_url or settings.seafile_base_url)
    return pages


def _show_pages(pages: dict[str, Any] | None, name: str, url: str | None) -> None:
    if pages is None or not url:
        return
    page = pages[name]
    _focus_page(pages, page)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    with suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=30_000)
    _wait_for_visible_body(page)
    _focus_page(pages, page)


def _browser_launch_args(args: argparse.Namespace) -> list[str]:
    if not args.headed or args.browser != "chromium":
        return []
    return [
        f"--window-position={args.browser_window_x},{args.browser_window_y}",
        f"--window-size={args.browser_window_width},{args.browser_window_height}",
        "--start-maximized",
        "--disable-extensions",
        "--disable-infobars",
        "--disable-notifications",
        "--disable-session-crashed-bubble",
        "--no-default-browser-check",
        "--no-first-run",
    ]


def _browser_viewport(args: argparse.Namespace) -> dict[str, int]:
    if not args.headed:
        return {"width": 1440, "height": 1000}
    return {
        "width": max(1024, args.browser_window_width),
        "height": max(720, args.browser_window_height - 90),
    }


def _focus_page(pages: dict[str, Any], page: Any) -> None:
    focus = pages.get("_focus_page")
    if callable(focus):
        focus(page)
    else:
        page.bring_to_front()


def _focus_playwright_page(page: Any, args: argparse.Namespace) -> None:
    page.bring_to_front()
    if not args.headed:
        return
    with suppress(Exception):
        page.evaluate(
            """([x, y, width, height]) => {
                window.moveTo(x, y);
                window.resizeTo(width, height);
                window.focus();
            }""",
            [
                args.browser_window_x,
                args.browser_window_y,
                args.browser_window_width,
                args.browser_window_height,
            ],
        )
    with suppress(Exception):
        page.bring_to_front()


def _wait_for_visible_body(page: Any, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with suppress(Exception):
            text = page.locator("body").inner_text(timeout=1_000).strip()
            if len(text) >= 20:
                return
        time.sleep(0.5)


def _minimize_other_windows() -> None:
    if os.name != "nt":
        return
    with suppress(Exception):
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(New-Object -ComObject Shell.Application).MinimizeAll()",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        time.sleep(1.0)


def _ensure_browser_login(
    pages: dict[str, Any] | None,
    name: str,
    *,
    username: str | None,
    password: str | None,
) -> bool:
    if pages is None or not username or not password:
        return False
    page = pages[name]
    password_input = page.locator("input[type='password']").first
    try:
        password_input.wait_for(state="visible", timeout=30_000)
    except Exception:
        return False
    username_input = page.locator(
        "input[name='login'], input[name='email'], input[name='username'], "
        "input[type='email'], input[type='text']"
    ).first
    filled = False
    with suppress(Exception):
        result = page.evaluate(
            """([username, password]) => {
                const visible = (element) => {
                    const style = window.getComputedStyle(element);
                    return style.visibility !== "hidden"
                        && style.display !== "none"
                        && element.getClientRects().length > 0;
                };
                const inputs = Array.from(document.querySelectorAll("input")).filter(visible);
                const passwordInput = inputs.find((input) => input.type === "password");
                const usernameInput = inputs.find((input) =>
                    input !== passwordInput
                    && ["", "text", "email"].includes(input.type || "")
                );
                const setValue = (input, value) => {
                    const prototype = Object.getPrototypeOf(input);
                    const prototypeSetter =
                        Object.getOwnPropertyDescriptor(prototype, "value")?.set;
                    const nativeSetter =
                        Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype,
                            "value",
                        )?.set;
                    input.focus();
                    if (prototypeSetter) {
                        prototypeSetter.call(input, value);
                    } else if (nativeSetter) {
                        nativeSetter.call(input, value);
                    } else {
                        input.value = value;
                    }
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                };
                if (usernameInput) {
                    setValue(usernameInput, username);
                }
                if (passwordInput) {
                    setValue(passwordInput, password);
                }
                return Boolean(usernameInput && passwordInput);
            }""",
            [username, password],
        )
        filled = bool(result)
    if not filled:
        if username_input.count() > 0:
            username_input.fill(username)
        password_input.fill(password)
    submit = page.locator(
        "button[type='submit'], button:has-text('Login'), button:has-text('Sign in'), "
        "button:has-text('Anmelden'), button:has-text('Einloggen')"
    ).first
    if submit.count() > 0:
        submit.click()
    else:
        page.keyboard.press("Enter")
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    with suppress(Exception):
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
    _wait_for_visible_body(page)
    with suppress(Exception):
        if "/login" in page.url:
            return False
    return True


def _close_playwright(context: Any, browser: Any, playwright: Any) -> None:
    context.close()
    if browser is not None:
        browser.close()
    playwright.stop()


def _dataset_name(session_factory: Any, repo_id: str) -> str | None:
    with session_factory() as session:
        library = session.get(Library, repo_id)
        if library and library.ragflow_dataset_name:
            return str(library.ragflow_dataset_name)
        return None


def _openwebui_mapping(session_factory: Any, repo_id: str) -> OpenWebUIDatasetMapping | None:
    with session_factory() as session:
        mapping = session.query(OpenWebUIDatasetMapping).filter_by(repo_id=repo_id).one_or_none()
        if mapping is None:
            return None
        session.expunge(mapping)
        return mapping


def _run_openwebui_visible_question(
    pages: dict[str, Any] | None,
    settings: Any,
    names: DemoRecordingNames,
    mapping: OpenWebUIDatasetMapping,
    paths: DemoRunPaths,
    recorder: OBSWebhookClient | None,
    checks: dict[str, Any],
    args: argparse.Namespace,
    *,
    pause_seconds: float,
) -> dict[str, Any]:
    if pages is None:
        return {
            "question_asked": False,
            "answer_visible": False,
            "preview_opened": False,
            "original_opened": False,
            "reason": "browser navigation disabled",
        }
    page = pages["openwebui"]
    _focus_page(pages, page)
    page.goto(settings.openwebui_base_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    _pause(pause_seconds)

    model_id = _openwebui_model_id(mapping)
    model_display_name = _openwebui_model_display_name(mapping)
    if model_id:
        _select_openwebui_model(page, model_id, model_display_name)
    editor = page.locator("textarea, [contenteditable=true]").last
    editor.click(timeout=30_000)
    try:
        editor.fill(names.question)
    except Exception:
        page.keyboard.insert_text(names.question)
    page.keyboard.press("Enter")
    with suppress(Exception):
        page.wait_for_url("**/c/**", timeout=45_000)
    chat_url = page.url
    answer_wait_timeout = max(
        20.0,
        float(os.environ.get("DEMO_OPENWEBUI_ANSWER_TIMEOUT_SECONDS", "120")),
    )
    answer_state = _wait_for_openwebui_answer_state(page, chat_url, answer_wait_timeout)
    if answer_state.get("preview_url"):
        try:
            page.goto(chat_url, wait_until="networkidle", timeout=60_000)
        except Exception:
            page.goto(chat_url, wait_until="domcontentloaded", timeout=60_000)
        _pause(pause_seconds)
    preview_url = str(answer_state.get("preview_url") or "")
    body_text = page.locator("body").inner_text(timeout=30_000)
    answer_text = str(answer_state.get("content") or body_text)
    answer_visible = bool(preview_url) and (
        "Bibliothek-Sync-Chunk-Preview-Originalprüfung" in answer_text
        or names.file_name in answer_text
        or (
            "Demo-Dokument" in answer_text
            and "Seafile" in answer_text
            and "RAGFlow" in answer_text
            and "OpenWebUI" in answer_text
        )
    )
    screenshot = paths.run_dir / "openwebui-answer.png"
    page.screenshot(path=str(screenshot), full_page=True)
    _capture_obs_checkpoint(recorder, "09-openwebui-answer", names, paths, args, checks)

    preview_opened = False
    original_opened = False
    original_url = ""
    if preview_url:
        preview = page.context.new_page()
        try:
            _focus_page(pages, preview)
            preview.goto(preview_url, wait_until="networkidle", timeout=60_000)
            _focus_page(pages, preview)
            _pause(pause_seconds)
            preview_text = preview.locator("body").inner_text(timeout=30_000)
            preview_opened = (
                "Bibliothek-Sync-Chunk-Preview-Originalprüfung" in preview_text
                or names.file_name in preview_text
                or "Original öffnen" in preview_text
            )
            preview.screenshot(path=str(paths.run_dir / "openwebui-preview.png"), full_page=True)
            _capture_obs_checkpoint(recorder, "10-openwebui-preview", names, paths, args, checks)
            original_url = str(
                preview.evaluate(
                    """() => {
                        const link = document.querySelector("a.original-action[href]");
                        return link ? link.href : "";
                    }"""
                )
                or ""
            )
            if original_url:
                original = page.context.new_page()
                try:
                    _focus_page(pages, original)
                    original.goto(original_url, wait_until="domcontentloaded", timeout=60_000)
                    _ensure_browser_login(
                        {"seafile": original},
                        "seafile",
                        username=(
                            os.environ.get("SEAFILE_UI_EMAIL")
                            or getattr(settings, "seafile_sync_user_email", None)
                        ),
                        password=os.environ.get("SEAFILE_UI_PASSWORD"),
                    )
                    _focus_page(pages, original)
                    _pause(pause_seconds)
                    original_text = original.locator("body").inner_text(timeout=30_000)
                    original_opened = (
                        "Bibliothek-Sync-Chunk-Preview-Originalprüfung" in original_text
                        or names.file_name in original_text
                        or "Demo-Dokument" in original_text
                    )
                    original.screenshot(
                        path=str(paths.run_dir / "openwebui-original.png"),
                        full_page=True,
                    )
                    _capture_obs_checkpoint(
                        recorder,
                        "11-openwebui-original",
                        names,
                        paths,
                        args,
                        checks,
                    )
                finally:
                    original.close()
        finally:
            preview.close()
    _focus_page(pages, page)
    _pause(pause_seconds)
    _capture_obs_checkpoint(recorder, "12-openwebui-final-chat", names, paths, args, checks)
    return {
        "question_asked": True,
        "answer_visible": answer_visible,
        "preview_opened": preview_opened,
        "original_opened": original_opened,
        "chat_url": chat_url,
        "preview_url": preview_url,
        "original_url": original_url,
        "answer_screenshot": str(screenshot),
    }


def _select_openwebui_model(
    page: Any,
    model_id: str,
    display_name: str | None = None,
) -> None:
    page.evaluate(
        """(id) => {
            window.localStorage.setItem("selectedModels", JSON.stringify([id]));
        }""",
        model_id,
    )
    try:
        page.reload(wait_until="networkidle", timeout=60_000)
    except Exception:
        page.reload(wait_until="domcontentloaded", timeout=60_000)
    if display_name and _openwebui_selected_model_visible(page, display_name):
        return
    if display_name:
        _select_openwebui_model_from_dropdown(page, display_name)
        if _openwebui_selected_model_visible(page, display_name):
            return
    if _openwebui_selected_model_visible(page, model_id):
        return
    raise RuntimeError(
        "OpenWebUI did not select the generated RAGFlow pipe model: "
        f"{display_name or model_id}"
    )


def _select_openwebui_model_from_dropdown(page: Any, display_name: str) -> None:
    selector = (
        "button[aria-label^='Ausgewähltes Modell'], "
        "button[aria-label^='Selected model']"
    )
    page.locator(selector).first.click(timeout=20_000)
    option = page.locator(
        "button",
        has_text=display_name,
    ).first
    option.wait_for(state="visible", timeout=20_000)
    option.click(timeout=20_000)
    page.wait_for_timeout(1_000)


def _openwebui_selected_model_visible(page: Any, expected: str) -> bool:
    expected_norm = expected.strip().lower()
    if not expected_norm:
        return False
    try:
        selected = page.locator(
            "button[aria-label^='Ausgewähltes Modell'], "
            "button[aria-label^='Selected model']"
        ).first
        text = selected.inner_text(timeout=10_000).strip().lower()
        aria = str(selected.get_attribute("aria-label") or "").strip().lower()
    except Exception:
        return False
    return expected_norm in text or expected_norm in aria


def _openwebui_model_id(mapping: OpenWebUIDatasetMapping) -> str:
    pipe_id = str(mapping.openwebui_pipe_id or "")
    model_name = str(mapping.openwebui_model_name or "")
    if pipe_id and model_name:
        return f"{pipe_id}.{model_name}"
    return model_name or pipe_id


def _openwebui_model_display_name(mapping: OpenWebUIDatasetMapping) -> str | None:
    dataset_name = str(mapping.ragflow_dataset_name or "").strip()
    if dataset_name:
        return f"Seafile · {dataset_name}"
    payload = mapping.openwebui_pipe_payload or {}
    name = payload.get("name") if isinstance(payload, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _wait_for_openwebui_preview_url(page: Any, timeout_seconds: float) -> str:
    deadline = time.monotonic() + timeout_seconds
    preview_url = ""
    while time.monotonic() < deadline:
        preview_url = _first_anchor_href(page, "/api/openwebui/sources/preview?token=")
        if preview_url:
            return preview_url
        with suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=2_000)
        time.sleep(2)
    return preview_url


def _wait_for_openwebui_answer_state(
    page: Any,
    chat_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    chat_id = _openwebui_chat_id_from_url(chat_url)
    state: dict[str, Any] = {"content": "", "preview_url": ""}
    while time.monotonic() < deadline:
        preview_url = _first_anchor_href(page, "/api/openwebui/sources/preview?token=")
        if preview_url:
            state["preview_url"] = preview_url
            state["content"] = page.locator("body").inner_text(timeout=10_000)
            return state
        if chat_id:
            api_state = _openwebui_chat_answer_state(page, chat_id)
            if api_state.get("preview_url"):
                return api_state
            state = api_state or state
        with suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=2_000)
        time.sleep(2)
    return state


def _openwebui_chat_answer_state(page: Any, chat_id: str) -> dict[str, Any]:
    result = page.evaluate(
        """async (chatId) => {
            const token = window.localStorage.getItem("token") || "";
            const response = await fetch(`/api/v1/chats/${chatId}`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (!response.ok) {
                return { content: "", preview_url: "", done: false };
            }
            const data = await response.json();
            const chat = data.chat || data;
            const messages = Object.values((chat.history && chat.history.messages) || {});
            const assistants = messages.filter(
                (message) => message && message.role === "assistant"
            );
            const last = assistants[assistants.length - 1] || {};
            const content = String(last.content || "");
            return {
                content,
                preview_url: firstUrl(content, "/api/openwebui/sources/preview?token="),
                original_url: firstUrl(content, "/file/"),
                done: Boolean(last.done),
            };

            function firstUrl(text, needle) {
                const index = text.indexOf(needle);
                if (index < 0) {
                    return "";
                }
                let start = index;
                while (start > 0 && /[A-Za-z0-9:/._?&=%#-]/.test(text[start - 1])) {
                    start -= 1;
                }
                let end = index + needle.length;
                while (end < text.length && !/[\\s>)\\]]/.test(text[end])) {
                    end += 1;
                }
                return text.slice(start, end);
            }
        }""",
        chat_id,
    )
    if isinstance(result, dict):
        return result
    return {"content": "", "preview_url": "", "done": False}


def _openwebui_chat_id_from_url(chat_url: str) -> str:
    marker = "/c/"
    if marker not in chat_url:
        return ""
    return chat_url.rsplit(marker, 1)[-1].split("?", 1)[0].strip("/")


def _first_anchor_href(page: Any, needle: str) -> str:
    result = page.evaluate(
        """(needle) => {
            const anchors = Array.from(document.querySelectorAll("a[href]"));
            const match = anchors.find((anchor) => String(anchor.href || "").includes(needle));
            return match ? match.href : "";
        }""",
        needle,
    )
    return str(result or "")


def _merge_openwebui_workflow(
    workflow: dict[str, dict[str, Any]],
    result: dict[str, Any],
    visual: bool,
) -> None:
    _mark_workflow(
        workflow,
        "openwebui_question_asked",
        "erfüllt" if result.get("question_asked") else "nicht erfüllt",
        str(result.get("chat_url") or result.get("reason") or ""),
        automatic=bool(result.get("question_asked")),
        visual=visual,
    )
    _mark_workflow(
        workflow,
        "openwebui_answer_shown",
        "erfüllt" if result.get("answer_visible") else "nicht erfüllt",
        str(result.get("answer_screenshot") or ""),
        automatic=bool(result.get("answer_visible")),
        visual=visual,
    )
    _mark_workflow(
        workflow,
        "openwebui_preview_opened",
        "erfüllt" if result.get("preview_opened") else "nicht erfüllt",
        str(result.get("preview_url") or ""),
        automatic=bool(result.get("preview_opened")),
        visual=visual,
    )
    _mark_workflow(
        workflow,
        "openwebui_original_opened",
        "erfüllt" if result.get("original_opened") else "nicht erfüllt",
        str(result.get("original_url") or ""),
        automatic=bool(result.get("original_opened")),
        visual=visual,
    )


def _mark_workflow(
    workflow: dict[str, dict[str, Any]],
    key: str,
    status: str,
    evidence: str,
    *,
    automatic: bool,
    visual: bool,
) -> None:
    item = workflow.setdefault(
        key,
        {
            "label": key,
            "status": "nicht geprüft",
            "evidence": "",
            "automatic": False,
            "visual": False,
        },
    )
    item.update(
        {
            "status": status,
            "evidence": evidence,
            "automatic": automatic,
            "visual": visual,
        }
    )


def _assert_required_workflow_complete(workflow: dict[str, dict[str, Any]]) -> None:
    missing = [
        label
        for key, label in REQUIRED_WORKFLOW_POINTS
        if workflow.get(key, {}).get("status") != "erfüllt"
    ]
    if missing:
        raise RuntimeError(
            "Demo workflow is incomplete; missing required points: " + ", ".join(missing)
        )


def _extract_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("repos", "repo_list", "libraries"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _repo_id(library: dict[str, Any]) -> str:
    repo_id = str(library.get("id") or library.get("repo_id") or "")
    if not repo_id:
        raise ValueError(f"Seafile library response did not contain a repo id: {library!r}")
    return repo_id


def _extract_chunks(retrieval: dict[str, Any]) -> list[Any]:
    for key in ("chunks", "documents"):
        value = retrieval.get(key)
        if isinstance(value, list):
            return value
    data = retrieval.get("data")
    if isinstance(data, dict):
        value = data.get("chunks") or data.get("documents")
        if isinstance(value, list):
            return value
    return []


def _select_demo_document(documents: list[dict[str, Any]], file_name: str) -> dict[str, Any]:
    for document in documents:
        names = {
            str(document.get(key) or "")
            for key in ("name", "document_name", "doc_name", "display_name")
        }
        if file_name in names:
            return document
    if documents:
        return documents[0]
    return {}


def _document_id(document: dict[str, Any]) -> str | None:
    for key in ("id", "document_id", "doc_id"):
        value = document.get(key)
        if value:
            return str(value)
    return None


def _rewrite_local_service_url(url: str, base_url: str) -> str:
    base = httpx.URL(base_url)
    current = httpx.URL(url)
    if current.host not in {"127.0.0.1", "localhost"}:
        if base.host not in {"127.0.0.1", "localhost"}:
            return url
        if not current.path.startswith("/seafhttp/"):
            return url
    return str(current.copy_with(scheme=base.scheme, host=base.host, port=base.port))


def _seafile_library_url(settings: Any, repo_id: str, library_name: str) -> str:
    base_url = (settings.seafile_public_base_url or settings.seafile_base_url).rstrip("/")
    return f"{base_url}/library/{quote(repo_id, safe='')}/{quote(library_name, safe='')}/"


def _ragflow_dataset_url(base_url: str | None, dataset_id: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/dataset/files/{quote(dataset_id, safe='')}"


def _ragflow_chat_url(base_url: str | None, chat_id: str | None) -> str | None:
    if not base_url or not chat_id:
        return base_url
    return f"{base_url.rstrip('/')}/chat/{quote(chat_id, safe='')}"


def _ragflow_agent_url(base_url: str | None, agent_id: str | None) -> str | None:
    if not base_url or not agent_id:
        return base_url
    return f"{base_url.rstrip('/')}/agent/{quote(agent_id, safe='')}?category=agent_canvas"


def _ragflow_dataflow_url(base_url: str | None, dataset_id: str, document_id: str) -> str | None:
    if not base_url:
        return None
    query = (
        f"knowledgeId={quote(dataset_id, safe='')}"
        f"&doc_id={quote(document_id, safe='')}"
        "&type=dataflow&is_read_only=false"
    )
    return f"{base_url.rstrip('/')}/dataflow-result?{query}"


def _select_ragflow_chunk_stage(pages: dict[str, Any] | None) -> None:
    if pages is None:
        return
    page = pages["ragflow"]
    for label in (
        "Token Chunker",
        "Title Chunker",
        "Chunker",
        "Result",
    ):
        with suppress(Exception):
            locator = page.get_by_text(label, exact=False).last
            if locator.count() > 0:
                locator.click(timeout=3_000)
                page.wait_for_timeout(1_000)
                break
    with suppress(Exception):
        page.mouse.wheel(0, 420)
        page.wait_for_timeout(500)


def _record_marker(recorder: OBSWebhookClient | None, marker: str, demo_id: str) -> None:
    if recorder is not None:
        recorder.add_marker(marker, demo_id=demo_id)


def _start_obs_recording(
    recorder: OBSWebhookClient | None,
    args: argparse.Namespace,
    names: DemoRecordingNames,
    checks: dict[str, Any],
    webhook_payloads: list[Any],
    recording_state: dict[str, Any],
) -> None:
    if recorder is None or recording_state.get("started"):
        return
    recording_state["started_at"] = datetime.now(UTC)
    start_payload = recorder.start_recording(
        recording_name=names.recording_name,
        scene_name=args.scene_name,
        demo_id=names.demo_id,
    )
    webhook_payloads.append(start_payload)
    checks["obs_recording"] = {
        "start": "erfüllt",
        "start_response": start_payload,
    }
    status_after_start = recorder.status()
    if status_after_start is not None:
        webhook_payloads.append(status_after_start)
        checks["obs_recording"]["status_after_start"] = status_after_start
        checks["obs_recording"]["recording_after_start"] = recorder.is_recording()
    recording_state["started"] = True
    recorder.add_marker("demo-start", demo_id=names.demo_id)


def _capture_obs_checkpoint(
    recorder: OBSWebhookClient | None,
    marker: str,
    names: DemoRecordingNames,
    paths: DemoRunPaths,
    args: argparse.Namespace,
    checks: dict[str, Any],
) -> None:
    if recorder is None:
        return
    output_path = paths.run_dir / "obs-screenshots" / f"{_safe_artifact_name(marker)}.png"
    try:
        result = recorder.capture_screenshot(
            output_path,
            marker=marker,
            demo_id=names.demo_id,
            width=args.obs_screenshot_width,
            height=args.obs_screenshot_height,
        )
    except Exception as exc:
        result = {
            "marker": marker,
            "written": False,
            "path": str(output_path),
            "error": str(exc),
        }
    if result is None:
        return
    checks.setdefault("obs_screenshots", []).append(result)


def _safe_artifact_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _paths(output_dir: Path, names: DemoRecordingNames) -> DemoRunPaths:
    run_dir = output_dir / names.demo_id
    return DemoRunPaths(
        run_dir=run_dir,
        demo_file=run_dir / names.file_name,
        summary_file=run_dir / "recording-summary.json",
    )


def _summary_payload(
    names: DemoRecordingNames,
    paths: DemoRunPaths,
    checks: dict[str, Any],
) -> dict[str, Any]:
    return {
        "demo_id": names.demo_id,
        "library_name": names.library_name,
        "dataset_label": names.dataset_label,
        "chat_label": names.chat_label,
        "demo_file": str(paths.demo_file),
        "summary_file": str(paths.summary_file),
        "checks": checks,
        "next_execute_command": (
            "uv run --extra dev python scripts/record_demo_workflow.py "
            f"--demo-id {names.demo_id} --execute --record --headed"
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
