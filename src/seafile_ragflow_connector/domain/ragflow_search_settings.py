from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import httpx

from seafile_ragflow_connector.clients.http import ApiError

DEFAULT_SEARCH_TEMPLATE_NAME = "search_template"
DEFAULT_TEMPLATE_SOURCE_ORDER = ("search_app", "chat", "builtin")
MAX_RETRIEVAL_PAGE_SIZE = 50


@dataclass(frozen=True)
class RagflowRetrievalSettings:
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    top_n: int = 8
    top_k: int = 1024
    page_size: int | None = None
    rerank_id: str | None = None
    keyword: bool = True
    highlight: bool = True
    cross_languages: tuple[str, ...] = ()
    use_kg: bool = False
    toc_enhance: bool = False
    metadata_condition: dict[str, Any] | None = None

    def to_search_config(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "similarity_threshold": self.similarity_threshold,
            "vector_similarity_weight": self.vector_similarity_weight,
            "top_n": self.top_n,
            "top_k": self.top_k,
            "keyword": self.keyword,
            "highlight": self.highlight,
            "use_kg": self.use_kg,
            "toc_enhance": self.toc_enhance,
        }
        if self.page_size is not None:
            payload["page_size"] = self.page_size
        if self.rerank_id:
            payload["rerank_id"] = self.rerank_id
        if self.cross_languages:
            payload["cross_languages"] = list(self.cross_languages)
        if self.metadata_condition:
            payload["metadata_condition"] = self.metadata_condition
        return payload

    def to_retrieval_options(
        self,
        *,
        requested_results: int,
        max_page_size: int = MAX_RETRIEVAL_PAGE_SIZE,
        include_rerank: bool = True,
        compatibility_mode: bool = False,
    ) -> dict[str, Any]:
        page_size = self.page_size or max(requested_results, self.top_n)
        page_size = _bounded_int(page_size, minimum=1, maximum=max_page_size)
        payload: dict[str, Any] = {
            "page_size": page_size,
            "similarity_threshold": self.similarity_threshold,
            "vector_similarity_weight": self.vector_similarity_weight,
            "top_k": max(1, self.top_k),
        }
        if compatibility_mode:
            return payload
        payload.update(
            {
                "keyword": self.keyword,
                "highlight": self.highlight,
                "use_kg": self.use_kg,
                "toc_enhance": self.toc_enhance,
            }
        )
        if include_rerank and self.rerank_id:
            payload["rerank_id"] = self.rerank_id
        if self.cross_languages:
            payload["cross_languages"] = list(self.cross_languages)
        if self.metadata_condition:
            payload["metadata_condition"] = self.metadata_condition
        return payload


@dataclass(frozen=True)
class RagflowRetrievalOverrides:
    similarity_threshold: float | None = None
    vector_similarity_weight: float | None = None
    top_n: int | None = None
    top_k: int | None = None
    rerank_id: str | None = None
    keyword: bool | None = None
    highlight: bool | None = None
    cross_languages: tuple[str, ...] | None = None
    use_kg: bool | None = None
    toc_enhance: bool | None = None


@dataclass(frozen=True)
class RagflowSearchTemplateConfig:
    enabled: bool = True
    name: str = DEFAULT_SEARCH_TEMPLATE_NAME
    source_order: tuple[str, ...] = DEFAULT_TEMPLATE_SOURCE_ORDER
    required: bool = False
    auto_create: bool = False
    overrides: RagflowRetrievalOverrides = RagflowRetrievalOverrides()


@dataclass(frozen=True)
class ResolvedSearchTemplate:
    source: str
    name: str
    settings: RagflowRetrievalSettings
    template_id: str | None = None
    warnings: tuple[str, ...] = ()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "search_template_source": self.source,
            "search_template_name": self.name,
            "search_template_id": self.template_id,
            "candidate_top_k": self.settings.top_k,
            "top_n": self.settings.top_n,
            "similarity_threshold": self.settings.similarity_threshold,
            "vector_similarity_weight": self.settings.vector_similarity_weight,
            "rerank_enabled": bool(self.settings.rerank_id),
            "highlight_enabled": self.settings.highlight,
            "keyword_enabled": self.settings.keyword,
            "use_kg": self.settings.use_kg,
            "toc_enhance": self.settings.toc_enhance,
            "template_warnings": list(self.warnings),
        }


BUILTIN_RETRIEVAL_SETTINGS = RagflowRetrievalSettings()


def config_from_settings(settings: Any) -> RagflowSearchTemplateConfig:
    source_order = _source_order(
        getattr(settings, "search_ragflow_template_source_order_csv", "")
        or getattr(settings, "search_ragflow_template_source_order", "")
    )
    return RagflowSearchTemplateConfig(
        enabled=bool(getattr(settings, "ragflow_search_template_enabled", True)),
        name=str(
            getattr(settings, "ragflow_search_template_name", DEFAULT_SEARCH_TEMPLATE_NAME)
            or DEFAULT_SEARCH_TEMPLATE_NAME
        ).strip(),
        source_order=source_order,
        required=bool(getattr(settings, "ragflow_search_template_required", False)),
        auto_create=bool(getattr(settings, "ragflow_search_template_auto_create", False)),
        overrides=RagflowRetrievalOverrides(
            similarity_threshold=getattr(settings, "search_ragflow_similarity_threshold", None),
            vector_similarity_weight=getattr(
                settings,
                "search_ragflow_vector_similarity_weight",
                None,
            ),
            top_n=getattr(settings, "search_ragflow_top_n", None),
            top_k=getattr(settings, "search_ragflow_candidate_top_k", None),
            rerank_id=_clean_optional(getattr(settings, "search_ragflow_rerank_id", None)),
            keyword=getattr(settings, "search_ragflow_keyword", None),
            highlight=getattr(settings, "search_ragflow_highlight", None),
            cross_languages=_optional_languages(
                getattr(settings, "search_ragflow_cross_languages_csv", "")
            ),
            use_kg=getattr(settings, "search_ragflow_use_kg", None),
            toc_enhance=getattr(settings, "search_ragflow_toc_enhance", None),
        ),
    )


def resolve_search_template(
    client: Any,
    config: RagflowSearchTemplateConfig,
) -> ResolvedSearchTemplate:
    warnings: list[str] = []
    if not config.enabled:
        return _resolved_builtin(config, warnings=("template_disabled",))

    for source in config.source_order:
        if source == "search_app":
            resolved = _resolve_search_app(client, config, warnings)
            if resolved is not None:
                return _with_overrides(resolved, config.overrides)
            continue
        if source == "chat":
            resolved = _resolve_chat(client, config, warnings)
            if resolved is not None:
                return _with_overrides(resolved, config.overrides)
            continue
        if source == "builtin":
            return _with_overrides(
                _resolved_builtin(config, warnings=tuple(warnings)),
                config.overrides,
            )

    if config.required:
        msg = f"RAGFlow search template not found: {config.name}"
        raise RuntimeError(msg)
    return _with_overrides(_resolved_builtin(config, warnings=tuple(warnings)), config.overrides)


def ensure_search_template(
    client: Any,
    config: RagflowSearchTemplateConfig,
    *,
    native_dataset_ids: Sequence[str] | None = None,
    chat_model_id: str | None = None,
) -> ResolvedSearchTemplate:
    resolved = resolve_search_template(client, config)
    if not config.enabled or "search_app" not in config.source_order:
        return resolved

    managed_scope_requested = native_dataset_ids is not None or chat_model_id is not None
    if resolved.source == "search_app":
        if not resolved.template_id:
            return _search_template_update_failure(
                config,
                resolved,
                RuntimeError("RAGFlow search template id is not verifiable"),
            )
        if not managed_scope_requested and not config.required:
            return resolved
        try:
            existing = client.get_search(resolved.template_id)
        except (ApiError, AttributeError, httpx.RequestError) as exc:
            return _search_template_update_failure(config, resolved, exc)
        if not isinstance(existing, dict):
            return _search_template_update_failure(
                config,
                resolved,
                RuntimeError("RAGFlow search owner or detail could not be verified"),
            )
        if not managed_scope_requested:
            return replace(resolved, settings=settings_from_search_app(existing))
        payload = _managed_search_template_payload(
            config,
            resolved,
            native_dataset_ids=native_dataset_ids,
            chat_model_id=chat_model_id,
        )
        if not _search_template_needs_update(existing, payload):
            return resolved
        try:
            _verify_artifact_owner_for_mutation(client)
            updated = client.update_search(resolved.template_id, payload)
        except (ApiError, AttributeError, httpx.RequestError) as exc:
            return _search_template_update_failure(config, resolved, exc)
        return ResolvedSearchTemplate(
            source="search_app",
            name=config.name,
            template_id=_optional_id(updated) or resolved.template_id,
            settings=resolved.settings,
            warnings=resolved.warnings,
        )

    if not config.auto_create:
        return resolved
    payload = _managed_search_template_payload(
        config,
        resolved,
        native_dataset_ids=native_dataset_ids,
        chat_model_id=chat_model_id,
    )
    try:
        _verify_artifact_owner_for_mutation(client)
        _claim_search_template_create(client, config.name)
        created = client.create_search(payload)
    except (ApiError, AttributeError, httpx.RequestError) as exc:
        if config.required:
            msg = f"RAGFlow search template could not be created: {config.name}"
            raise RuntimeError(msg) from exc
        warnings = (*resolved.warnings, "search_app_auto_create_blocked")
        return replace(resolved, warnings=warnings)
    search_id = _optional_id(created)
    try:
        if not search_id:
            raise RuntimeError("RAGFlow search create response did not contain an id")
        created_detail = client.get_search(search_id)
        if not isinstance(created_detail, dict):
            raise RuntimeError("RAGFlow search owner or detail could not be verified")
    except (ApiError, AttributeError, httpx.RequestError, RuntimeError) as exc:
        rollback_warning: str
        rollback_error: Exception | None = None
        if search_id:
            try:
                client.delete_search(search_id)
            except (ApiError, AttributeError, httpx.RequestError, RuntimeError) as delete_exc:
                rollback_warning = "search_app_auto_create_rollback_failed"
                rollback_error = delete_exc
            else:
                rollback_warning = "search_app_auto_create_rolled_back"
        else:
            rollback_warning = "search_app_auto_create_rollback_unavailable"
        if config.required:
            if rollback_error is not None:
                msg = (
                    "RAGFlow search template could not be verified and rollback failed: "
                    f"{config.name}"
                )
                raise RuntimeError(msg) from rollback_error
            msg = f"RAGFlow search template could not be verified: {config.name}"
            raise RuntimeError(msg) from exc
        warnings = (
            *resolved.warnings,
            "search_app_auto_create_unverified",
            rollback_warning,
        )
        return replace(resolved, warnings=warnings)
    return ResolvedSearchTemplate(
        source="search_app",
        name=config.name,
        template_id=search_id,
        settings=resolved.settings,
        warnings=resolved.warnings,
    )


def _verify_artifact_owner_for_mutation(client: Any) -> None:
    if not getattr(client, "artifact_owner_id", None):
        return
    verifier = getattr(client, "verify_artifact_owner", None)
    if not callable(verifier):
        raise ApiError(
            "RAGFlow interactive owner preflight is unavailable",
            status_code=200,
            payload={"owner_preflight_available": False},
        )
    verifier()


def _claim_search_template_create(client: Any, template_name: str) -> None:
    attribute_name = "_connector_search_create_attempts"
    attempts = getattr(client, attribute_name, None)
    if attempts is None:
        attempts = set()
        try:
            setattr(client, attribute_name, attempts)
        except (AttributeError, TypeError) as exc:
            raise ApiError(
                "RAGFlow search create guard is unavailable",
                status_code=200,
                payload={"search_create_guard_available": False},
            ) from exc
    if not isinstance(attempts, set):
        raise ApiError(
            "RAGFlow search create guard is invalid",
            status_code=200,
            payload={"search_create_guard_valid": False},
        )
    if template_name in attempts:
        raise ApiError(
            "RAGFlow search template creation was already attempted",
            status_code=200,
            payload={"search_template": template_name, "duplicate_create_blocked": True},
        )
    attempts.add(template_name)


def _managed_search_template_payload(
    config: RagflowSearchTemplateConfig,
    resolved: ResolvedSearchTemplate,
    *,
    native_dataset_ids: Sequence[str] | None,
    chat_model_id: str | None,
) -> dict[str, Any]:
    search_config = resolved.settings.to_search_config()
    if native_dataset_ids is not None:
        search_config["kb_ids"] = sorted(
            {
                dataset_id
                for value in native_dataset_ids
                if (dataset_id := str(value).strip())
            }
        )
    normalized_model_id = str(chat_model_id or "").strip()
    if normalized_model_id:
        search_config["chat_id"] = normalized_model_id
    return {
        "name": config.name,
        "description": (
            "Connector-verwaltetes Search-Template für nutzernahe RAGFlow-Suchen. "
            "Die nativen Dataset-Bindungen werden aus den aktiven "
            "Connector-Bibliotheken aktualisiert."
        ),
        "search_config": search_config,
    }


def _search_template_needs_update(
    existing: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    if str(existing.get("name") or "") != str(payload["name"]):
        return True
    if str(existing.get("description") or "") != str(payload["description"]):
        return True
    existing_search_config = existing.get("search_config")
    if not isinstance(existing_search_config, dict):
        return True
    desired_search_config = payload["search_config"]
    return any(
        existing_search_config.get(key) != value
        for key, value in desired_search_config.items()
    )


def _search_template_update_failure(
    config: RagflowSearchTemplateConfig,
    resolved: ResolvedSearchTemplate,
    exc: Exception,
) -> ResolvedSearchTemplate:
    if config.required:
        msg = f"RAGFlow search template could not be updated: {config.name}"
        raise RuntimeError(msg) from exc
    return replace(
        resolved,
        warnings=(*resolved.warnings, "search_app_update_unsupported"),
    )


def settings_from_search_app(search_app: dict[str, Any]) -> RagflowRetrievalSettings:
    search_config = search_app.get("search_config")
    if not isinstance(search_config, dict):
        search_config = {}
    return settings_from_mapping(search_config)


def settings_from_chat(chat: dict[str, Any]) -> RagflowRetrievalSettings:
    settings = settings_from_mapping(chat)
    prompt_config = chat.get("prompt_config")
    if isinstance(prompt_config, dict):
        keyword = _optional_bool(prompt_config.get("keyword"))
        use_kg = _optional_bool(prompt_config.get("use_kg"))
        toc_enhance = _optional_bool(prompt_config.get("toc_enhance"))
        cross_languages = _languages(prompt_config.get("cross_languages"))
        settings = replace(
            settings,
            keyword=settings.keyword if keyword is None else keyword,
            cross_languages=cross_languages or settings.cross_languages,
            use_kg=settings.use_kg if use_kg is None else use_kg,
            toc_enhance=settings.toc_enhance if toc_enhance is None else toc_enhance,
        )
    return settings


def settings_from_mapping(mapping: dict[str, Any]) -> RagflowRetrievalSettings:
    base = BUILTIN_RETRIEVAL_SETTINGS
    similarity_threshold = _optional_float(mapping.get("similarity_threshold"))
    vector_similarity_weight = _optional_float(mapping.get("vector_similarity_weight"))
    keyword = _optional_bool(mapping.get("keyword"))
    highlight = _optional_bool(mapping.get("highlight"))
    return RagflowRetrievalSettings(
        similarity_threshold=(
            base.similarity_threshold
            if similarity_threshold is None
            else similarity_threshold
        ),
        vector_similarity_weight=(
            base.vector_similarity_weight
            if vector_similarity_weight is None
            else vector_similarity_weight
        ),
        top_n=_optional_int(mapping.get("top_n")) or base.top_n,
        top_k=_optional_int(mapping.get("top_k")) or base.top_k,
        page_size=_optional_int(mapping.get("page_size")),
        rerank_id=_clean_optional(mapping.get("rerank_id")),
        keyword=base.keyword if keyword is None else keyword,
        highlight=base.highlight if highlight is None else highlight,
        cross_languages=_languages(mapping.get("cross_languages")),
        use_kg=bool(_optional_bool(mapping.get("use_kg")) or False),
        toc_enhance=bool(_optional_bool(mapping.get("toc_enhance")) or False),
        metadata_condition=_metadata_condition(mapping.get("metadata_condition")),
    )


def apply_retrieval_settings_to_chat_payload(
    payload: dict[str, Any],
    resolved: ResolvedSearchTemplate,
) -> dict[str, Any]:
    updated = dict(payload)
    search = resolved.settings
    updated.update(
        {
            "top_n": search.top_n,
            "top_k": search.top_k,
            "similarity_threshold": search.similarity_threshold,
            "vector_similarity_weight": search.vector_similarity_weight,
            "rerank_id": search.rerank_id or "",
        }
    )
    prompt_config = dict(updated.get("prompt_config") or {})
    prompt_config.update(
        {
            "keyword": search.keyword,
            "toc_enhance": search.toc_enhance,
            "use_kg": search.use_kg,
        }
    )
    if search.cross_languages:
        prompt_config["cross_languages"] = list(search.cross_languages)
    updated["prompt_config"] = prompt_config
    return updated


def _resolve_search_app(
    client: Any,
    config: RagflowSearchTemplateConfig,
    warnings: list[str],
) -> ResolvedSearchTemplate | None:
    try:
        searches = client.list_searches(keywords=config.name, page_size=20)
    except (ApiError, AttributeError, httpx.RequestError):
        warnings.append("search_app_api_unavailable")
        return None
    matches = [item for item in searches if item.get("name") == config.name]
    if not matches:
        return None
    search_app = matches[0]
    search_id = _optional_id(search_app)
    if search_id:
        try:
            full = client.get_search(search_id)
            if isinstance(full, dict):
                search_app = full
        except (ApiError, httpx.RequestError):
            warnings.append("search_app_detail_unavailable")
    return ResolvedSearchTemplate(
        source="search_app",
        name=config.name,
        template_id=_optional_id(search_app),
        settings=settings_from_search_app(search_app),
        warnings=tuple(warnings),
    )


def _resolve_chat(
    client: Any,
    config: RagflowSearchTemplateConfig,
    warnings: list[str],
) -> ResolvedSearchTemplate | None:
    try:
        chats = client.list_chats(name=config.name)
    except (ApiError, AttributeError, httpx.RequestError):
        warnings.append("chat_template_api_unavailable")
        return None
    matches = [item for item in chats if item.get("name") == config.name]
    if not matches:
        return None
    chat = matches[0]
    chat_id = _optional_id(chat)
    if chat_id:
        try:
            full = client.get_chat(chat_id)
            if isinstance(full, dict):
                chat = full
        except (ApiError, httpx.RequestError):
            warnings.append("chat_template_detail_unavailable")
    return ResolvedSearchTemplate(
        source="chat",
        name=config.name,
        template_id=_optional_id(chat),
        settings=settings_from_chat(chat),
        warnings=tuple(warnings),
    )


def _resolved_builtin(
    config: RagflowSearchTemplateConfig,
    *,
    warnings: tuple[str, ...] = (),
) -> ResolvedSearchTemplate:
    return ResolvedSearchTemplate(
        source="builtin",
        name=config.name,
        settings=BUILTIN_RETRIEVAL_SETTINGS,
        warnings=warnings,
    )


def _with_overrides(
    resolved: ResolvedSearchTemplate,
    overrides: RagflowRetrievalOverrides,
) -> ResolvedSearchTemplate:
    settings = resolved.settings
    values: dict[str, Any] = {}
    for field_name in (
        "similarity_threshold",
        "vector_similarity_weight",
        "top_n",
        "top_k",
        "rerank_id",
        "keyword",
        "highlight",
        "cross_languages",
        "use_kg",
        "toc_enhance",
    ):
        value = getattr(overrides, field_name)
        if value is not None:
            values[field_name] = value
    if values:
        settings = replace(settings, **values)
    return replace(resolved, settings=settings)


def _source_order(value: str | tuple[str, ...]) -> tuple[str, ...]:
    raw = value if isinstance(value, tuple) else tuple(str(value or "").split(","))
    result = tuple(item.strip().lower() for item in raw if item.strip())
    valid = tuple(item for item in result if item in DEFAULT_TEMPLATE_SOURCE_ORDER)
    return valid or DEFAULT_TEMPLATE_SOURCE_ORDER


def _optional_languages(value: str | None) -> tuple[str, ...] | None:
    languages = _languages(value)
    return languages or None


def _languages(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _metadata_condition(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    return None


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, result))


def _optional_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _clean_optional(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _bounded_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _optional_id(value: dict[str, Any]) -> str | None:
    item = value.get("id") or value.get("search_id")
    if item in (None, ""):
        return None
    return str(item)
