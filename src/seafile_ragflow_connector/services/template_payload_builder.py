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


class TemplateError(ValueError):
    """Raised when a RAGFlow template cannot be used safely."""


def build_dataset_create_payload(
    template: dict[str, Any],
    generated_name: str,
    *,
    append_description: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": generated_name}

    for key in ("avatar", "embedding_model", "permission"):
        if key in template and template[key] is not None:
            payload[key] = template[key]

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
        payload["parser_config"] = template["parser_config"]

    return payload


def dataset_settings_fingerprint(dataset: dict[str, Any]) -> str:
    relevant = {key: dataset.get(key) for key in TEMPLATE_HASH_FIELDS if key in dataset}
    return f"sha256:{sha256_json(relevant)}"

