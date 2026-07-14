from __future__ import annotations

from typing import Any

from seafile_ragflow_connector.config.settings import Settings
from seafile_ragflow_connector.i18n import localizer_for
from seafile_ragflow_connector.utils.redaction import is_secret_key

_SENSITIVE_FIELDS = {"database_url", "redis_url"}
_NON_SECRET_TOKEN_FIELDS = {"search_answer_llm_max_tokens"}

# Diese Optionen bleiben aus Kompatibilitätsgründen ladbar, steuern im aktuellen
# Laufzeitpfad aber noch kein Verhalten. Das Inventar macht diesen Vertrag
# sichtbar, statt wirksame Schalter vorzutäuschen.
_LIMITED_FIELDS: dict[str, tuple[str, str]] = {
    "search_acl_include_subfolder_permissions": (
        "reserved",
        "acl_subfolders",
    ),
    "search_acl_include_share_links": (
        "reserved",
        "acl_share_links",
    ),
    "seafile_sync_user_email": (
        "informational",
        "sync_user_email",
    ),
    "ragflow_validate_created_dataset": (
        "compatibility",
        "validate_dataset",
    ),
    "preserve_original_filename_in_metadata": (
        "compatibility",
        "preserve_filename",
    ),
    "reparse_on_dataset_settings_change": (
        "reserved",
        "reparse",
    ),
    "full_sync_on_missing_commit": (
        "compatibility",
        "full_sync_fallback",
    ),
    "archive_dataset_when_library_deleted": (
        "reserved",
        "archive_dataset",
    ),
    "max_concurrent_libraries": (
        "deployment",
        "library_concurrency",
    ),
    "upload_workers": (
        "reserved",
        "upload_workers",
    ),
    "parse_workers": (
        "reserved",
        "parse_workers",
    ),
    "ragflow_upload_batch_size": (
        "reserved",
        "upload_batch",
    ),
    "ragflow_parse_batch_size": (
        "reserved",
        "parse_batch",
    ),
    "ragflow_max_inflight_documents": (
        "reserved",
        "inflight",
    ),
    "cache_dir": (
        "deployment",
        "runtime_path",
    ),
    "temp_dir": (
        "deployment",
        "runtime_path",
    ),
    "allow_outbound_internet": (
        "reserved",
        "outbound_policy",
    ),
    "disable_telemetry": (
        "reserved",
        "telemetry",
    ),
}


def settings_inventory(settings: Settings) -> list[dict[str, Any]]:
    values = settings.model_dump(mode="json")
    configured_fields = settings.model_fields_set
    l10n = localizer_for(settings)
    inventory: list[dict[str, Any]] = []
    for name, field in Settings.model_fields.items():
        env_names = _env_names(name, field.validation_alias)
        status, note_key = _LIMITED_FIELDS.get(name, ("active", ""))
        note = l10n.text(f"cli.doctor.notes.{note_key}") if note_key else ""
        value = values.get(name)
        if name not in _NON_SECRET_TOKEN_FIELDS and (
            name in _SENSITIVE_FIELDS
            or any(is_secret_key(candidate) for candidate in (name, *env_names))
        ):
            value = "***" if value not in (None, "") else value
        inventory.append(
            {
                "field": name,
                "env": env_names,
                "configured": name in configured_fields,
                "status": status,
                "note": note,
                "value": value,
            }
        )
    return inventory


def settings_inventory_summary(inventory: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for entry in inventory:
        status = str(entry["status"])
        summary[status] = summary.get(status, 0) + 1
    return dict(sorted(summary.items()))


def configured_limited_settings(settings: Settings) -> list[dict[str, str]]:
    return [
        {
            "field": str(entry["field"]),
            "status": str(entry["status"]),
            "note": str(entry["note"]),
        }
        for entry in settings_inventory(settings)
        if entry["configured"] and entry["status"] in {"reserved", "compatibility"}
    ]


def _env_names(field_name: str, validation_alias: Any) -> list[str]:
    if isinstance(validation_alias, str):
        return [validation_alias]
    choices = getattr(validation_alias, "choices", None)
    if choices:
        return [str(choice) for choice in choices]
    return [field_name.upper()]
