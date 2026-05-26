from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from seafile_ragflow_connector.domain.file_classification import FileClassification
from seafile_ragflow_connector.utils.hashing import sha256_bytes, sha256_text


@dataclass(frozen=True)
class IngestionArtifact:
    document_name: str
    content: bytes
    mime_type: str
    source_content_sha256: str
    ingested_content_sha256: str
    metadata: dict[str, str]


def _project_text(path: str, data: bytes, encoding: str | None) -> bytes:
    decoded = data.decode(encoding or "utf-8", errors="replace")
    source_hash = sha256_text(path)[:16]
    header = (
        f"Source path: {path}\n"
        f"Source path hash: {source_hash}\n"
        "\n"
        "----- BEGIN SOURCE CONTENT -----\n"
    )
    footer = "\n----- END SOURCE CONTENT -----\n"
    return (header + decoded + footer).encode("utf-8")


def prepare_ingestion_artifact(
    classification: FileClassification,
    data: bytes,
) -> IngestionArtifact:
    source_hash = sha256_bytes(data)
    base_name = PurePosixPath(classification.path).name or "document"
    path_hash = sha256_text(classification.normalized_path)[:16]

    if classification.ingestion_strategy == "text_projection":
        content = _project_text(
            classification.normalized_path,
            data,
            classification.detected_encoding,
        )
        document_name = f"{path_hash}__{base_name}.txt"
        mime_type = "text/plain"
    elif classification.ingestion_strategy == "direct":
        content = data
        document_name = base_name
        mime_type = classification.detected_mime or "application/octet-stream"
    else:
        msg = f"unsupported ingestion strategy: {classification.ingestion_strategy}"
        raise ValueError(msg)

    return IngestionArtifact(
        document_name=document_name,
        content=content,
        mime_type=mime_type,
        source_content_sha256=source_hash,
        ingested_content_sha256=sha256_bytes(content),
        metadata={
            "source_path": classification.normalized_path,
            "source_extension": classification.source_extension,
            "ingestion_strategy": classification.ingestion_strategy,
        },
    )


def build_ragflow_document_metadata(
    artifact: IngestionArtifact,
    *,
    repo_id: str,
    path: str,
    item: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    metadata: dict[str, Any] = dict(artifact.metadata)
    source_path = metadata.get("source_path") or path
    source_extension = metadata.get("source_extension") or ""
    metadata.update(
        {
            "repo_id": repo_id,
            "path": source_path,
            "source_path": source_path,
            "source_sha256": artifact.source_content_sha256,
            "document_name": artifact.document_name,
            "file_type": source_extension.lstrip(".") or artifact.mime_type,
        }
    )
    if item:
        _set_metadata(metadata, "seafile_obj_id", item.get("id") or item.get("obj_id"))
        _set_metadata(metadata, "seafile_mtime", item.get("mtime"))
        _set_metadata(metadata, "seafile_size", item.get("size"))
    return {
        key: str(value)
        for key, value in metadata.items()
        if value not in (None, "", [], {})
    }


def _set_metadata(metadata: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, "", [], {}):
        metadata[key] = value
