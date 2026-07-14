from __future__ import annotations

from seafile_ragflow_connector.config.inventory import (
    configured_limited_settings,
    settings_inventory,
    settings_inventory_summary,
)
from seafile_ragflow_connector.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "seafile_base_url": "http://seafile.local",
        "seafile_admin_token": "admin-token",
        "seafile_sync_user_token": "sync-token",
        "ragflow_base_url": "http://ragflow.local",
        "ragflow_api_key": "ragflow-token",
        "database_url": "postgresql+psycopg://sync:secret@postgres/db",
        "redis_url": "redis://:secret@redis:6379/0",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_inventory_redacts_secrets_and_exposes_canonical_env_names() -> None:
    inventory = settings_inventory(_settings())
    by_field = {entry["field"]: entry for entry in inventory}

    assert by_field["seafile_admin_token"]["value"] == "***"
    assert by_field["database_url"]["value"] == "***"
    assert by_field["redis_url"]["value"] == "***"
    assert by_field["search_answer_llm_max_tokens"]["value"] == 900
    assert by_field["connector_language"]["env"] == [
        "CONNECTOR_LANGUAGE",
        "LANGUAGE",
    ]
    assert by_field["max_file_size_mb"]["env"] == ["MAX_FILE_SIZE_MB"]


def test_inventory_marks_configured_compatibility_options_honestly() -> None:
    settings = _settings(upload_workers=4, max_file_size_mb=32)

    limited = configured_limited_settings(settings)
    by_field = {entry["field"]: entry for entry in limited}

    assert by_field["upload_workers"]["status"] == "reserved"
    assert "max_file_size_mb" not in by_field
    summary = settings_inventory_summary(settings_inventory(settings))
    assert summary["active"] > summary["reserved"]
