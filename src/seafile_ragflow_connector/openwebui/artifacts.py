from __future__ import annotations

import re
from dataclasses import dataclass
from textwrap import dedent

from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.utils.hashing import sha256_json, sha256_text

ARTIFACT_VERSION = "8"
_IDENTIFIER_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class OpenWebUIArtifactSpec:
    artifact_id: str
    name: str
    content: str
    valves: dict[str, object]
    payload: dict[str, object]
    definition_hash: str


@dataclass(frozen=True)
class DatasetArtifactInputs:
    namespace: str
    repo_id: str
    dataset_id: str
    dataset_name: str
    ragflow_chat_id: str | None
    proxy_base_url: str | None
    proxy_verify_ssl: bool = True
    proxy_ca_bundle: str | None = None
    model_name_prefix: str = "ragflow"


def build_tool_spec(inputs: DatasetArtifactInputs) -> OpenWebUIArtifactSpec:
    artifact_id = build_tool_id(inputs.namespace, inputs.dataset_name, inputs.dataset_id)
    name = f"RAGFlow Suche: {inputs.dataset_name}"
    content = _tool_content()
    valves: dict[str, object] = {
        "ARTIFACT_ID": artifact_id,
        "CONNECTOR_PROXY_BASE_URL": inputs.proxy_base_url or "",
        "CONNECTOR_PROXY_SHARED_SECRET": "",
        "CONNECTOR_PROXY_VERIFY_SSL": inputs.proxy_verify_ssl,
        "CONNECTOR_PROXY_CA_BUNDLE": inputs.proxy_ca_bundle or "",
        "TLS_DEBUG": False,
        "DATASET_ID": inputs.dataset_id,
        "TOP_K": 8,
        "SHOW_SOURCE_SCORES": True,
        "SHOW_SOURCE_DEBUG": False,
        "SOURCE_MARKDOWN_MODE": "compact",
    }
    payload: dict[str, object] = {
        "id": artifact_id,
        "name": name,
        "content": content,
        "meta": {
            "description": f"Dataset-spezifische RAGFlow-Suche für {inputs.dataset_name}.",
            "manifest": _manifest("tool", inputs),
        },
        "access_grants": [],
    }
    definition_hash = _definition_hash(payload, valves)
    return OpenWebUIArtifactSpec(artifact_id, name, content, valves, payload, definition_hash)


def build_pipe_spec(inputs: DatasetArtifactInputs) -> OpenWebUIArtifactSpec:
    artifact_id = build_pipe_id(inputs.namespace, inputs.dataset_name, inputs.dataset_id)
    model_name = build_model_name(inputs.namespace, inputs.dataset_name, inputs.dataset_id)
    content = _pipe_content()
    valves: dict[str, object] = {
        "ARTIFACT_ID": artifact_id,
        "CONNECTOR_PROXY_BASE_URL": inputs.proxy_base_url or "",
        "CONNECTOR_PROXY_SHARED_SECRET": "",
        "CONNECTOR_PROXY_VERIFY_SSL": inputs.proxy_verify_ssl,
        "CONNECTOR_PROXY_CA_BUNDLE": inputs.proxy_ca_bundle or "",
        "TLS_DEBUG": False,
        "DATASET_ID": inputs.dataset_id,
        "RAGFLOW_CHAT_ID": inputs.ragflow_chat_id or "",
        "MODEL_ID": model_name,
        "MODEL_NAME": model_name,
        "TOP_K": 8,
        "SHOW_SOURCE_SCORES": True,
        "SHOW_SOURCE_DEBUG": False,
        "SOURCE_MARKDOWN_MODE": "compact",
    }
    payload: dict[str, object] = {
        "id": artifact_id,
        "name": f"RAGFlow Modell: {inputs.dataset_name}",
        "content": content,
        "meta": {
            "description": f"OpenWebUI-Custom-Model für RAGFlow-Dataset {inputs.dataset_name}.",
            "manifest": _manifest("pipe", inputs),
        },
    }
    definition_hash = _definition_hash(payload, valves)
    return OpenWebUIArtifactSpec(artifact_id, model_name, content, valves, payload, definition_hash)


def build_tool_id(namespace: str, dataset_name: str, dataset_id: str) -> str:
    return _identifier(namespace, "tool", dataset_name, dataset_id)


def build_pipe_id(namespace: str, dataset_name: str, dataset_id: str) -> str:
    return _identifier(namespace, "pipe", dataset_name, dataset_id)


def build_model_name(namespace: str, dataset_name: str, dataset_id: str) -> str:
    slug = slugify(dataset_name, fallback="dataset").replace("-", "_")
    return f"{namespace}/{slug}_{_short_id(dataset_id)}"


def _identifier(namespace: str, kind: str, dataset_name: str, dataset_id: str) -> str:
    slug = slugify(dataset_name, fallback="dataset").replace("-", "_")
    raw = f"{namespace}_{kind}_{slug}_{_short_id(dataset_id)}".lower()
    clean = _IDENTIFIER_RE.sub("_", raw).strip("_")
    if clean and clean[0].isdigit():
        clean = f"owui_{clean}"
    return clean[:96]


def _short_id(value: str) -> str:
    clean = _IDENTIFIER_RE.sub("", value.lower())
    if len(clean) >= 8:
        return clean[:12]
    return sha256_text(value)[:12]


def _manifest(kind: str, inputs: DatasetArtifactInputs) -> dict[str, object]:
    return {
        "owner": "seafile-ragflow-connector",
        "kind": kind,
        "artifact_version": ARTIFACT_VERSION,
        "repo_id": inputs.repo_id,
        "ragflow_dataset_id": inputs.dataset_id,
        "ragflow_dataset_name": inputs.dataset_name,
        "ragflow_chat_id": inputs.ragflow_chat_id,
    }


def _definition_hash(payload: dict[str, object], valves: dict[str, object]) -> str:
    hash_valves = {key: value for key, value in valves.items() if "SECRET" not in key}
    return sha256_json({"payload": payload, "valves": hash_valves, "version": ARTIFACT_VERSION})


def _tool_content() -> str:
    return (
        dedent(
            '''
        """
        title: RAGFlow Dataset Search
        author: Seafile RAGFlow Connector
        version: 1.3.0
        owner: seafile-ragflow-connector
        artifact_version: 8
        """

        import httpx
        import logging
        import re
        from pathlib import Path
        from urllib.parse import urlsplit, urlunsplit
        from pydantic import BaseModel, Field


        class Tools:
            class Valves(BaseModel):
                ARTIFACT_ID: str = Field(default="")
                CONNECTOR_PROXY_BASE_URL: str = Field(default="")
                CONNECTOR_PROXY_SHARED_SECRET: str = Field(default="")
                CONNECTOR_PROXY_VERIFY_SSL: bool = Field(default=True)
                CONNECTOR_PROXY_CA_BUNDLE: str = Field(default="")
                TLS_DEBUG: bool = Field(default=False)
                DATASET_ID: str = Field(default="")
                TOP_K: int = Field(default=8, ge=1, le=20)
                SHOW_SOURCE_SCORES: bool = Field(default=True)
                SHOW_SOURCE_DEBUG: bool = Field(default=False)
                SOURCE_MARKDOWN_MODE: str = Field(default="compact")

            def __init__(self):
                self.valves = self.Valves()

            async def query_dataset(self, question: str, __event_emitter__=None) -> str:
                """Query the assigned RAGFlow dataset through the connector proxy."""
                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": "Suche im RAGFlow-Dataset...",
                                "done": False,
                            },
                        }
                    )
                payload = {
                    "artifact_id": self.valves.ARTIFACT_ID,
                    "dataset_id": self.valves.DATASET_ID,
                    "question": question,
                    "top_k": self.valves.TOP_K,
                }
                headers = {
                    "Authorization": f"Bearer {self.valves.CONNECTOR_PROXY_SHARED_SECRET}",
                    "Content-Type": "application/json",
                }
                url = (
                    self.valves.CONNECTOR_PROXY_BASE_URL.rstrip("/")
                    + "/api/openwebui/proxy/query"
                )
                try:
                    verify = _httpx_verify(
                        self.valves.CONNECTOR_PROXY_VERIFY_SSL,
                        self.valves.CONNECTOR_PROXY_CA_BUNDLE,
                    )
                    async with httpx.AsyncClient(
                        timeout=60,
                        verify=verify,
                    ) as client:
                        response = await client.post(url, json=payload, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                except ValueError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "TLS-Konfiguration ungültig.",
                                    "done": True,
                                },
                            }
                        )
                    return "Die TLS-Konfiguration der RAGFlow-Pipe ist ungültig."
                except httpx.TimeoutException as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Proxy-Timeout.",
                                    "done": True,
                                },
                            }
                        )
                    return "Der RAGFlow-Proxy hat nicht rechtzeitig geantwortet."
                except httpx.HTTPStatusError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    status = exc.response.status_code
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": f"RAGFlow-Proxy antwortete mit HTTP {status}.",
                                    "done": True,
                                },
                            }
                        )
                    return f"RAGFlow-Proxy antwortete mit HTTP {status}."
                except httpx.ConnectError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Proxy war nicht erreichbar.",
                                    "done": True,
                                },
                            }
                        )
                    return "Der RAGFlow-Proxy war nicht erreichbar."
                except Exception as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Abfrage fehlgeschlagen.",
                                    "done": True,
                                },
                            }
                        )
                    return "Die RAGFlow-Abfrage konnte nicht ausgeführt werden."

                sources = _normalize_sources(
                    data.get("sources") or [],
                    show_scores=self.valves.SHOW_SOURCE_SCORES,
                    show_debug=self.valves.SHOW_SOURCE_DEBUG,
                )
                if __event_emitter__:
                    for source in sources:
                        await __event_emitter__({"type": "source", "data": source})
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": "RAGFlow-Abfrage abgeschlossen.",
                                "done": True,
                            },
                        }
                    )
                return data.get("answer") or _source_markdown(
                    sources,
                    show_scores=self.valves.SHOW_SOURCE_SCORES,
                    show_debug=self.valves.SHOW_SOURCE_DEBUG,
                )


        def _source_markdown(sources):
            if not sources:
                return "Keine passenden Quellen gefunden."
            lines = ["## Gefundene Quellen", ""]
            for index, source in enumerate(sources, start=1):
                title = source.get("name") or source.get("document_name") or "Quelle"
                snippet = _clean_snippet(source.get("text") or source.get("snippet") or "")
                locator = _source_locator(source)
                line = f"{index}. **{_clean(title)}**"
                if locator != "-":
                    line += f" - {locator}"
                lines.append(line)
                if snippet:
                    lines.append(f"   > {_compact(snippet, 360)}")
            return "\\n".join(lines)


        def _source_locator(source):
            metadata = source.get("source_metadata") or {}
            parts = []
            if metadata.get("page") not in (None, ""):
                parts.append(f"Seite {metadata.get('page')}")
            if metadata.get("line") not in (None, ""):
                parts.append(f"Zeile {metadata.get('line')}")
            chunk = metadata.get("chunk_id")
            if chunk not in (None, ""):
                parts.append(f"Chunk `{str(chunk)[:12]}`")
            return _clean(", ".join(parts) or "-")


        def _compact(value, limit=220):
            clean = _clean(value)
            return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


        def _clean_snippet(value):
            clean = str(value or "")
            clean = re.sub(r"(?is)<(script|style).*?</\\1>", " ", clean)
            clean = re.sub(r"(?i)</t[dh]>\\s*<t[dh][^>]*>", " | ", clean)
            clean = re.sub(r"(?i)</tr>\\s*<tr[^>]*>", "\\n", clean)
            clean = re.sub(r"(?i)<br\\s*/?>", "\\n", clean)
            clean = re.sub(r"(?s)<[^>]+>", " ", clean)
            clean = "\\n".join(" ".join(line.split()) for line in clean.splitlines())
            return "\\n".join(line for line in clean.splitlines() if line).strip()


        def _clean(value):
            return " ".join(str(value or "").split())

            '''
        ).strip()
        + "\n\n"
        + _artifact_source_helpers()
    )


def _pipe_content() -> str:
    return (
        dedent(
            '''
        """
        title: RAGFlow Dataset Pipe
        author: Seafile RAGFlow Connector
        version: 1.3.0
        owner: seafile-ragflow-connector
        artifact_version: 8
        """

        import httpx
        import logging
        import re
        from pathlib import Path
        from urllib.parse import urlsplit, urlunsplit
        from pydantic import BaseModel, Field


        class Pipe:
            class Valves(BaseModel):
                ARTIFACT_ID: str = Field(default="")
                CONNECTOR_PROXY_BASE_URL: str = Field(default="")
                CONNECTOR_PROXY_SHARED_SECRET: str = Field(default="")
                CONNECTOR_PROXY_VERIFY_SSL: bool = Field(default=True)
                CONNECTOR_PROXY_CA_BUNDLE: str = Field(default="")
                TLS_DEBUG: bool = Field(default=False)
                DATASET_ID: str = Field(default="")
                RAGFLOW_CHAT_ID: str = Field(default="")
                MODEL_ID: str = Field(default="")
                MODEL_NAME: str = Field(default="")
                TOP_K: int = Field(default=8, ge=1, le=20)
                SHOW_SOURCE_SCORES: bool = Field(default=True)
                SHOW_SOURCE_DEBUG: bool = Field(default=False)
                SOURCE_MARKDOWN_MODE: str = Field(default="compact")

            def __init__(self):
                self.valves = self.Valves()

            def pipes(self):
                return [
                    {
                        "id": self.valves.MODEL_ID,
                        "name": self.valves.MODEL_NAME or self.valves.MODEL_ID,
                    }
                ]

            async def pipe(
                self,
                body: dict,
                __event_emitter__=None,
                __user__: dict | None = None,
                __task__: str | None = None,
                __task_body__: dict | None = None,
                __metadata__: dict | None = None,
            ):
                task = _normalize_task(__task__ or (__metadata__ or {}).get("task"))
                if task:
                    return _task_response(task, __task_body__ or body)

                if __event_emitter__:
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": "RAGFlow-Antwort wird vorbereitet...",
                                "done": False,
                            },
                        }
                    )
                payload = {
                    "artifact_id": self.valves.ARTIFACT_ID,
                    "dataset_id": self.valves.DATASET_ID,
                    "chat_id": self.valves.RAGFLOW_CHAT_ID,
                    "messages": body.get("messages") or [],
                    "model": body.get("model") or self.valves.MODEL_ID or "model",
                    "top_k": self.valves.TOP_K,
                    "user": {
                        "id": (__user__ or {}).get("id"),
                        "email": (__user__ or {}).get("email"),
                    },
                }
                headers = {
                    "Authorization": f"Bearer {self.valves.CONNECTOR_PROXY_SHARED_SECRET}",
                    "Content-Type": "application/json",
                }
                url = (
                    self.valves.CONNECTOR_PROXY_BASE_URL.rstrip("/")
                    + "/api/openwebui/proxy/chat"
                )
                try:
                    verify = _httpx_verify(
                        self.valves.CONNECTOR_PROXY_VERIFY_SSL,
                        self.valves.CONNECTOR_PROXY_CA_BUNDLE,
                    )
                    async with httpx.AsyncClient(
                        timeout=180,
                        verify=verify,
                    ) as client:
                        response = await client.post(url, json=payload, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                except ValueError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "TLS-Konfiguration ungültig.",
                                    "done": True,
                                },
                            }
                        )
                    return "Die TLS-Konfiguration der RAGFlow-Pipe ist ungültig."
                except httpx.TimeoutException as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow hat nicht rechtzeitig geantwortet.",
                                    "done": True,
                                },
                            }
                        )
                    return "RAGFlow hat nicht rechtzeitig geantwortet."
                except httpx.HTTPStatusError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    status = exc.response.status_code
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": f"RAGFlow-Proxy antwortete mit HTTP {status}.",
                                    "done": True,
                                },
                            }
                        )
                    return f"RAGFlow-Proxy antwortete mit HTTP {status}."
                except httpx.ConnectError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Proxy war nicht erreichbar.",
                                    "done": True,
                                },
                            }
                        )
                    return "Der RAGFlow-Proxy war nicht erreichbar."
                except httpx.RequestError as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Proxy war nicht erreichbar.",
                                    "done": True,
                                },
                            }
                        )
                    return "Der RAGFlow-Proxy war nicht erreichbar."
                except Exception as exc:
                    _log_proxy_error(exc, url, self.valves.CONNECTOR_PROXY_CA_BUNDLE)
                    if __event_emitter__:
                        await __event_emitter__(
                            {
                                "type": "status",
                                "data": {
                                    "description": "RAGFlow-Antwort fehlgeschlagen.",
                                    "done": True,
                                },
                            }
                        )
                    return (
                        "Die RAGFlow-Antwort konnte wegen eines unerwarteten Fehlers "
                        "nicht erzeugt werden."
                    )

                sources = _normalize_sources(
                    data.get("sources") or [],
                    show_scores=self.valves.SHOW_SOURCE_SCORES,
                    show_debug=self.valves.SHOW_SOURCE_DEBUG,
                )
                if __event_emitter__:
                    for source in sources:
                        await __event_emitter__({"type": "source", "data": source})
                    await __event_emitter__(
                        {
                            "type": "status",
                            "data": {
                                "description": "RAGFlow-Antwort abgeschlossen.",
                                "done": True,
                            },
                        }
                    )
                answer = data.get("answer") or ""
                if sources and not data.get("citations_emitted", True):
                    answer = answer + "\\n\\n" + _source_markdown(
                        sources,
                        show_scores=self.valves.SHOW_SOURCE_SCORES,
                        show_debug=self.valves.SHOW_SOURCE_DEBUG,
                    )
                return answer or _source_markdown(
                    sources,
                    show_scores=self.valves.SHOW_SOURCE_SCORES,
                    show_debug=self.valves.SHOW_SOURCE_DEBUG,
                ) or "RAGFlow hat keine Antwort geliefert."


        def _normalize_task(task):
            if not task:
                return ""
            value = str(task).lower()
            if "." in value:
                value = value.rsplit(".", 1)[-1]
            return value


        def _task_response(task, task_body):
            text = _last_user_text((task_body or {}).get("messages") or [])
            if "title" in task:
                return _compact_text(text, 80) or "RAGFlow"
            if "tags" in task or "follow_up" in task:
                return "[]"
            if "emoji" in task:
                return "RAG"
            if "query" in task or "image_prompt" in task:
                return _compact_text(text, 160)
            return ""


        def _last_user_text(messages):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            parts.append(str(item.get("text") or ""))
                    return " ".join(part for part in parts if part)
            return ""


        def _compact_text(text, max_length):
            clean = " ".join(str(text or "").split())
            if len(clean) <= max_length:
                return clean
            return clean[: max_length - 1].rstrip() + "..."

        def _source_markdown(sources):
            if not sources:
                return ""
            lines = ["## Gefundene Quellen", ""]
            for index, source in enumerate(sources, start=1):
                title = source.get("name") or source.get("document_name") or "Quelle"
                snippet = _clean_snippet(source.get("text") or source.get("snippet") or "")
                locator = _source_locator(source)
                line = f"{index}. **{_clean(title)}**"
                if locator != "-":
                    line += f" - {locator}"
                lines.append(line)
                if snippet:
                    lines.append(f"   > {_compact(snippet, 360)}")
            return "\\n".join(lines)


        def _source_locator(source):
            metadata = source.get("source_metadata") or {}
            parts = []
            if metadata.get("page") not in (None, ""):
                parts.append(f"Seite {metadata.get('page')}")
            if metadata.get("line") not in (None, ""):
                parts.append(f"Zeile {metadata.get('line')}")
            chunk = metadata.get("chunk_id")
            if chunk not in (None, ""):
                parts.append(f"Chunk `{str(chunk)[:12]}`")
            return _clean(", ".join(parts) or "-")


        def _compact(value, limit=220):
            clean = _clean(value)
            return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


        def _clean_snippet(value):
            clean = str(value or "")
            clean = re.sub(r"(?is)<(script|style).*?</\\1>", " ", clean)
            clean = re.sub(r"(?i)</t[dh]>\\s*<t[dh][^>]*>", " | ", clean)
            clean = re.sub(r"(?i)</tr>\\s*<tr[^>]*>", "\\n", clean)
            clean = re.sub(r"(?i)<br\\s*/?>", "\\n", clean)
            clean = re.sub(r"(?s)<[^>]+>", " ", clean)
            clean = "\\n".join(" ".join(line.split()) for line in clean.splitlines())
            return "\\n".join(line for line in clean.splitlines() if line).strip()


        def _clean(value):
            return " ".join(str(value or "").split())
            '''
        ).strip()
        + "\n\n"
        + _artifact_source_helpers()
    )


def _artifact_source_helpers() -> str:
    return dedent(
        '''

        from html import unescape
        from typing import Any


        def _httpx_verify(verify_ssl, ca_bundle):
            if not bool(verify_ssl):
                logging.getLogger(__name__).warning(
                    "OpenWebUI Pipe -> Connector Proxy uses VERIFY_SSL=false; "
                    "this is only intended for debug/dev."
                )
                return False
            ca_path = str(ca_bundle or "").strip()
            if not ca_path:
                return True
            path = Path(ca_path)
            if not path.exists():
                raise ValueError(f"CA bundle does not exist: {ca_path}")
            if not path.is_file():
                raise ValueError(f"CA bundle is not a file: {ca_path}")
            return ca_path


        def _log_proxy_error(exc, url, ca_bundle):
            logging.getLogger(__name__).warning(
                "OpenWebUI Pipe -> Connector Proxy failed "
                "target=%s error_class=%s ca_bundle_set=%s",
                _safe_url(url),
                _error_class(exc),
                bool(str(ca_bundle or "").strip()),
            )


        def _safe_url(url):
            parsed = urlsplit(str(url or ""))
            if not parsed.scheme or not parsed.netloc:
                return str(url or "").split("?", 1)[0]
            host = parsed.hostname or ""
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/") or "", "", ""))


        def _error_class(exc):
            if isinstance(exc, httpx.TimeoutException):
                return "TIMEOUT"
            if isinstance(exc, httpx.HTTPStatusError):
                return f"HTTP_{exc.response.status_code}"
            if isinstance(exc, httpx.ConnectError):
                text = str(exc).lower()
                if "certificate" in text or "cert" in text or "ssl" in text:
                    return "CERTIFICATE_VERIFY_FAILED"
                return "CONNECT_ERROR"
            if isinstance(exc, httpx.RequestError):
                return exc.__class__.__name__.upper()
            if isinstance(exc, ValueError):
                return "TLS_CONFIGURATION_ERROR"
            return exc.__class__.__name__.upper()


        class SourceHit(BaseModel):
            rank: int
            title: str
            snippet: str = ""
            page: object | None = None
            line: object | None = None
            chunk_id: str | None = None
            score: object | None = None
            preview_url: str | None = None
            original_url: str | None = None
            path: str | None = None
            document_id: str | None = None
            dataset_id: str | None = None
            repo_id: str | None = None
            file_type: str | None = None
            source_metadata: dict[str, Any] = Field(default_factory=dict)


        def _normalize_sources(sources, *, show_scores=True, show_debug=False):
            normalized = []
            seen = set()
            for rank, source in enumerate(sources, start=1):
                hit = _normalize_source(source, rank)
                key = (
                    hit.path or hit.title,
                    hit.document_id or "",
                    hit.chunk_id or "",
                    _clean(hit.snippet)[:180],
                )
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(_source_event_data(hit))
            return normalized


        def _normalize_source(source, rank):
            metadata = _metadata(source)
            title = (
                source.get("name")
                or source.get("document_name")
                or metadata.get("document_name")
                or "Quelle"
            )
            snippet = _clean_snippet(source.get("text") or source.get("snippet") or "")
            return SourceHit(
                rank=rank,
                title=str(title),
                snippet=snippet,
                page=metadata.get("page"),
                line=metadata.get("line"),
                chunk_id=_string_or_none(metadata.get("chunk_id")),
                score=source.get("score") or metadata.get("score"),
                preview_url=source.get("preview_url") or source.get("url"),
                original_url=source.get("original_url") or metadata.get("original_url"),
                path=_string_or_none(metadata.get("path")),
                document_id=_string_or_none(metadata.get("document_id")),
                dataset_id=_string_or_none(metadata.get("dataset_id")),
                repo_id=_string_or_none(metadata.get("repo_id")),
                file_type=_string_or_none(metadata.get("file_type")),
                source_metadata=dict(metadata),
            )


        def _source_event_data(hit):
            metadata = dict(hit.source_metadata)
            metadata.update(
                {
                    "rank": hit.rank,
                    "score": hit.score,
                    "relevance": _relevance(hit.score),
                    "preview_url": hit.preview_url,
                    "original_url": hit.original_url,
                    "path": hit.path,
                    "file_type": hit.file_type,
                }
            )
            metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
            return {
                "name": hit.title,
                "url": hit.preview_url,
                "preview_url": hit.preview_url,
                "original_url": hit.original_url,
                "text": hit.snippet,
                "snippet": hit.snippet,
                "document": [hit.snippet or hit.title],
                "score": hit.score,
                "relevance": metadata.get("relevance"),
                "rank": hit.rank,
                "source_metadata": metadata,
                "metadata": [metadata],
                "source": {"name": hit.title, "url": hit.preview_url},
            }


        def _source_markdown(sources, *, show_scores=True, show_debug=False):
            if not sources:
                return "Keine passenden Quellen gefunden."
            groups = _group_sources(sources)
            lines = ["## Gefundene Quellen", ""]
            for display_rank, group in enumerate(groups[:6], start=1):
                source = group[0]
                metadata = _metadata(source)
                title = _escape_markdown(source.get("name") or "Quelle")
                location = _location(metadata)
                relevance = (
                    _relevance_text(source.get("score") or metadata.get("score"))
                    if show_scores
                    else ""
                )
                hit_count = "" if len(group) == 1 else f" · {len(group)} Treffer"
                lines.append(f"### {display_rank}. {title}")
                summary = " · ".join(part for part in (location, relevance) if part)
                if summary or hit_count:
                    lines.append(f"**{summary}{hit_count}**")
                actions = _actions(source, metadata)
                if actions:
                    lines.append(f"**Aktionen:** {actions}")
                snippet = _clean_snippet(source.get("text") or source.get("snippet") or "")
                if snippet:
                    lines.append("")
                    lines.extend(_blockquote(_compact(snippet, 420)))
                if show_debug:
                    debug = _debug_parts(metadata)
                    if debug:
                        lines.append("")
                        lines.append(f"Debug: {' · '.join(debug)}")
                lines.append("")
            return "\\n".join(lines).rstrip()


        def _group_sources(sources):
            grouped = {}
            for source in sources:
                metadata = _metadata(source)
                key = (
                    metadata.get("path")
                    or metadata.get("document_id")
                    or metadata.get("document_name")
                    or source.get("name")
                    or "Quelle"
                )
                grouped.setdefault(str(key), []).append(source)
            groups = list(grouped.values())
            for group in groups:
                group.sort(key=lambda item: (_score_sort(item), _rank_sort(item)))
            groups.sort(key=lambda group: (_score_sort(group[0]), _rank_sort(group[0])))
            return groups


        def _score_sort(source):
            score = _score_float(source.get("score") or _metadata(source).get("score"))
            return -1.0 if score is None else -score


        def _rank_sort(source):
            try:
                return int(source.get("rank") or _metadata(source).get("rank") or 9999)
            except Exception:
                return 9999


        def _metadata(source):
            metadata = source.get("source_metadata")
            if isinstance(metadata, dict):
                return metadata
            items = source.get("metadata")
            if isinstance(items, list) and items and isinstance(items[0], dict):
                return items[0]
            return {}


        def _location(metadata):
            parts = []
            if metadata.get("page") not in (None, ""):
                parts.append(f"Seite {metadata.get('page')}")
            if metadata.get("line") not in (None, ""):
                parts.append(f"Zeile {metadata.get('line')}")
            return " · ".join(parts) or "Fundstelle nicht angegeben"


        def _actions(source, metadata):
            links = []
            if source.get("preview_url") or source.get("url"):
                links.append(f"[Preview öffnen]({source.get('preview_url') or source.get('url')})")
            if source.get("original_url") or metadata.get("original_url"):
                original = source.get("original_url") or metadata.get("original_url")
                links.append(f"[Original öffnen]({original})")
            return " · ".join(links)


        def _debug_parts(metadata):
            parts = []
            if metadata.get("chunk_id"):
                parts.append(f"Chunk `{_escape_markdown(str(metadata['chunk_id'])[:12])}`")
            if metadata.get("document_id"):
                parts.append(f"Dokument `{_escape_markdown(str(metadata['document_id'])[:12])}`")
            if metadata.get("dataset_id"):
                parts.append(f"Dataset `{_escape_markdown(str(metadata['dataset_id'])[:12])}`")
            if metadata.get("repo_id"):
                parts.append(f"Repo `{_escape_markdown(str(metadata['repo_id'])[:12])}`")
            return parts


        def _relevance_text(score):
            formatted = _format_score(score)
            if formatted:
                return f"Relevanz {_relevance(score)} ({formatted})"
            return "Relevanz unbekannt"


        def _relevance(score):
            value = _score_float(score)
            if value is None:
                return "unbekannt"
            if value >= 0.8:
                return "hoch"
            if value >= 0.55:
                return "mittel"
            return "niedrig"


        def _format_score(score):
            value = _score_float(score)
            if value is None:
                return ""
            return f"{value:.0%}"


        def _score_float(score):
            try:
                value = float(score)
            except Exception:
                return None
            if value > 1:
                value = value / 100
            return max(0.0, min(1.0, value))


        def _blockquote(text):
            return [
                f"> {_escape_markdown(line)}" if line else ">"
                for line in str(text).splitlines()
            ]


        def _compact(value, limit=220):
            clean = _clean(value)
            return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


        def _clean_snippet(value):
            clean = str(value or "")
            clean = re.sub(r"(?is)<(script|style).*?</\\1>", " ", clean)
            clean = re.sub(r"(?i)</t[dh]>\\s*<t[dh][^>]*>", " | ", clean)
            clean = re.sub(r"(?i)</tr>\\s*<tr[^>]*>", "\\n", clean)
            clean = re.sub(r"(?i)<br\\s*/?>", "\\n", clean)
            clean = re.sub(r"(?s)<[^>]+>", " ", clean)
            clean = unescape(clean)
            clean = "\\n".join(" ".join(line.split()) for line in clean.splitlines())
            return "\\n".join(line for line in clean.splitlines() if line).strip()


        def _clean(value):
            return " ".join(str(value or "").split())


        def _escape_markdown(value):
            replacements = {
                "\\\\": "\\\\\\\\",
                "`": "\\\\`",
                "*": "\\\\*",
                "_": "\\\\_",
                "{": "\\\\{",
                "}": "\\\\}",
                "[": "\\\\[",
                "]": "\\\\]",
                "(": "\\\\(",
                ")": "\\\\)",
                "#": "\\\\#",
                "|": "\\\\|",
                "<": "&lt;",
                ">": "&gt;",
            }
            return "".join(replacements.get(char, char) for char in str(value or ""))


        def _string_or_none(value):
            if value in (None, ""):
                return None
            return str(value)
        '''
    ).strip()
