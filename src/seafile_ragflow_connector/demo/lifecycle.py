from __future__ import annotations

import csv
import json
import time
import zipfile
from dataclasses import dataclass
from html import escape
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
from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.persistence.db import get_session_factory
from seafile_ragflow_connector.persistence.models.library import Library
from seafile_ragflow_connector.persistence.models.openwebui import OpenWebUIDatasetMapping

CANONICAL_DEMO_LIBRARIES = (
    "Connector Demo Wissen",
    "Connector Demo Präsentationen",
    "Connector Demo Edge Cases",
)
SAFE_SEAFILE_LIBRARY_PREFIXES = (
    "Connector Demo ",
    "RAG Demo Bibliothek ",
    "Offline Demo Bibliothek ",
    "Codex GIF Demo ",
)
SAFE_RAGFLOW_DATASET_PREFIXES = (
    "seafile__connector-demo-",
    "seafile__rag-demo-bibliothek-",
    "seafile__offline-demo-bibliothek-",
    "seafile__codex-gif-demo-",
)
SAFE_OPENWEBUI_ARTIFACT_MARKERS = (
    "_connector_demo_",
    "_rag_demo_bibliothek_",
    "_offline_demo_bibliothek_",
    "_codex_gif_demo_",
)
_CONTENT_TYPES_OPEN = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
)
_RELATIONSHIPS_OPEN = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">'
)
_DEFAULT_RELS_TYPE = (
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
)
_DEFAULT_XML_TYPE = '<Default Extension="xml" ContentType="application/xml"/>'
_OFFICE_DOCUMENT_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" '
)
_SLIDE_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/slide" '
)
_WORKSHEET_REL = (
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/worksheet" '
)


@dataclass(frozen=True)
class DemoFileSpec:
    library_name: str
    relative_path: str
    mime_type: str
    kind: str


DEMO_FILE_SPECS = (
    DemoFileSpec(
        "Connector Demo Wissen",
        "wissen_mehrseitig.pdf",
        "application/pdf",
        "knowledge_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Wissen",
        "prozesshandbuch.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "knowledge_docx",
    ),
    DemoFileSpec("Connector Demo Wissen", "kurznotiz.txt", "text/plain", "knowledge_txt"),
    DemoFileSpec("Connector Demo Wissen", "integration.md", "text/markdown", "knowledge_md"),
    DemoFileSpec("Connector Demo Wissen", "kennzahlen.csv", "text/csv", "knowledge_csv"),
    DemoFileSpec(
        "Connector Demo Wissen",
        "kennzahlen.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "knowledge_xlsx",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "foliennummern.pdf",
        "application/pdf",
        "presentation_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "quartalsdemo.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "presentation_pptx",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "tabelle_im_pdf.pdf",
        "application/pdf",
        "table_pdf",
    ),
    DemoFileSpec(
        "Connector Demo Präsentationen",
        "ocr_hinweis.pdf",
        "application/pdf",
        "ocr_pdf",
    ),
    DemoFileSpec("Connector Demo Edge Cases", "umlaute_aeoeuess.txt", "text/plain", "umlauts"),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "html_fragmente.md",
        "text/markdown",
        "html_fragments",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "tabellenzellen.csv",
        "text/csv",
        "edge_table",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "aehnlicher_inhalt_a.txt",
        "text/plain",
        "duplicate_a",
    ),
    DemoFileSpec(
        "Connector Demo Edge Cases",
        "aehnlicher_inhalt_b.txt",
        "text/plain",
        "duplicate_b",
    ),
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


def write_demo_testset(root: Path) -> dict[str, list[str]]:
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, list[str]] = {name: [] for name in CANONICAL_DEMO_LIBRARIES}
    for spec in DEMO_FILE_SPECS:
        library_dir = root / slugify(spec.library_name, fallback="library")
        library_dir.mkdir(parents=True, exist_ok=True)
        target = library_dir / spec.relative_path
        _write_demo_file(target, spec.kind)
        result[spec.library_name].append(str(target))
    return result


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


def _write_demo_file(path: Path, kind: str) -> None:
    if kind == "knowledge_pdf":
        _write_pdf(
            path,
            [
                "Connector Demo Wissen - Seite 1\nÜberblick: Seafile ist die Quelle der Wahrheit.",
                "Connector Demo Wissen - Seite 2\nRAGFlow erhält Datasets aus connector_template.",
                "Connector Demo Wissen - Seite 3\nOpenWebUI zeigt kompakte Quellen mit Auszug.",
                "Connector Demo Wissen - Seite 4\nTOP_K steuert die Anzahl relevanter Treffer.",
                "Connector Demo Wissen - Seite 5\n"
                "Originaldokumente können per Link geöffnet werden.",
                "Connector Demo Wissen - Seite 6\nPreview läuft lokal und ohne CDN.",
                "Connector Demo Wissen - Seite 7\nPDF-Seitenanker sollen #page=7 erzeugen.",
            ],
        )
    elif kind == "knowledge_docx":
        _write_docx(
            path,
            [
                "Abschnitt Betrieb: Der Connector synchronisiert nur von Seafile zu RAGFlow.",
                "Tabelle: System | Zweck | Status",
                "Aufzählung: Discovery, Upload, Parse, OpenWebUI-Sync.",
            ],
        )
    elif kind == "knowledge_txt":
        path.write_text(
            "Kurzer Fließtext für die normale Wissensabfrage. "
            "Die Demo prüft Quellen, Preview und Original-Link.\n",
            encoding="utf-8",
        )
    elif kind == "knowledge_md":
        path.write_text(
            "# Integration\n\n- Seafile bleibt Quelle der Wahrheit.\n"
            "- RAGFlow speichert Datasets und Chunks.\n\n"
            "```text\nTOP_K=8\n```\n",
            encoding="utf-8",
        )
    elif kind == "knowledge_csv":
        _write_csv(path, [["Metrik", "Wert"], ["TOP_K", "8"], ["Preview", "lokal"]])
    elif kind == "knowledge_xlsx":
        _write_xlsx(path, [["Metrik", "Wert"], ["TOP_K", "8"], ["Preview", "lokal"]])
    elif kind == "presentation_pdf":
        _write_pdf(
            path,
            [
                f"Connector Demo Präsentationen - Folie {index}\n"
                f"Foliennummer {index}: Quellenangabe und Preview prüfen."
                for index in range(1, 8)
            ],
        )
    elif kind == "presentation_pptx":
        _write_pptx(
            path,
            [
                "Folie 1: Connector Demo Präsentationen",
                "Folie 2: Quellen, Preview und Seitenanker",
            ],
        )
    elif kind == "table_pdf":
        _write_pdf(
            path,
            [
                "PDF mit eingebetteter Tabelle\nSpalte A | Spalte B\nAlpha | 10\nBeta | 20",
                "Tabellenhinweis\nZellen sollen als lesbarer Text erscheinen.",
            ],
        )
    elif kind == "ocr_pdf":
        _write_pdf(
            path,
            [
                "OCR-Hinweis\nDiese Seite simuliert OCR-relevanten Inhalt und macht "
                "Parsingqualität sichtbar.",
            ],
        )
    elif kind == "umlauts":
        path.write_text(
            "Umlaute-Test: ä, ö, ü, Ä, Ö, Ü und ß müssen lesbar bleiben.\n",
            encoding="utf-8",
        )
    elif kind == "html_fragments":
        path.write_text(
            "# HTML-Fragmente\n\n"
            "Dieser Text enthält <table><tr><td>Alpha</td><td>Beta</td></tr></table> "
            "und &uuml;bernommene Entities. Tags dürfen nicht roh erscheinen.\n",
            encoding="utf-8",
        )
    elif kind == "edge_table":
        _write_csv(path, [["Schlüssel", "Wert"], ["HTML", "<td>Alpha</td>"], ["Entity", "&uuml;"]])
    elif kind == "duplicate_a":
        path.write_text(
            "Ähnlicher Inhalt: Der Connector nutzt Quellenranking und Deduplizierung.",
            encoding="utf-8",
        )
    elif kind == "duplicate_b":
        path.write_text(
            "Ähnlicher Inhalt: Der Connector nutzt Quellenranking und Deduplizierung "
            "mit zweiter Datei.",
            encoding="utf-8",
        )
    else:
        msg = f"unknown demo file kind: {kind}"
        raise ValueError(msg)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _write_pdf(path: Path, pages: list[str]) -> None:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    for index, text in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        stream = _pdf_stream(text)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
                f"/BaseFont /Helvetica >> >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
    _write_pdf_objects(path, objects)


def _pdf_stream(text: str) -> bytes:
    lines = text.splitlines() or [text]
    commands = ["BT", "/F1 14 Tf", "72 760 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -24 Td")
        commands.append(f"({_pdf_escape(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", "replace")


def _pdf_escape(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace(
        "(", "\\("
    ).replace(")", "\\)")


def _write_pdf_objects(path: Path, objects: list[bytes]) -> None:
    offsets = [0]
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(body))


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    _write_zip(
        path,
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_CONTENT_TYPES_OPEN}"
                f"{_DEFAULT_RELS_TYPE}"
                f"{_DEFAULT_XML_TYPE}"
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_OFFICE_DOCUMENT_REL}"
                'Target="word/document.xml"/>'
                "</Relationships>"
            ),
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}<w:sectPr/></w:body></w:document>"
            ),
        },
    )


def _write_xlsx(path: Path, rows: list[list[str]]) -> None:
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{chr(64 + col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    _write_zip(
        path,
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_CONTENT_TYPES_OPEN}"
                f"{_DEFAULT_RELS_TYPE}"
                f"{_DEFAULT_XML_TYPE}"
                '<Override PartName="/xl/workbook.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_OFFICE_DOCUMENT_REL}"
                'Target="xl/workbook.xml"/>'
                "</Relationships>"
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Demo" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"{_RELATIONSHIPS_OPEN}"
                '<Relationship Id="rId1" '
                f"{_WORKSHEET_REL}"
                'Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
            "xl/worksheets/sheet1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
            ),
        },
    )


def _write_pptx(path: Path, slides: list[str]) -> None:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for index in range(1, len(slides) + 1)
    )
    slide_ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{index}"/>'
        for index in range(1, len(slides) + 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{index}" '
        f"{_SLIDE_REL}"
        f'Target="slides/slide{index}.xml"/>'
        for index in range(1, len(slides) + 1)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_CONTENT_TYPES_OPEN}"
            f"{_DEFAULT_RELS_TYPE}"
            f"{_DEFAULT_XML_TYPE}"
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.presentation.main+xml"/>'
            f"{slide_overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_RELATIONSHIPS_OPEN}"
            '<Relationship Id="rId1" '
            f"{_OFFICE_DOCUMENT_REL}"
            'Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{slide_ids}</p:sldIdLst></p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"{_RELATIONSHIPS_OPEN}{rels}</Relationships>"
        ),
    }
    for index, title in enumerate(slides, start=1):
        files[f"ppt/slides/slide{index}.xml"] = _slide_xml(title)
    _write_zip(path, files)


def _slide_xml(title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/>"
        "<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>"
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Titel"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="914400" y="914400"/>'
        '<a:ext cx="8229600" cy="1371600"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>'
        f"{escape(title)}"
        "</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))


def _mime_for_path(path: Path) -> str:
    for spec in DEMO_FILE_SPECS:
        if spec.relative_path == path.name:
            return spec.mime_type
    return "application/octet-stream"


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
