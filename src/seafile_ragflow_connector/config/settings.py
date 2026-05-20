from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple)) else value.split(",")
    return tuple(item.strip().lower() for item in raw_values if item.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="stack.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "production"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    dry_run: bool = False

    connector_dashboard_enabled: bool = False
    connector_dashboard_host: str = "0.0.0.0"
    connector_dashboard_port: int = 8080
    connector_dashboard_max_log_entries: int = 5000
    connector_dashboard_max_event_entries: int = 10000
    connector_dashboard_max_sync_runs: int = 1000
    connector_dashboard_log_page_size: int = 100
    connector_dashboard_max_field_length: int = 4000

    seafile_base_url: str
    seafile_internal_url: str | None = None
    seafile_admin_token: str
    seafile_sync_user_token: str
    seafile_sync_user_email: str | None = None
    seafile_skip_encrypted_libraries: bool = True
    seafile_skip_virtual_repos: bool = True
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

    postgres_host: str = "connector-postgres"
    postgres_port: int = 5432
    postgres_db: str = "seafile_ragflow_sync"
    postgres_user: str = "sync"
    postgres_password: str | None = None
    database_url: str = ""

    redis_host: str = "connector-redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str = ""

    allow_unknown_text_files: bool = True
    allow_extensions_csv: str = Field(default="", validation_alias="ALLOW_EXTENSIONS")
    deny_extensions_csv: str = Field(
        default=".exe,.dll,.so,.zip,.tar,.gz,.7z,.tmp,.part",
        validation_alias="DENY_EXTENSIONS",
    )
    text_extensions_csv: str = Field(
        default=(
            ".ada,.adb,.ads,.txt,.md,.rst,.py,.js,.ts,.java,.c,.cpp,.h,"
            ".sql,.xml,.json,.yaml,.yml,.ini,.cfg,.log"
        ),
        validation_alias="TEXT_EXTENSIONS",
    )
    binary_direct_extensions_csv: str = Field(
        default=".pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg",
        validation_alias="BINARY_DIRECT_EXTENSIONS",
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

    @field_validator("connector_dashboard_port")
    @classmethod
    def validate_dashboard_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            msg = "connector_dashboard_port must be between 1 and 65535"
            raise ValueError(msg)
        return value

    @field_validator(
        "connector_dashboard_max_log_entries",
        "connector_dashboard_max_event_entries",
        "connector_dashboard_max_sync_runs",
        "connector_dashboard_log_page_size",
        "connector_dashboard_max_field_length",
    )
    @classmethod
    def validate_dashboard_positive_int(cls, value: int) -> int:
        if value <= 0:
            msg = "dashboard limits must be positive"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def build_service_urls(self) -> Settings:
        if not self.database_url:
            if not self.postgres_password:
                msg = "DATABASE_URL or POSTGRES_PASSWORD must be set"
                raise ValueError(msg)
            user = quote(self.postgres_user, safe="")
            password = quote(self.postgres_password, safe="")
            database = quote(self.postgres_db, safe="")
            self.database_url = (
                f"postgresql+psycopg://{user}:{password}@"
                f"{self.postgres_host}:{self.postgres_port}/{database}"
            )
        if not self.redis_url:
            self.redis_url = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return self

    @property
    def allow_extensions(self) -> tuple[str, ...]:
        return _split_csv(self.allow_extensions_csv)

    @property
    def deny_extensions(self) -> tuple[str, ...]:
        return _split_csv(self.deny_extensions_csv)

    @property
    def text_extensions(self) -> tuple[str, ...]:
        return _split_csv(self.text_extensions_csv)

    @property
    def binary_direct_extensions(self) -> tuple[str, ...]:
        return _split_csv(self.binary_direct_extensions_csv)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
