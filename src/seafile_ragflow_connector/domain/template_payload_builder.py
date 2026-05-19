from __future__ import annotations

import re
from typing import Any

from seafile_ragflow_connector.utils.hashing import sha256_json


DATASET_CREATE_FIELDS = {
    "name",
    "avatar",
    "description",
    "embedding_model",
    "permission",
    "chunk_method",
    "parser_config",
    "parse_type",
    "pipeline_id",
}

TEMPLATE_HASH_FIELDS = (
    "avatar",
    "description",
    "embedding_model",
    "permission",
    "chunk_method",
    "parser_config",
    "parse_type",
    "pipeline_id",
)

NAIVE_PARSER_CONFIG_CREATE_FIELDS = {
    "auto_keywords",
    "auto_questions",
    "chunk_token_num",
    "delimiter",
    "html4excel",
    "layout_recognize",
    "tag_kb_ids",
    "task_page_size",
    "raptor",
    "graphrag",
    "parent_child",
}

RAPTOR_ONLY_CHUNK_METHODS = {"qa", "manual", "paper", "book", "laws", "presentation"}
EMPTY_CONFIG_CHUNK_METHODS = {"table", "picture", "one", "email"}


class TemplateError(ValueError):
    """Raised when a RAGFlow template cannot be used safely."""


def build_dataset_create_payload(
    template: dict[str, Any],
    generated_name: str,
    *,
    append_description: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": generated_name}

    for key in ("avatar", "permission"):
        if key in template and template[key] is not None:
            payload[key] = template[key]
    if _is_create_compatible_embedding_model(template.get("embedding_model")):
        payload["embedding_model"] = template["embedding_model"]

    if template.get("description") is not None:
        payload["description"] = str(template["description"])
    if append_description:
        existing = payload.get("description", "")
        payload["description"] = f"{existing}\n\n{append_description}".strip()

    has_pipeline = template.get("parse_type") is not None or bool(template.get("pipeline_id"))
    has_builtin = bool(template.get("chunk_method")) or template.get("parser_config") is not None
    if has_pipeline and has_builtin:
        msg = "template mixes ingestion pipeline settings with chunk_method/parser_config"
        raise TemplateError(msg)

    if has_pipeline:
        if template.get("parse_type") is None:
            msg = "template pipeline mode requires parse_type"
            raise TemplateError(msg)
        pipeline_id = template.get("pipeline_id")
        if not isinstance(pipeline_id, str) or not re.fullmatch(r"[0-9a-f]{32}", pipeline_id):
            msg = "template pipeline mode requires a 32 character lowercase hex pipeline_id"
            raise TemplateError(msg)
        payload["parse_type"] = template["parse_type"]
        payload["pipeline_id"] = pipeline_id
        return payload

    if template.get("chunk_method"):
        payload["chunk_method"] = template["chunk_method"]
    if template.get("parser_config") is not None:
        payload["parser_config"] = sanitize_parser_config_for_create(
            template.get("chunk_method"),
            template["parser_config"],
        )

    return payload


def dataset_settings_fingerprint(dataset: dict[str, Any]) -> str:
    relevant = {key: dataset.get(key) for key in TEMPLATE_HASH_FIELDS if key in dataset}
    return f"sha256:{sha256_json(relevant)}"


def _is_create_compatible_embedding_model(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    model, separator, provider = value.partition("@")
    return bool(separator and model.strip() and provider.strip())


def sanitize_parser_config_for_create(chunk_method: Any, parser_config: Any) -> Any:
    if not isinstance(parser_config, dict):
        return parser_config
    if chunk_method == "naive":
        return {
            key: value
            for key, value in parser_config.items()
            if key in NAIVE_PARSER_CONFIG_CREATE_FIELDS
        }
    if chunk_method in RAPTOR_ONLY_CHUNK_METHODS:
        return {"raptor": parser_config["raptor"]} if "raptor" in parser_config else {}
    if chunk_method in EMPTY_CONFIG_CHUNK_METHODS:
        return {}
    return parser_config
