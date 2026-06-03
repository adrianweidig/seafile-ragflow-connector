from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import select

from seafile_ragflow_connector.clients.http import (
    ApiError,
    make_client,
    unwrap_response,
)
from seafile_ragflow_connector.clients.openwebui import OpenWebUIClient
from seafile_ragflow_connector.clients.ragflow import RAGFlowClient
from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.demo.fixtures import (
    CANONICAL_DEMO_LIBRARIES as CANONICAL_DEMO_LIBRARIES,
)
from seafile_ragflow_connector.demo.fixtures import (
    _mime_for_path,
)
from seafile_ragflow_connector.demo.fixtures import (
    write_demo_testset as write_demo_testset,
)
from seafile_ragflow_connector.persistence.db import get_session_factory
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping

SAFE_SEAFILE_LIBRARY_PREFIXES = (
    "Connector Demo ",
    "Demo OBS Seafile RAGFlow OpenWebUI ",
    "Demo RAGFlow OpenWebUI Bibliothek ",
    "RAG Demo Bibliothek ",
    "Offline Demo Bibliothek ",
    "Codex GIF Demo ",
)
SAFE_RAGFLOW_DATASET_PREFIXES = (
    "RAG_connector_demo_",
    "RAG_demo_obs_seafile_ragflow_openwebui_",
    "RAG_demo_ragflow_openwebui_bibliothek_",
    "RAG_rag_demo_bibliothek_",
    "RAG_offline_demo_bibliothek_",
    "RAG_codex_gif_demo_",
    "seafile__connector-demo-",
    "seafile__demo-obs-seafile-ragflow-openwebui-",
    "seafile__demo-ragflow-openwebui-bibliothek-",
    "seafile__rag-demo-bibliothek-",
    "seafile__offline-demo-bibliothek-",
    "seafile__codex-gif-demo-",
)
SAFE_OPENWEBUI_ARTIFACT_MARKERS = (
    "_connector_demo_",
    "_demo_obs_seafile_ragflow_openwebui_",
    "_demo_ragflow_openwebui_bibliothek_",
    "_rag_demo_bibliothek_",
    "_offline_demo_bibliothek_",
    "_codex_gif_demo_",
)




def is_safe_demo_library_name(name: str | None) -> bool:
    value = str(name or "")
    return any(value.startswith(prefix) for prefix in SAFE_SEAFILE_LIBRARY_PREFIXES)


def is_safe_demo_dataset_name(name: str | None) -> bool:
    value = str(name or "")
    return any(value.startswith(prefix) for prefix in SAFE_RAGFLOW_DATASET_PREFIXES)


def is_safe_demo_openwebui_artifact(value: str | None) -> bool:
    normalized = str(value or "").lower().replace("-", "_")
    return any(marker in normalized for marker in SAFE_OPENWEBUI_ARTIFACT_MARKERS)




def build_cleanup_plan(settings: Settings) -> dict[str, Any]:
    inventory = _collect_inventory(settings)
    plan = {
        "seafile_libraries": [
            item
            for item in inventory["seafile_libraries"]
            if is_safe_demo_library_name(str(item.get("name") or ""))
        ],
        "ragflow_datasets": [
            item
            for item in inventory["ragflow_datasets"]
            if is_safe_demo_dataset_name(str(item.get("name") or ""))
        ],
        "ragflow_chats": [
            item
            for item in inventory["ragflow_chats"]
            if is_safe_demo_openwebui_artifact(str(item.get("name") or ""))
        ],
        "openwebui_tools": [
            item
            for item in inventory["openwebui_tools"]
            if item.get("owned") and is_safe_demo_openwebui_artifact(_artifact_identity(item))
        ],
        "openwebui_functions": [
            item
            for item in inventory["openwebui_functions"]
            if item.get("owned") and is_safe_demo_openwebui_artifact(_artifact_identity(item))
        ],
        "connector_libraries": [
            item
            for item in inventory["connector_libraries"]
            if is_safe_demo_library_name(str(item.get("name") or ""))
            or is_safe_demo_dataset_name(str(item.get("ragflow_dataset_name") or ""))
        ],
        "connector_mappings": [
            item
            for item in inventory["connector_mappings"]
            if is_safe_demo_dataset_name(str(item.get("dataset_name") or ""))
            or is_safe_demo_openwebui_artifact(str(item.get("tool_id") or ""))
            or is_safe_demo_openwebui_artifact(str(item.get("pipe_id") or ""))
        ],
    }
    return {"inventory": inventory, "plan": plan}


def cleanup_demo_environment(settings: Settings, *, execute: bool = False) -> dict[str, Any]:
    planned = build_cleanup_plan(settings)
    plan: dict[str, list[dict[str, Any]]] = planned["plan"]
    result: dict[str, Any] = {
        "mode": "execute" if execute else "dry-run",
        "plan": plan,
        "deleted": {
            "seafile_libraries": [],
            "ragflow_datasets": [],
            "ragflow_chats": [],
            "openwebui_tools": [],
            "openwebui_functions": [],
            "connector_libraries": [],
            "connector_mappings": [],
        },
        "errors": [],
    }
    if not execute:
        return result

    _delete_openwebui_artifacts(settings, plan, result)
    _delete_ragflow_objects(settings, plan, result)
    _delete_seafile_libraries(settings, plan, result)
    _delete_connector_state(settings, plan, result)
    return result


def bootstrap_demo_environment(
    settings: Settings,
    *,
    output_dir: Path,
    execute: bool = False,
) -> dict[str, Any]:
    fixtures = write_demo_testset(output_dir)
    result: dict[str, Any] = {
        "mode": "execute" if execute else "dry-run",
        "fixtures": fixtures,
        "libraries": [],
        "uploads": [],
        "errors": [],
    }
    if not execute:
        return result

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
        existing = _seafile_libraries_by_name(admin_client)
        for library_name, files in fixtures.items():
            library = existing.get(library_name) or _create_seafile_library(
                sync_client,
                library_name,
            )
            repo_id = str(library.get("id") or library.get("repo_id"))
            result["libraries"].append(
                {
                    "name": library_name,
                    "repo_id": repo_id,
                    "created": library_name not in existing,
                }
            )
            for file_name in files:
                path = Path(file_name)
                try:
                    _upload_file(sync_client, settings, repo_id, path, _mime_for_path(path))
                    result["uploads"].append(
                        {"library": library_name, "repo_id": repo_id, "file": path.name}
                    )
                except Exception as exc:
                    result["errors"].append(
                        {
                            "scope": "seafile_upload",
                            "library": library_name,
                            "file": path.name,
                            "error": str(exc),
                        }
                    )
    finally:
        admin_client.close()
        sync_client.close()
    return result


def _collect_inventory(settings: Settings) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, list[dict[str, Any]]] = {
        "seafile_libraries": [],
        "ragflow_datasets": [],
        "ragflow_chats": [],
        "openwebui_tools": [],
        "openwebui_functions": [],
        "connector_libraries": [],
        "connector_mappings": [],
    }
    _collect_connector_inventory(settings, inventory)
    _collect_seafile_inventory(settings, inventory)
    _collect_ragflow_inventory(settings, inventory)
    _collect_openwebui_inventory(settings, inventory)
    return inventory


def _collect_connector_inventory(
    settings: Settings, inventory: dict[str, list[dict[str, Any]]]
) -> None:
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as session:
        for library in session.scalars(select(Library).order_by(Library.name.asc())):
            inventory["connector_libraries"].append(
                {
                    "repo_id": library.repo_id,
                    "name": library.name,
                    "status": library.status,
                    "ragflow_dataset_id": library.ragflow_dataset_id,
                    "ragflow_dataset_name": library.ragflow_dataset_name,
                }
            )
        for mapping in session.scalars(select(OpenWebUIDatasetMapping)):
            inventory["connector_mappings"].append(
                {
                    "id": mapping.id,
                    "repo_id": mapping.repo_id,
                    "dataset_id": mapping.ragflow_dataset_id,
                    "dataset_name": mapping.ragflow_dataset_name,
                    "chat_id": mapping.ragflow_chat_id,
                    "tool_id": mapping.openwebui_tool_id,
                    "pipe_id": mapping.openwebui_pipe_id,
                    "artifact_version": mapping.artifact_version,
                    "status": mapping.sync_status,
                }
            )


def _collect_seafile_inventory(
    settings: Settings, inventory: dict[str, list[dict[str, Any]]]
) -> None:
    client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_admin_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        data = unwrap_response(client.get("/api/v2.1/admin/libraries/", params={"per_page": 500}))
        libraries = _extract_list(data, "repos", "repo_list", "libraries")
        for item in libraries:
            inventory["seafile_libraries"].append(
                {
                    "id": item.get("id") or item.get("repo_id"),
                    "name": item.get("name") or item.get("repo_name"),
                    "owner": item.get("owner") or item.get("owner_email"),
                    "file_count": item.get("file_count"),
                }
            )
    finally:
        client.close()


def _collect_ragflow_inventory(
    settings: Settings, inventory: dict[str, list[dict[str, Any]]]
) -> None:
    client = RAGFlowClient(
        settings.ragflow_internal_url or settings.ragflow_base_url,
        settings.ragflow_api_key,
        timeout=120.0,
        verify=settings.ragflow_httpx_verify,
    )
    try:
        for item in client.list_datasets():
            inventory["ragflow_datasets"].append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "document_count": item.get("document_count") or item.get("doc_num"),
                }
            )
        for item in client.list_chats():
            inventory["ragflow_chats"].append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "dataset_ids": item.get("dataset_ids") or item.get("datasets"),
                }
            )
    finally:
        client.close()


def _collect_openwebui_inventory(
    settings: Settings, inventory: dict[str, list[dict[str, Any]]]
) -> None:
    if settings.openwebui_effective_sync_mode == "disabled" or not settings.openwebui_admin_api_key:
        return
    client = OpenWebUIClient(
        settings.openwebui_base_url,
        settings.openwebui_admin_api_key,
        timeout=settings.openwebui_request_timeout_seconds,
        verify=settings.openwebui_httpx_verify,
    )
    try:
        for item in client.list_tools():
            inventory["openwebui_tools"].append(_openwebui_artifact_summary(item))
        for item in client.list_functions():
            inventory["openwebui_functions"].append(_openwebui_artifact_summary(item))
    finally:
        client.close()


def _delete_openwebui_artifacts(
    settings: Settings,
    plan: dict[str, list[dict[str, Any]]],
    result: dict[str, Any],
) -> None:
    if settings.openwebui_effective_sync_mode == "disabled" or not settings.openwebui_admin_api_key:
        return
    client = OpenWebUIClient(
        settings.openwebui_base_url,
        settings.openwebui_admin_api_key,
        timeout=settings.openwebui_request_timeout_seconds,
        verify=settings.openwebui_httpx_verify,
    )
    try:
        for tool in plan["openwebui_tools"]:
            artifact_id = str(tool.get("id") or "")
            _delete_one(
                result,
                "openwebui_tools",
                artifact_id,
                lambda artifact_id=artifact_id: client.delete_tool(artifact_id),
            )
        for function in plan["openwebui_functions"]:
            artifact_id = str(function.get("id") or "")
            _delete_one(
                result,
                "openwebui_functions",
                artifact_id,
                lambda artifact_id=artifact_id: client.delete_function(artifact_id),
            )
    finally:
        client.close()


def _delete_ragflow_objects(
    settings: Settings,
    plan: dict[str, list[dict[str, Any]]],
    result: dict[str, Any],
) -> None:
    client = RAGFlowClient(
        settings.ragflow_internal_url or settings.ragflow_base_url,
        settings.ragflow_api_key,
        timeout=120.0,
        verify=settings.ragflow_httpx_verify,
    )
    try:
        chat_ids = [str(item.get("id")) for item in plan["ragflow_chats"] if item.get("id")]
        dataset_ids = [str(item.get("id")) for item in plan["ragflow_datasets"] if item.get("id")]
        if chat_ids:
            _delete_one(
                result,
                "ragflow_chats",
                ",".join(chat_ids),
                lambda: client.delete_chats(chat_ids),
                reported=chat_ids,
            )
        if dataset_ids:
            _delete_one(
                result,
                "ragflow_datasets",
                ",".join(dataset_ids),
                lambda: client.delete_datasets(dataset_ids),
                reported=dataset_ids,
            )
    finally:
        client.close()


def _delete_seafile_libraries(
    settings: Settings,
    plan: dict[str, list[dict[str, Any]]],
    result: dict[str, Any],
) -> None:
    client = make_client(
        settings.seafile_base_url,
        headers={"Authorization": f"Token {settings.seafile_admin_token}"},
        timeout=120.0,
        verify=settings.seafile_httpx_verify,
    )
    try:
        for library in plan["seafile_libraries"]:
            repo_id = str(library.get("id") or "")
            if not repo_id:
                continue
            _delete_one(
                result,
                "seafile_libraries",
                repo_id,
                lambda repo_id=repo_id: _delete_seafile_library(client, repo_id),
            )
    finally:
        client.close()


def _delete_connector_state(
    settings: Settings,
    plan: dict[str, list[dict[str, Any]]],
    result: dict[str, Any],
) -> None:
    mapping_ids = {int(item["id"]) for item in plan["connector_mappings"] if item.get("id")}
    repo_ids = {str(item["repo_id"]) for item in plan["connector_libraries"] if item.get("repo_id")}
    session_factory = get_session_factory(settings.database_url)
    with session_factory() as session:
        for mapping_id in sorted(mapping_ids):
            mapping = session.get(OpenWebUIDatasetMapping, mapping_id)
            if mapping is not None:
                session.delete(mapping)
                result["deleted"]["connector_mappings"].append(mapping_id)
        for repo_id in sorted(repo_ids):
            library = session.get(Library, repo_id)
            if library is not None:
                session.delete(library)
                result["deleted"]["connector_libraries"].append(repo_id)
        session.commit()


def _delete_one(
    result: dict[str, Any],
    category: str,
    identity: str,
    operation: Any,
    *,
    reported: list[str] | None = None,
) -> None:
    try:
        operation()
        result["deleted"][category].extend(reported or [identity])
    except Exception as exc:
        result["errors"].append({"scope": category, "id": identity, "error": str(exc)})


def _delete_seafile_library(client: httpx.Client, repo_id: str) -> None:
    try:
        unwrap_response(client.delete(f"/api/v2.1/admin/libraries/{repo_id}/"))
    except ApiError as exc:
        if exc.status_code == 404:
            return
        raise


def _seafile_libraries_by_name(client: httpx.Client) -> dict[str, dict[str, Any]]:
    data = unwrap_response(client.get("/api/v2.1/admin/libraries/", params={"per_page": 500}))
    result: dict[str, dict[str, Any]] = {}
    for item in _extract_list(data, "repos", "repo_list", "libraries"):
        name = str(item.get("name") or item.get("repo_name") or "")
        if name:
            result[name] = item
    return result


def _create_seafile_library(client: httpx.Client, name: str) -> dict[str, Any]:
    data = unwrap_response(client.post("/api2/repos/", data={"name": name}))
    if isinstance(data, dict):
        return data
    msg = f"unexpected Seafile library create response for {name}"
    raise TypeError(msg)


def _upload_file(
    client: httpx.Client,
    settings: Settings,
    repo_id: str,
    path: Path,
    mime_type: str,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            upload_link = unwrap_response(
                client.get(f"/api2/repos/{repo_id}/upload-link/", params={"p": "/"})
            )
            if not isinstance(upload_link, str):
                msg = f"unexpected Seafile upload-link response for {repo_id}"
                raise TypeError(msg)
            with path.open("rb") as handle:
                response = httpx.post(
                    _rewrite_seafile_service_url(upload_link.strip().strip('"'), settings),
                    headers={"Authorization": f"Token {settings.seafile_sync_user_token}"},
                    data={"parent_dir": "/", "replace": "1"},
                    files={"file": (path.name, handle, mime_type)},
                    timeout=120.0,
                    verify=settings.seafile_httpx_verify,
                )
            unwrap_response(response)
            return
        except ApiError as exc:
            last_error = exc
            if exc.status_code not in {429, 502, 503, 504}:
                raise
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(min(2 * attempt, 10))
    if last_error:
        raise last_error


def _openwebui_artifact_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "is_active": item.get("is_active"),
        "owned": _is_connector_owned(item),
    }


def _is_connector_owned(item: dict[str, Any]) -> bool:
    meta = item.get("meta")
    manifest = meta.get("manifest") if isinstance(meta, dict) else None
    return (
        isinstance(manifest, dict)
        and manifest.get("owner") == "seafile-ragflow-connector"
    ) or "seafile-ragflow-connector" in str(item.get("content") or "")


def _artifact_identity(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("id", "name"))


def _extract_list(data: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []




def dumps_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)


def _rewrite_seafile_service_url(url: str, settings: Settings) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return url
    base = urlparse(settings.seafile_base_url)
    return urlunparse(
        (
            base.scheme,
            base.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
