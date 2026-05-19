from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = value.split(",")
    return tuple(item.strip().lower() for item in raw_values if item.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="stack.env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "production"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    dry_run: bool = False

    seafile_base_url: str
    seafile_internal_url: str | None = None
    seafile_admin_token: str
    seafile_sync_user_token: str
    seafile_sync_user_email: str | None = None
    seafile_rewrite_download_urls: bool = False
    seafile_download_rewrite_from: str | None = None
    seafile_download_rewrite_to: str | None = None

    ragflow_base_url: str
    ragflow_internal_url: str | None = None
    ragflow_api_key: str
    ragflow_template_dataset_name: str = "connector_template"
    ragflow_template_required: bool = True
    ragflow_template_refresh_seconds: int = 300
    ragflow_refresh_dataset_settings: bool = True
    ragflow_validate_created_dataset: bool = True

    database_url: str
    redis_url: str

    allow_unknown_text_files: bool = True
    allow_extensions: tuple[str, ...] = ()
    deny_extensions: tuple[str, ...] = (
        ".exe",
        ".dll",
        ".so",
        ".zip",
        ".tar",
        ".gz",
        ".7z",
        ".tmp",
        ".part",
    )
    text_extensions: tuple[str, ...] = (
        ".ada",
        ".adb",
        ".ads",
        ".txt",
        ".md",
        ".rst",
        ".py",
        ".js",
        ".ts",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".sql",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".log",
    )
    binary_direct_extensions: tuple[str, ...] = (
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
    )
    default_text_ingestion_strategy: Literal["direct", "text_projection"] = "text_projection"
    preserve_original_filename_in_metadata: bool = True
    max_file_size_mb: int = 1024
    exclude_regex: str | None = r"(^/\.|/\.|~$|\.tmp$|\.part$)"

    dataset_settings_source: Literal["ragflow_current"] = "ragflow_current"
    reparse_on_dataset_settings_change: bool = False

    discovery_interval_seconds: int = 300
    delta_sync_interval_seconds: int = 300
    reconcile_interval_seconds: int = 21600
    full_sync_on_missing_commit: bool = True

    delete_ragflow_docs_on_seafile_delete: bool = True
    delete_dataset_when_library_deleted: bool = False
    archive_dataset_when_library_deleted: bool = True

    max_concurrent_libraries: int = 2
    upload_workers: int = 2
    parse_workers: int = 1
    ragflow_upload_batch_size: int = 8
    ragflow_parse_batch_size: int = 16
    ragflow_max_inflight_documents: int = 64

    job_max_attempts: int = 5
    job_retry_base_seconds: int = 30
    job_retry_max_seconds: int = 3600

    cache_dir: Path = Path("/cache")
    temp_dir: Path = Path("/cache/tmp")
    allow_outbound_internet: bool = False
    disable_telemetry: bool = True

    @field_validator(
        "allow_extensions",
        "deny_extensions",
        "text_extensions",
        "binary_direct_extensions",
        mode="before",
    )
    @classmethod
    def split_extension_csv(cls, value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
        return _split_csv(value)

    @field_validator("seafile_base_url", "ragflow_base_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("max_file_size_mb")
    @classmethod
    def validate_max_file_size(cls, value: int) -> int:
        if value <= 0:
            msg = "max_file_size_mb must be positive"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

