from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from seafile_ragflow_connector.app.logging import configure_logging
from seafile_ragflow_connector.app.runtime import build_runtime
from seafile_ragflow_connector.clients.http import make_client, unwrap_response
from seafile_ragflow_connector.config import get_settings
from seafile_ragflow_connector.demo.recording import (
    DemoRecordingNames,
    OBSWebhookClient,
    OBSWebhookConfig,
    OBSWebhookError,
    build_recording_steps,
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
    recording_started = False
    if args.record:
        recorder = OBSWebhookClient(obs_config)
        recorder.validate()
        recorder.start_recording(
            recording_name=names.recording_name,
            scene_name=args.scene_name,
            demo_id=names.demo_id,
        )
        recording_started = True
        recorder.add_marker("demo-start", demo_id=names.demo_id)

    try:
        checks.update(_execute_workflow(args, names, paths, recorder))
        mode = "execute-recording" if args.record else "execute-no-recording"
        write_recording_summary(
            paths.summary_file,
            names=names,
            mode=mode,
            obs_config=obs_config,
            checks=checks,
        )
        print(json.dumps(_summary_payload(names, paths, checks), ensure_ascii=False, indent=2))
        return 0
    finally:
        if recorder is not None:
            try:
                if recording_started:
                    recorder.add_marker("demo-stop", demo_id=names.demo_id)
                    recorder.stop_recording(demo_id=names.demo_id)
            finally:
                recorder.close()


def _execute_workflow(
    args: argparse.Namespace,
    names: DemoRecordingNames,
    paths: DemoRunPaths,
    recorder: OBSWebhookClient | None,
) -> dict[str, Any]:
    settings = get_settings()
    runtime = build_runtime(settings)
    try:
        pages = _open_browser_pages(args, settings) if not args.skip_browser else None
        try:
            seafile_url = settings.seafile_public_base_url or settings.seafile_base_url
            _show_pages(pages, "seafile", seafile_url)
            repo_id = _ensure_seafile_library(settings, names.library_name)
            _record_marker(recorder, "seafile-library-created", names.demo_id)
            _pause(args.pause_seconds)

            runtime.orchestrator.discover_libraries()
            dataset_id = runtime.orchestrator.ensure_dataset_for_repo(repo_id)
            dataset_name = _dataset_name(runtime.orchestrator.session_factory, repo_id)
            ragflow_url = settings.ragflow_public_base_url or settings.ragflow_base_url
            _show_pages(pages, "ragflow", ragflow_url)
            _record_marker(recorder, "ragflow-dataset-created", names.demo_id)
            _pause(args.pause_seconds)

            if runtime.openwebui_sync_service is not None:
                runtime.openwebui_sync_service.sync_once(repo_ids={repo_id})
            mapping = _openwebui_mapping(runtime.orchestrator.session_factory, repo_id)
            _record_marker(recorder, "ragflow-chat-openwebui-pipe-created", names.demo_id)
            _pause(args.pause_seconds)

            _upload_file(settings, repo_id, paths.demo_file)
            _record_marker(recorder, "seafile-file-uploaded", names.demo_id)
            _pause(args.pause_seconds)

            sync_summary = runtime.orchestrator.sync_library_full(repo_id)
            _wait_for_parse(
                runtime.ragflow_client.list_documents,
                dataset_id,
                args.wait_parse_seconds,
            )
            documents = runtime.ragflow_client.list_documents(dataset_id)
            retrieval = runtime.ragflow_client.retrieve_chunks(
                dataset_id=dataset_id,
                question=names.question,
                top_k=5,
                page_size=5,
            )
            _show_pages(pages, "openwebui", settings.openwebui_base_url)
            _record_marker(recorder, "openwebui-question-ready", names.demo_id)
            _pause(args.pause_seconds)

            return {
                "seafile_repo_id": repo_id,
                "ragflow_dataset_id": dataset_id,
                "ragflow_dataset_name": dataset_name,
                "openwebui_pipe_id": mapping.openwebui_pipe_id if mapping else None,
                "ragflow_chat_id": mapping.ragflow_chat_id if mapping else None,
                "files_uploaded": sync_summary.files_uploaded,
                "documents_visible": len(documents),
                "retrieval_chunks_visible": len(_extract_chunks(retrieval)),
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


def _ensure_seafile_library(settings: Any, library_name: str) -> str:
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
                return _repo_id(library)
        created = unwrap_response(sync_client.post("/api2/repos/", data={"name": library_name}))
        if not isinstance(created, dict):
            raise TypeError(f"unexpected Seafile create response for {library_name}")
        return _repo_id(created)
    finally:
        admin_client.close()
        sync_client.close()


def _upload_file(settings: Any, repo_id: str, path: Path) -> None:
    client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        upload_link = unwrap_response(
            client.get(
                f"/api2/repos/{repo_id}/upload-link/",
                params={"p": "/"},
            )
        )
        if not isinstance(upload_link, str):
            raise TypeError(f"unexpected Seafile upload-link response for {repo_id}")
        with path.open("rb") as handle:
            response = httpx.post(
                _rewrite_local_service_url(
                    upload_link.strip().strip('"'),
                    settings.seafile_base_url,
                ),
                headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
                data={"parent_dir": "/", "replace": "1"},
                files={"file": (path.name, handle, "text/markdown")},
                timeout=120.0,
                verify=settings.seafile_httpx_verify,
            )
        unwrap_response(response)
    finally:
        client.close()


def _wait_for_parse(
    list_documents: Callable[[str], list[dict[str, Any]]],
    dataset_id: str,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        documents = list_documents(dataset_id)
        active = any(
            str(doc.get("run") or "").upper() in {"RUNNING", "UNSTART"}
            for doc in documents
        )
        if documents and not active:
            return
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
    if args.profile_dir:
        context = browser_type.launch_persistent_context(
            user_data_dir=str(args.profile_dir),
            headless=not args.headed,
            viewport={"width": 1440, "height": 1000},
        )
        browser = None
    else:
        browser = browser_type.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
    pages = {
        "seafile": context.new_page(),
        "ragflow": context.new_page(),
        "openwebui": context.new_page(),
        "close": lambda: _close_playwright(context, browser, playwright),
    }
    _show_pages(pages, "seafile", settings.seafile_public_base_url or settings.seafile_base_url)
    return pages


def _show_pages(pages: dict[str, Any] | None, name: str, url: str | None) -> None:
    if pages is None or not url:
        return
    page = pages[name]
    page.bring_to_front()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)


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


def _rewrite_local_service_url(url: str, base_url: str) -> str:
    if not (url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
        return url
    base = httpx.URL(base_url)
    current = httpx.URL(url)
    return str(current.copy_with(scheme=base.scheme, host=base.host, port=base.port))


def _record_marker(recorder: OBSWebhookClient | None, marker: str, demo_id: str) -> None:
    if recorder is not None:
        recorder.add_marker(marker, demo_id=demo_id)


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
