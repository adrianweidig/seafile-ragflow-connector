from __future__ import annotations

import re
from dataclasses import dataclass
from textwrap import dedent

from seafile_ragflow_connector.domain.naming import slugify
from seafile_ragflow_connector.utils.hashing import sha256_json, sha256_text

ARTIFACT_VERSION = "4"
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
        "DATASET_ID": inputs.dataset_id,
        "TOP_K": 8,
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
        "DATASET_ID": inputs.dataset_id,
        "RAGFLOW_CHAT_ID": inputs.ragflow_chat_id or "",
        "MODEL_ID": model_name,
        "MODEL_NAME": model_name,
        "TOP_K": 8,
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
    return dedent(
        '''
        """
        title: RAGFlow Dataset Search
        author: Seafile RAGFlow Connector
        version: 1.2.1
        owner: seafile-ragflow-connector
        artifact_version: 4
        """

        import httpx
        from pydantic import BaseModel, Field


        class Tools:
            class Valves(BaseModel):
                ARTIFACT_ID: str = Field(default="")
                CONNECTOR_PROXY_BASE_URL: str = Field(default="")
                CONNECTOR_PROXY_SHARED_SECRET: str = Field(default="")
                CONNECTOR_PROXY_VERIFY_SSL: bool = Field(default=True)
                CONNECTOR_PROXY_CA_BUNDLE: str = Field(default="")
                DATASET_ID: str = Field(default="")
                TOP_K: int = Field(default=8, ge=1, le=20)

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
                try:
                    async with httpx.AsyncClient(
                        timeout=60,
                        verify=_httpx_verify(
                            self.valves.CONNECTOR_PROXY_VERIFY_SSL,
                            self.valves.CONNECTOR_PROXY_CA_BUNDLE,
                        ),
                    ) as client:
                        url = (
                            self.valves.CONNECTOR_PROXY_BASE_URL.rstrip("/")
                            + "/api/openwebui/proxy/query"
                        )
                        response = await client.post(url, json=payload, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                except Exception:
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

                sources = data.get("sources") or []
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
                return data.get("answer") or _source_markdown(sources)


        def _source_markdown(sources):
            if not sources:
                return "Keine passenden Quellen gefunden."
            lines = [
                "## Gefundene Quellen",
                "",
                "| # | Dokument | Fundstelle | Auszug |",
                "|---:|---|---|---|",
            ]
            for index, source in enumerate(sources, start=1):
                title = source.get("name") or source.get("document_name") or "Quelle"
                url = source.get("url") or source.get("preview_url")
                original_url = source.get("original_url")
                snippet = source.get("text") or source.get("snippet") or ""
                document = f"[{_clean(title)}]({url})" if url else _clean(title)
                if original_url and original_url != url:
                    document = f"{document} - [Original öffnen]({original_url})"
                row = (
                    f"| {index} | {document} | {_source_locator(source)} | "
                    f"{_compact_cell(snippet)} |"
                )
                lines.append(row)
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


        def _compact_cell(value, limit=220):
            clean = _clean(value).replace("|", "\\\\|")
            if len(clean) <= limit:
                return clean or "-"
            return clean[: limit - 3].rstrip() + "..."


        def _clean(value):
            return " ".join(str(value or "").split())


        def _httpx_verify(verify_ssl, ca_bundle):
            if not bool(verify_ssl):
                return False
            ca_path = str(ca_bundle or "").strip()
            return ca_path or True
        '''
    ).strip()


def _pipe_content() -> str:
    return dedent(
        '''
        """
        title: RAGFlow Dataset Pipe
        author: Seafile RAGFlow Connector
        version: 1.2.1
        owner: seafile-ragflow-connector
        artifact_version: 4
        """

        import httpx
        from pydantic import BaseModel, Field


        class Pipe:
            class Valves(BaseModel):
                ARTIFACT_ID: str = Field(default="")
                CONNECTOR_PROXY_BASE_URL: str = Field(default="")
                CONNECTOR_PROXY_SHARED_SECRET: str = Field(default="")
                CONNECTOR_PROXY_VERIFY_SSL: bool = Field(default=True)
                CONNECTOR_PROXY_CA_BUNDLE: str = Field(default="")
                DATASET_ID: str = Field(default="")
                RAGFLOW_CHAT_ID: str = Field(default="")
                MODEL_ID: str = Field(default="")
                MODEL_NAME: str = Field(default="")
                TOP_K: int = Field(default=8, ge=1, le=20)

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
                    "model": "model",
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
                try:
                    async with httpx.AsyncClient(
                        timeout=180,
                        verify=_httpx_verify(
                            self.valves.CONNECTOR_PROXY_VERIFY_SSL,
                            self.valves.CONNECTOR_PROXY_CA_BUNDLE,
                        ),
                    ) as client:
                        url = (
                            self.valves.CONNECTOR_PROXY_BASE_URL.rstrip("/")
                            + "/api/openwebui/proxy/chat"
                        )
                        response = await client.post(url, json=payload, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                except Exception:
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
                    return "Die RAGFlow-Antwort konnte nicht erzeugt werden."

                sources = data.get("sources") or []
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
                    answer = answer + "\\n\\n" + _source_markdown(sources)
                return answer or _source_markdown(sources) or "RAGFlow hat keine Antwort geliefert."


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


        def _httpx_verify(verify_ssl, ca_bundle):
            if not bool(verify_ssl):
                return False
            ca_path = str(ca_bundle or "").strip()
            return ca_path or True


        def _source_markdown(sources):
            if not sources:
                return ""
            lines = [
                "## Gefundene Quellen",
                "",
                "| # | Dokument | Fundstelle | Auszug |",
                "|---:|---|---|---|",
            ]
            for index, source in enumerate(sources, start=1):
                title = source.get("name") or source.get("document_name") or "Quelle"
                url = source.get("url") or source.get("preview_url")
                original_url = source.get("original_url")
                snippet = source.get("text") or source.get("snippet") or ""
                document = f"[{_clean(title)}]({url})" if url else _clean(title)
                if original_url and original_url != url:
                    document = f"{document} - [Original öffnen]({original_url})"
                row = (
                    f"| {index} | {document} | {_source_locator(source)} | "
                    f"{_compact_cell(snippet)} |"
                )
                lines.append(row)
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


        def _compact_cell(value, limit=220):
            clean = _clean(value).replace("|", "\\\\|")
            if len(clean) <= limit:
                return clean or "-"
            return clean[: limit - 3].rstrip() + "..."


        def _clean(value):
            return " ".join(str(value or "").split())
        '''
    ).strip()
