from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

OBSAction = Literal["status", "start", "stop", "screenshot", "scene", "marker"]

_SAFE_DEMO_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_ACTION_ENV_NAMES: dict[OBSAction, str] = {
    "status": "OBS_WEBHOOK_STATUS_URL",
    "start": "OBS_WEBHOOK_START_URL",
    "stop": "OBS_WEBHOOK_STOP_URL",
    "screenshot": "OBS_WEBHOOK_SCREENSHOT_URL",
    "scene": "OBS_WEBHOOK_SCENE_URL",
    "marker": "OBS_WEBHOOK_MARKER_URL",
}
_REQUIRED_OBS_ACTIONS: tuple[OBSAction, ...] = ("start", "stop")
_RECORDING_PATH_KEYS = {
    "file",
    "filename",
    "last_recording",
    "last_recording_path",
    "output",
    "output_file",
    "output_path",
    "path",
    "recording",
    "recording_file",
    "recording_path",
    "saved_file",
    "saved_path",
}
REQUIRED_WORKFLOW_POINTS: tuple[tuple[str, str], ...] = (
    ("seafile_library_created", "Seafile-Bibliothek erstellt"),
    ("seafile_empty_library_shown", "leere Bibliothek gezeigt"),
    ("ragflow_dataset_created", "RAGFlow-Dataset erstellt"),
    ("ragflow_chat_created", "RAGFlow-Chat beziehungsweise Assistant erstellt"),
    ("file_uploaded_after_chat", "Datei erst danach hochgeladen"),
    ("ragflow_sync_shown", "RAGFlow-Synchronisation gezeigt"),
    ("ragflow_parsing_shown", "RAGFlow-Parsing gezeigt"),
    ("ragflow_chunks_shown", "RAGFlow-Chunks gezeigt"),
    ("openwebui_pipe_shown", "OpenWebUI-Pipe gezeigt"),
    ("openwebui_question_asked", "Frage gestellt"),
    ("openwebui_answer_shown", "Antwort gezeigt"),
    ("openwebui_preview_opened", "Preview geöffnet"),
    ("openwebui_original_opened", "Originaldatei geöffnet"),
)


class OBSWebhookError(RuntimeError):
    """Raised when an OBS webhook endpoint is missing or rejects a request."""


@dataclass(frozen=True)
class OBSWebhookConfig:
    status_url: str | None = None
    start_url: str | None = None
    stop_url: str | None = None
    screenshot_url: str | None = None
    scene_url: str | None = None
    marker_url: str | None = None
    token: str | None = None
    token_header: str = "Authorization"
    token_scheme: str = "Bearer"
    payload_mode: Literal["json", "none"] = "json"
    timeout_seconds: float = 20.0
    recording_output_dir: str | None = None
    expected_extension: str = ".mkv"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> OBSWebhookConfig:
        values = environ or dict(os.environ)
        payload_mode = values.get("OBS_WEBHOOK_PAYLOAD_MODE", "json").strip().lower()
        if payload_mode not in {"json", "none"}:
            payload_mode = "json"
        timeout = _float_env(values.get("OBS_WEBHOOK_TIMEOUT_SECONDS"), default=20.0)
        expected_extension = _normalize_extension(
            _clean_env(values.get("OBS_RECORDING_EXPECTED_EXTENSION"))
            or _clean_env(values.get("OBS_RECORDING_FORMAT"))
            or ".mkv"
        )
        return cls(
            status_url=_clean_env(values.get("OBS_WEBHOOK_STATUS_URL")),
            start_url=_clean_env(values.get("OBS_WEBHOOK_START_URL")),
            stop_url=_clean_env(values.get("OBS_WEBHOOK_STOP_URL")),
            screenshot_url=_clean_env(values.get("OBS_WEBHOOK_SCREENSHOT_URL")),
            scene_url=_clean_env(values.get("OBS_WEBHOOK_SCENE_URL")),
            marker_url=_clean_env(values.get("OBS_WEBHOOK_MARKER_URL")),
            token=_clean_env(values.get("OBS_WEBHOOK_TOKEN")),
            token_header=_clean_env(values.get("OBS_WEBHOOK_TOKEN_HEADER")) or "Authorization",
            token_scheme=_clean_env(values.get("OBS_WEBHOOK_TOKEN_SCHEME")) or "Bearer",
            payload_mode=payload_mode,  # type: ignore[arg-type]
            timeout_seconds=timeout,
            recording_output_dir=_clean_env(values.get("OBS_RECORDING_OUTPUT_DIR")),
            expected_extension=expected_extension,
        )

    def action_url(self, action: OBSAction) -> str | None:
        return {
            "status": self.status_url,
            "start": self.start_url,
            "stop": self.stop_url,
            "screenshot": self.screenshot_url,
            "scene": self.scene_url,
            "marker": self.marker_url,
        }[action]

    def has_action(self, action: OBSAction) -> bool:
        return bool(self.action_url(action))

    def missing_required_actions(self) -> list[OBSAction]:
        return [action for action in _REQUIRED_OBS_ACTIONS if not self.has_action(action)]

    def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        if self.token_header.lower() == "authorization" and self.token_scheme:
            return {self.token_header: f"{self.token_scheme} {self.token}"}
        return {self.token_header: self.token}

    def redacted(self) -> dict[str, Any]:
        return {
            "status_url": self.status_url,
            "start_url": self.start_url,
            "stop_url": self.stop_url,
            "screenshot_url": self.screenshot_url,
            "scene_url": self.scene_url,
            "marker_url": self.marker_url,
            "token_configured": bool(self.token),
            "token_header": self.token_header,
            "token_scheme": (
                self.token_scheme if self.token_header.lower() == "authorization" else ""
            ),
            "payload_mode": self.payload_mode,
            "timeout_seconds": self.timeout_seconds,
            "recording_output_dir": self.recording_output_dir,
            "expected_extension": self.expected_extension,
        }


class OBSWebhookClient:
    def __init__(self, config: OBSWebhookConfig) -> None:
        self.config = config
        self._client = httpx.Client(
            headers=config.headers(),
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def validate(self) -> dict[str, Any]:
        missing = self.config.missing_required_actions()
        if missing:
            raise OBSWebhookError(
                "OBS webhook configuration is missing required action URLs: "
                + ", ".join(_ACTION_ENV_NAMES[action] for action in missing)
            )
        if self.config.has_action("status"):
            status = self.request("status")
        else:
            status = {"configured": True, "status_probe": "not_configured"}
        return {"obs": status, "config": self.config.redacted()}

    def status(self) -> dict[str, Any] | None:
        if not self.config.has_action("status"):
            return None
        return self.request("status")

    def is_recording(self) -> bool | None:
        status = self.status()
        if status is None:
            return None
        return _recording_state(status)

    def start_recording(
        self,
        *,
        recording_name: str,
        scene_name: str | None = None,
        demo_id: str | None = None,
    ) -> dict[str, Any]:
        if scene_name and self.config.has_action("scene"):
            self.request("scene", {"scene": scene_name, "demo_id": demo_id})
        return self.request(
            "start",
            {
                "recording_name": recording_name,
                "scene": scene_name,
                "demo_id": demo_id,
            },
        )

    def stop_recording(self, *, demo_id: str | None = None) -> dict[str, Any]:
        return self.request("stop", {"demo_id": demo_id})

    def add_marker(self, marker: str, *, demo_id: str | None = None) -> dict[str, Any] | None:
        if not self.config.has_action("marker"):
            return None
        return self.request("marker", {"marker": marker, "demo_id": demo_id})

    def request(self, action: OBSAction, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.config.action_url(action)
        if not url:
            raise OBSWebhookError(f"OBS webhook action is not configured: {action}")
        method = "GET" if action == "status" else "POST"
        request_kwargs: dict[str, Any] = {}
        if method == "POST" and self.config.payload_mode == "json":
            request_kwargs["json"] = _compact_payload(payload or {})
        response = self._client.request(method, url, **request_kwargs)
        body = _response_payload(response)
        if response.is_error:
            raise OBSWebhookError(
                f"OBS webhook action {action!r} failed with HTTP {response.status_code}: "
                f"{_safe_body_excerpt(body)}"
            )
        return body if isinstance(body, dict) else {"value": body}


@dataclass(frozen=True)
class DemoRecordingNames:
    demo_id: str
    library_name: str
    dataset_label: str
    chat_label: str
    file_name: str
    question: str

    @classmethod
    def build(cls, demo_id: str | None = None) -> DemoRecordingNames:
        safe_id = safe_demo_id(demo_id)
        return cls(
            demo_id=safe_id,
            library_name=f"Demo OBS Seafile RAGFlow OpenWebUI {safe_id}",
            dataset_label=f"Demo OBS Dataset Seafile Sync {safe_id}",
            chat_label=f"Demo OBS Chat Seafile RAG {safe_id}",
            file_name=f"demo-seafile-ragflow-openwebui-workflow-{safe_id}.md",
            question=(
                "Welche Schritte beschreibt das Demo-Dokument für Seafile, RAGFlow "
                "und OpenWebUI, und wo ist der Prüfbegriff "
                "Bibliothek-Sync-Chunk-Preview-Originalprüfung zu sehen?"
            ),
        )

    @property
    def recording_name(self) -> str:
        return f"demo-seafile-ragflow-openwebui-full-workflow-{self.demo_id}"

    @property
    def marker(self) -> str:
        return f"BIBLIOTHEK_SYNC_CHUNK_PREVIEW_ORIGINALPRUEFUNG_{self.demo_id.upper()}"


def safe_demo_id(value: str | None = None) -> str:
    raw = value or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = _SAFE_DEMO_ID_RE.sub("-", raw).strip("-_")
    return safe or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_demo_markdown(path: Path, names: DemoRecordingNames) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_demo_markdown(names), encoding="utf-8", newline="\n")
    return path


def build_demo_markdown(names: DemoRecordingNames) -> str:
    return f"""# Demo-Dokument: Seafile, RAGFlow und OpenWebUI Workflow

Laufkennung: {names.demo_id}

## Überblick

Dieses Dokument beschreibt einen Demonstrationsworkflow, bei dem eine Datei
zuerst in eine Seafile-Bibliothek hochgeladen, danach in RAGFlow synchronisiert
und geparsed und anschließend über eine automatisch erzeugte OpenWebUI-Pipe
abgefragt wird.

## Seafile-Schritt

In Seafile wird eine neue Bibliothek erstellt. Die Bibliothek ist zunächst leer.
Erst nachdem in RAGFlow ein Dataset und ein Chat beziehungsweise Assistant
angelegt wurden, wird dieses Dokument in die Bibliothek hochgeladen.

Sichtbarer Bibliotheksname: `{names.library_name}`

## RAGFlow-Schritt

RAGFlow synchronisiert die Datei aus der Seafile-Bibliothek. Danach wird die
Datei geparsed. Die erzeugten Chunks enthalten Abschnitte zum Überblick, zum
Seafile-Schritt, zum RAGFlow-Schritt und zum OpenWebUI-Schritt.

Sichtbares Dataset-Label: `{names.dataset_label}`
Sichtbares Chat-Label: `{names.chat_label}`

## OpenWebUI-Schritt

OpenWebUI erkennt automatisch eine Pipe zur Bibliothek. Über diese Pipe kann
eine Frage zum Dokument gestellt werden. Die Antwort soll über Preview und
Originaldatei nachvollziehbar geprüft werden.

## Eindeutige Prüfinformation

Der eindeutige Prüfbegriff für diese Demo lautet:
Bibliothek-Sync-Chunk-Preview-Originalprüfung.

Interner Prüfmarker für wiederholbare Läufe: `{names.marker}`

## Demo-Frage

> {names.question}

Die Antwort muss die Schritte Seafile, RAGFlow und OpenWebUI nennen und über
Preview sowie Originaldatei mit diesem Dokument abgeglichen werden können.
"""


def build_recording_steps(names: DemoRecordingNames) -> list[dict[str, str]]:
    return [
        {
            "id": "browser-prepare",
            "title": "Demo-Browserfenster vorbereiten",
            "success": "Ein dediziertes Browserfenster ist für die OBS-Aufnahme sichtbar.",
        },
        {
            "id": "obs-start",
            "title": "OBS-Aufnahme starten",
            "success": "OBS-WebHook meldet den Start der Aufnahme.",
        },
        {
            "id": "seafile-open",
            "title": "Seafile öffnen",
            "success": "Seafile-Oberfläche ist sichtbar.",
        },
        {
            "id": "seafile-library-create",
            "title": "Seafile-Bibliothek erstellen",
            "success": (
                f"Bibliothek `{names.library_name}` wurde neu erstellt "
                "oder eindeutig geöffnet."
            ),
        },
        {
            "id": "seafile-library-empty",
            "title": "Leere Bibliothek vor Upload zeigen",
            "success": f"Bibliothek `{names.library_name}` ist vor dem Upload sichtbar leer.",
        },
        {
            "id": "ragflow-open",
            "title": "RAGFlow öffnen",
            "success": "RAGFlow-Oberfläche ist sichtbar.",
        },
        {
            "id": "ragflow-dataset-create",
            "title": "RAGFlow-Dataset zur Bibliothek erstellen",
            "success": (
                "Dataset ist sichtbar und mit Demo-Label "
                f"`{names.dataset_label}` korrelierbar."
            ),
        },
        {
            "id": "ragflow-dataset-details",
            "title": "RAGFlow-Dataset-Details zeigen",
            "success": "Dataset-ID, Bibliotheksbezug und Dokumentliste sind sichtbar.",
        },
        {
            "id": "ragflow-chat-create",
            "title": "RAGFlow-Chat oder Assistant vor Datei-Upload erstellen",
            "success": f"Chat `{names.chat_label}` ist dem Dataset zugeordnet.",
        },
        {
            "id": "seafile-upload",
            "title": "Datei erst nach Dataset und Chat hochladen",
            "success": f"`{names.file_name}` ist in Seafile sichtbar.",
        },
        {
            "id": "ragflow-sync",
            "title": "RAGFlow-Synchronisation zeigen",
            "success": "Dokument ist in der RAGFlow-Dateiliste sichtbar.",
        },
        {
            "id": "ragflow-parse",
            "title": "RAGFlow-Parsingstatus zeigen",
            "success": "Parsingstatus ist sichtbar erreicht oder abgeschlossen.",
        },
        {
            "id": "ragflow-chunks",
            "title": "Mehrere RAGFlow-Chunks öffnen",
            "success": (
                "Mehrere Chunks sind sichtbar; mindestens einer enthält "
                "`Bibliothek-Sync-Chunk-Preview-Originalprüfung`."
            ),
        },
        {
            "id": "openwebui-open",
            "title": "OpenWebUI öffnen",
            "success": "OpenWebUI-Oberfläche ist sichtbar.",
        },
        {
            "id": "openwebui-pipe",
            "title": "OpenWebUI-Pipe zur Bibliothek zeigen",
            "success": "Automatisch erzeugtes Pipe-Modell ist sichtbar.",
        },
        {
            "id": "openwebui-question",
            "title": "Frage stellen, Antwort, Preview und Original prüfen",
            "success": "Antwort, Preview und Originaldokument enthalten denselben Demo-Kontext.",
        },
        {
            "id": "openwebui-preview",
            "title": "Preview der Quelle öffnen",
            "success": "Die Preview zeigt den Prüfbegriff oder passende Abschnittsüberschriften.",
        },
        {
            "id": "openwebui-original",
            "title": "Originaldatei öffnen",
            "success": "Das Original zeigt denselben Prüfbegriff und dieselben Schritte.",
        },
        {
            "id": "workflow-final",
            "title": "Abschlussansicht zeigen",
            "success": "Antwort, Preview und Original sind nachvollziehbar zusammengeführt.",
        },
        {
            "id": "obs-stop",
            "title": "OBS-Aufnahme stoppen",
            "success": "OBS-WebHook meldet kontrollierten Stopp.",
        },
    ]


def write_recording_summary(
    path: Path,
    *,
    names: DemoRecordingNames,
    mode: str,
    obs_config: OBSWebhookConfig,
    checks: dict[str, Any] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "demo_id": names.demo_id,
        "recording_name": names.recording_name,
        "library_name": names.library_name,
        "dataset_label": names.dataset_label,
        "chat_label": names.chat_label,
        "file_name": names.file_name,
        "question": names.question,
        "steps": build_recording_steps(names),
        "required_workflow": build_workflow_validation_template(),
        "obs": obs_config.redacted(),
        "checks": checks or {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_workflow_validation_template() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "label": label,
            "status": "nicht geprüft",
            "evidence": "",
            "automatic": False,
            "visual": False,
        }
        for key, label in REQUIRED_WORKFLOW_POINTS
    }


def validate_recording_artifact(
    *,
    recording_name: str,
    demo_id: str,
    expected_extension: str = ".mkv",
    output_dir: str | Path | None = None,
    webhook_payloads: Iterable[Any] = (),
    started_at: datetime | None = None,
) -> dict[str, Any]:
    extension = _normalize_extension(expected_extension)
    candidates: list[tuple[Path, str]] = []
    for payload in webhook_payloads:
        for value in _recording_paths_from_payload(payload, extension):
            candidates.append((Path(value), "webhook"))
    if output_dir:
        candidates.extend(
            (path, "output_dir")
            for path in _filesystem_recording_candidates(
                Path(output_dir),
                recording_name=recording_name,
                demo_id=demo_id,
                expected_extension=extension,
                started_at=started_at,
            )
        )
    unique_candidates = _unique_path_candidates(candidates)
    selected: tuple[Path, str] | None = None
    for candidate in unique_candidates:
        path, _source = candidate
        if path.exists() and path.is_file() and path.suffix.lower() == extension:
            selected = candidate
            break
    if selected is None and unique_candidates:
        selected = unique_candidates[0]

    artifact_path = selected[0] if selected else None
    source = selected[1] if selected else None
    exists = bool(artifact_path and artifact_path.exists() and artifact_path.is_file())
    size_bytes = artifact_path.stat().st_size if exists and artifact_path else None
    extension_ok = bool(artifact_path and artifact_path.suffix.lower() == extension)
    valid = bool(exists and extension_ok and (size_bytes or 0) > 0)
    return {
        "path": str(artifact_path) if artifact_path else None,
        "exists": exists,
        "size_bytes": size_bytes,
        "extension_ok": extension_ok,
        "valid": valid,
        "source": source,
        "expected_extension": extension,
        "candidate_count": len(unique_candidates),
        "candidates": [str(candidate[0]) for candidate in unique_candidates[:10]],
    }


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _float_env(value: str | None, *, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in {None, ""}}


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _safe_body_excerpt(body: Any) -> str:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str)
    return text[:500]


def _normalize_extension(value: str) -> str:
    extension = value.strip().lower()
    if not extension:
        return ".mkv"
    if extension in {"matroska", "mkv"}:
        return ".mkv"
    if not extension.startswith("."):
        extension = f".{extension}"
    return extension


def _recording_state(payload: Any) -> bool | None:
    if isinstance(payload, dict):
        for key in (
            "recording",
            "is_recording",
            "recording_active",
            "recording_running",
            "active",
            "running",
        ):
            if key in payload:
                return _boolish(payload.get(key))
        for key in ("status", "state"):
            state = str(payload.get(key) or "").strip().lower()
            if state in {"recording", "started", "running", "active"}:
                return True
            if state in {"idle", "stopped", "not_recording", "inactive"}:
                return False
        for value in payload.values():
            nested = _recording_state(value)
            if nested is not None:
                return nested
    if isinstance(payload, list):
        for value in payload:
            nested = _recording_state(value)
            if nested is not None:
                return nested
    return None


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "recording", "running", "started", "active"}:
        return True
    if text in {"0", "false", "no", "off", "idle", "stopped", "inactive"}:
        return False
    return None


def _recording_paths_from_payload(payload: Any, expected_extension: str) -> list[str]:
    paths: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in _RECORDING_PATH_KEYS:
                paths.extend(_recording_path_values(value, expected_extension))
            paths.extend(_recording_paths_from_payload(value, expected_extension))
    elif isinstance(payload, list):
        for value in payload:
            paths.extend(_recording_paths_from_payload(value, expected_extension))
    return paths


def _recording_path_values(value: Any, expected_extension: str) -> list[str]:
    if isinstance(value, str):
        text = value.strip().strip('"')
        if _looks_like_recording_path(text, expected_extension):
            return [text]
    if isinstance(value, (dict, list)):
        return _recording_paths_from_payload(value, expected_extension)
    return []


def _looks_like_recording_path(value: str, expected_extension: str) -> bool:
    if not value or value.startswith(("http://", "https://")):
        return False
    return Path(value).suffix.lower() == expected_extension


def _filesystem_recording_candidates(
    output_dir: Path,
    *,
    recording_name: str,
    demo_id: str,
    expected_extension: str,
    started_at: datetime | None,
) -> list[Path]:
    if not output_dir.exists() or not output_dir.is_dir():
        return []
    names = {recording_name.lower(), demo_id.lower()}
    started_ts = started_at.timestamp() - 10 if started_at else None
    candidates: list[Path] = []
    for path in output_dir.rglob(f"*{expected_extension}"):
        if not path.is_file():
            continue
        if started_ts is not None and path.stat().st_mtime < started_ts:
            continue
        lower_name = path.name.lower()
        if any(name and name in lower_name for name in names):
            candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates


def _unique_path_candidates(candidates: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: set[str] = set()
    unique: list[tuple[Path, str]] = []
    for path, source in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append((path, source))
    return unique
