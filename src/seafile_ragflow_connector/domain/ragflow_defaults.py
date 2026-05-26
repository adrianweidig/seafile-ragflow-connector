from __future__ import annotations

from typing import Any

RAGFLOW_REFERENCE_METADATA_FIELDS = (
    "repo_id",
    "path",
    "source_path",
    "source_extension",
    "file_type",
    "ingestion_strategy",
    "source_sha256",
    "seafile_obj_id",
    "seafile_mtime",
    "seafile_size",
    "document_name",
)


def build_template_dataset_payload(name: str) -> dict[str, Any]:
    """Build a conservative RAGFlow dataset template for document-heavy RAG."""
    return {
        "name": name,
        "description": (
            "Automatisch angelegtes Connector-Template für Seafile-RAG. "
            "Optimiert für DeepDOC-Layout, Seitenpositionen und robuste "
            "Dokumenten-Metadaten ohne parsezeitteure LLM-Zusatzfragen."
        ),
        "permission": "me",
        "chunk_method": "naive",
        "parser_config": {
            "layout_recognize": "DeepDOC",
            "chunk_token_num": 512,
            "delimiter": "\n",
            "auto_keywords": 0,
            "auto_questions": 0,
            "html4excel": False,
            "task_page_size": 12,
            "filename_embd_weight": 0.1,
            "pages": [[1, 1000000]],
            "parent_child": {"use_parent_child": False},
            "raptor": {"use_raptor": False},
            "graphrag": {"use_graphrag": False},
        },
    }


def build_chat_payload(name: str, *, dataset_id: str | None = None) -> dict[str, Any]:
    """Build an idempotent RAGFlow chat payload for connector-owned RAG chats."""
    payload: dict[str, Any] = {
        "name": name,
        "description": (
            "Connector-verwalteter RAG-Chat für OpenWebUI. Nutzt die "
            "synchronisierten Seafile-Dokumente mit Zitaten und Metadaten."
        ),
        "top_n": 10,
        "top_k": 1024,
        "similarity_threshold": 0.1,
        "vector_similarity_weight": 0.35,
        "llm_setting": {
            "temperature": 0.1,
            "top_p": 0.3,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.3,
            "max_tokens": 1200,
        },
        "prompt_config": {
            "system": (
                "Du bist ein präziser RAG-Assistent für OpenWebUI. "
                "Antworte nur auf Basis der bereitgestellten Wissensauszüge. "
                "Wenn die Wissensbasis keine belastbare Antwort enthält, sage das klar. "
                "Nenne relevante Seiten, Dokumentnamen und Metadaten, wenn sie vorhanden sind. "
                "Antworte in der Sprache der Nutzerfrage.\n\n"
                "Wissensbasis:\n{knowledge}\n"
            ),
            "prologue": "Ich beantworte Fragen auf Basis der synchronisierten Seafile-Dokumente.",
            "parameters": [{"key": "knowledge", "optional": False}],
            "empty_response": (
                "Ich habe dazu keine belastbare Stelle im angebundenen Dataset gefunden."
            ),
            "quote": True,
            "keyword": True,
            "refine_multiturn": True,
            "toc_enhance": True,
            "tts": False,
            "use_kg": False,
            "reasoning": False,
            "reference_metadata": {
                "include": True,
                "fields": list(RAGFLOW_REFERENCE_METADATA_FIELDS),
            },
        },
    }
    if dataset_id is not None:
        payload["dataset_ids"] = [dataset_id]
    return payload
