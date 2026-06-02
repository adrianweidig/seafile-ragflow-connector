from __future__ import annotations

import json
import os
import re
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

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> OBSWebhookConfig:
        values = environ or dict(os.environ)
        payload_mode = values.get("OBS_WEBHOOK_PAYLOAD_MODE", "json").strip().lower()
        if payload_mode not in {"json", "none"}:
            payload_mode = "json"
        timeout = _float_env(values.get("OBS_WEBHOOK_TIMEOUT_SECONDS"), default=20.0)
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
            library_name=f"Demo RAGFlow OpenWebUI Bibliothek {safe_id}",
            dataset_label=f"Demo Dataset Seafile Sync {safe_id}",
            chat_label=f"Demo Chat Seafile RAG {safe_id}",
            file_name=f"seafile-ragflow-openwebui-demo-{safe_id}.md",
            question=(
                "Welche zentralen Schritte beschreibt das Dokument für den Seafile-, "
                "RAGFlow- und OpenWebUI-Workflow, und wo im Originaldokument werden "
                "diese Schritte erläutert?"
            ),
        )

    @property
    def recording_name(self) -> str:
        return f"seafile-ragflow-openwebui-demo-{self.demo_id}"

    @property
    def marker(self) -> str:
        return f"DEMO_SEAFILE_RAGFLOW_OPENWEBUI_{self.demo_id.upper()}"


def safe_demo_id(value: str | None = None) -> str:
    raw = value or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = _SAFE_DEMO_ID_RE.sub("-", raw).strip("-_")
    return safe or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_demo_markdown(path: Path, names: DemoRecordingNames) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_demo_markdown(names), encoding="utf-8", newline="\n")
    return path


def build_demo_markdown(names: DemoRecordingNames) -> str:
    return f"""# Seafile-, RAGFlow- und OpenWebUI-Demo {names.demo_id}

Eindeutiger Prüfmarker: {names.marker}

## Überblick

Dieses Dokument beschreibt den Demoablauf für eine neue Seafile-Bibliothek, ein
zugehöriges RAGFlow-Dataset, einen RAGFlow-Chat und eine automatisch erzeugte
OpenWebUI-Pipe. Seafile bleibt die Quelle der Wahrheit; RAGFlow und OpenWebUI
werden aus der Connector-Synchronisation aufgebaut.

## Schritt 1: Bibliothek und Dataset

Die Demo beginnt mit einer leeren Seafile-Bibliothek namens
`{names.library_name}`. Danach wird das dazugehörige RAGFlow-Dataset sichtbar
gemacht. Der Connector bildet den technischen Dataset-Namen aus dem
Seafile-Bibliotheksnamen und der echten Repo-ID; das sichtbare Demo-Label lautet
`{names.dataset_label}`.

## Schritt 2: Chat vor Upload

Vor dem Datei-Upload wird der RAGFlow-Chat für das Dataset erzeugt. Das
sichtbare Demo-Label für diesen Chat lautet `{names.chat_label}`. Damit ist im
Video nachvollziehbar, dass die Chat- und Pipe-Strecke bereits vorbereitet ist,
bevor Inhalte aus Seafile synchronisiert werden.

## Schritt 3: Upload und Synchronisation

Erst nach Bibliothek, Dataset und Chat wird diese Datei in Seafile hochgeladen.
Der Connector synchronisiert sie anschließend nach RAGFlow, startet das Parsing
und speichert Metadaten wie Repo-ID, Quellpfad, Dateityp und Prüfsumme.

## Schritt 4: Chunks und Nachweise

Nach abgeschlossenem Parsing zeigt RAGFlow mehrere Chunks aus diesem Dokument.
Die Chunks enthalten den Prüfmarker `{names.marker}`, die Schrittüberschriften
und die Aussage, dass Seafile die Quelle der Wahrheit bleibt.

## Schritt 5: OpenWebUI-Frage

In OpenWebUI wird die automatisch erzeugte Pipe zur Bibliothek ausgewählt. Die
Demo-Frage lautet:

> {names.question}

Die erwartete Antwort nennt die Schritte Bibliothek, Dataset, Chat, Upload,
Synchronisation, Parsing, Chunk-Prüfung, OpenWebUI-Pipe, Preview und
Originaldatei. Preview und Originaldatei müssen den Marker `{names.marker}` und
die passenden Abschnittsüberschriften enthalten.
"""


def build_recording_steps(names: DemoRecordingNames) -> list[dict[str, str]]:
    return [
        {
            "id": "obs-start",
            "title": "OBS-Aufnahme starten",
            "success": "OBS-WebHook meldet Start oder vorhandene Aufnahme.",
        },
        {
            "id": "seafile-library",
            "title": "Seafile öffnen und leere Bibliothek zeigen",
            "success": f"Bibliothek `{names.library_name}` ist sichtbar und leer.",
        },
        {
            "id": "ragflow-dataset",
            "title": "RAGFlow-Dataset zur Bibliothek zeigen",
            "success": (
                "Dataset ist sichtbar und mit Demo-Label "
                f"`{names.dataset_label}` korrelierbar."
            ),
        },
        {
            "id": "ragflow-chat",
            "title": "RAGFlow-Chat vor Datei-Upload zeigen",
            "success": f"Chat `{names.chat_label}` ist dem Dataset zugeordnet.",
        },
        {
            "id": "seafile-upload",
            "title": "Datei erst nach Dataset und Chat hochladen",
            "success": f"`{names.file_name}` ist in Seafile sichtbar.",
        },
        {
            "id": "ragflow-sync-parse",
            "title": "RAGFlow-Synchronisation und Parsing prüfen",
            "success": (
                "Dokument ist sichtbar und Parsingstatus ist abgeschlossen "
                "oder nachvollziehbar."
            ),
        },
        {
            "id": "ragflow-chunks",
            "title": "Mehrere RAGFlow-Chunks öffnen",
            "success": f"Mindestens ein Chunk enthält `{names.marker}`.",
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
        "obs": obs_config.redacted(),
        "checks": checks or {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


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
