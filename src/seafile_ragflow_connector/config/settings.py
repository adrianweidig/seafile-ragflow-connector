from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from seafile_ragflow_connector.clients.tls import (
    build_service_httpx_verify,
    validate_tls_file,
)


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
        populate_by_name=True,
    )

    app_env: str = "production"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    dry_run: bool = False
    ssl_cert_file: str | None = Field(default=None, validation_alias="SSL_CERT_FILE")
    requests_ca_bundle: str | None = Field(default=None, validation_alias="REQUESTS_CA_BUNDLE")
    connector_ca_bundle: str | None = None

    connector_dashboard_enabled: bool = False
    connector_dashboard_host: str = "0.0.0.0"  # nosec B104
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
    seafile_verify_ssl: bool = True
    seafile_ca_bundle: str | None = None
    seafile_rewrite_download_urls: bool = False
    seafile_download_rewrite_from: str | None = None
    seafile_download_rewrite_to: str | None = None
    seafile_file_url_template: str | None = None

    ragflow_base_url: str
    ragflow_internal_url: str | None = None
    ragflow_api_key: str
    ragflow_template_dataset_name: str = "connector_template"
    ragflow_template_required: bool = True
    ragflow_verify_ssl: bool = True
    ragflow_ca_bundle: str | None = None
    ragflow_template_refresh_seconds: int = 300
    ragflow_refresh_dataset_settings: bool = True
    ragflow_validate_created_dataset: bool = True
    ragflow_public_base_url: str | None = None
    ragflow_document_url_template: str | None = None

    openwebui_integration_enabled: bool = False
    openwebui_base_url: str = "http://localhost:3000"
    openwebui_admin_api_key: str | None = None
    openwebui_sync_on_startup: bool = True
    openwebui_sync_mode: Literal["disabled", "dry-run", "sync", "repair"] = "sync"
    openwebui_create_tools: bool = True
    openwebui_create_pipes: bool = True
    openwebui_request_timeout_seconds: int = 180
    openwebui_verify_ssl: bool = True
    openwebui_ca_bundle: str | None = None
    openwebui_function_namespace: str = "ragflow"
    openwebui_source_preview_mode: Literal[
        "ragflow_link",
        "connector_viewer",
        "citation_only",
        "disabled",
    ] = "ragflow_link"
    openwebui_proxy_public_base_url: str | None = None
    openwebui_proxy_internal_base_url: str | None = None
    openwebui_proxy_shared_secret: str | None = None
    openwebui_proxy_verify_ssl: bool = Field(
        default=True,
        validation_alias=AliasChoices("OPENWEBUI_PROXY_VERIFY_SSL", "CONNECTOR_PROXY_VERIFY_SSL"),
    )
    openwebui_proxy_ca_bundle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENWEBUI_PROXY_CA_BUNDLE", "CONNECTOR_PROXY_CA_BUNDLE"),
    )
    ragflow_client_cert_file: str | None = None
    ragflow_client_key_file: str | None = None
    seafile_client_cert_file: str | None = None
    seafile_client_key_file: str | None = None
    connector_proxy_client_cert_file: str | None = None
    connector_proxy_client_key_file: str | None = None
    openwebui_sync_interval_seconds: int = 300
    openwebui_dataset_allowlist_csv: str = Field(
        default="",
        validation_alias="OPENWEBUI_DATASET_ALLOWLIST",
    )

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
    delete_dataset_when_library_deleted: bool = True
    archive_dataset_when_library_deleted: bool = False

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
        "seafile_base_url",
        "ragflow_base_url",
        "ragflow_public_base_url",
        "openwebui_base_url",
        "openwebui_proxy_public_base_url",
        "openwebui_proxy_internal_base_url",
    )
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @field_validator(
        "connector_ca_bundle",
        "ssl_cert_file",
        "requests_ca_bundle",
        "seafile_ca_bundle",
        "ragflow_ca_bundle",
        "openwebui_ca_bundle",
        "openwebui_proxy_ca_bundle",
        "ragflow_client_cert_file",
        "ragflow_client_key_file",
        "seafile_client_cert_file",
        "seafile_client_key_file",
        "connector_proxy_client_cert_file",
        "connector_proxy_client_key_file",
        mode="before",
    )
    @classmethod
    def strip_optional_path(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

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

    @field_validator("openwebui_request_timeout_seconds", "openwebui_sync_interval_seconds")
    @classmethod
    def validate_openwebui_positive_int(cls, value: int) -> int:
        if value <= 0:
            msg = "openwebui numeric settings must be positive"
            raise ValueError(msg)
        return value

    @field_validator("openwebui_function_namespace")
    @classmethod
    def validate_openwebui_namespace(cls, value: str) -> str:
        namespace = value.strip().lower().replace("-", "_")
        if not namespace or not namespace.replace("_", "").isalnum() or namespace[0].isdigit():
            msg = "OPENWEBUI_FUNCTION_NAMESPACE must be a valid Python identifier prefix"
            raise ValueError(msg)
        return namespace

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
        if self.openwebui_proxy_internal_base_url is None:
            self.openwebui_proxy_internal_base_url = self.openwebui_proxy_public_base_url
        for name in (
            "ragflow_public_base_url",
            "openwebui_proxy_public_base_url",
            "openwebui_proxy_internal_base_url",
        ):
            value = getattr(self, name)
            if value and not _is_http_url(value):
                msg = f"{name.upper()} must be an http or https URL"
                raise ValueError(msg)
        for name in (
            "connector_ca_bundle",
            "ssl_cert_file",
            "requests_ca_bundle",
            "seafile_ca_bundle",
            "ragflow_ca_bundle",
            "openwebui_ca_bundle",
            "openwebui_proxy_ca_bundle",
            "ragflow_client_cert_file",
            "ragflow_client_key_file",
            "seafile_client_cert_file",
            "seafile_client_key_file",
            "connector_proxy_client_cert_file",
            "connector_proxy_client_key_file",
        ):
            value = getattr(self, name)
            if value:
                validate_tls_file(str(value), label=name.upper())
        if self.openwebui_integration_enabled:
            mode = self.openwebui_effective_sync_mode
            writes_openwebui_artifacts = mode in {"sync", "repair"} and (
                self.openwebui_create_tools or self.openwebui_create_pipes
            )
            if mode in {"sync", "repair"} and not self.openwebui_admin_api_key:
                msg = "OPENWEBUI_ADMIN_API_KEY must be set when OpenWebUI sync or repair is enabled"
                raise ValueError(msg)
            if (
                writes_openwebui_artifacts
                and not self.openwebui_proxy_shared_secret
            ):
                msg = (
                    "OPENWEBUI_PROXY_SHARED_SECRET must be set when OpenWebUI "
                    "tools or pipes are synced"
                )
                raise ValueError(msg)
            if (
                writes_openwebui_artifacts
                and not self.openwebui_proxy_base_url_for_functions
            ):
                msg = (
                    "OPENWEBUI_PROXY_INTERNAL_BASE_URL or OPENWEBUI_PROXY_PUBLIC_BASE_URL "
                    "must be set when OpenWebUI tools or pipes are synced"
                )
                raise ValueError(msg)
            if (
                writes_openwebui_artifacts
                and self.openwebui_source_preview_mode == "connector_viewer"
                and not self.openwebui_proxy_public_base_url
            ):
                msg = (
                    "OPENWEBUI_PROXY_PUBLIC_BASE_URL must be set for connector_viewer "
                    "preview mode when OpenWebUI tools or pipes are synced"
                )
                raise ValueError(msg)
            if not _is_http_url(self.openwebui_base_url):
                msg = "OPENWEBUI_BASE_URL must be an http or https URL"
                raise ValueError(msg)
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

    @property
    def openwebui_dataset_allowlist(self) -> tuple[str, ...]:
        return tuple(
            item.strip()
            for item in self.openwebui_dataset_allowlist_csv.split(",")
            if item.strip()
        )

    @property
    def openwebui_effective_sync_mode(self) -> Literal["disabled", "dry-run", "sync", "repair"]:
        if not self.openwebui_integration_enabled or self.openwebui_sync_mode == "disabled":
            return "disabled"
        if self.dry_run:
            return "dry-run"
        return self.openwebui_sync_mode

    @property
    def openwebui_proxy_base_url_for_functions(self) -> str | None:
        return self.openwebui_proxy_internal_base_url or self.openwebui_proxy_public_base_url

    @property
    def seafile_httpx_verify(self) -> bool | str:
        return self._httpx_verify(self.seafile_verify_ssl, self.seafile_ca_bundle)

    @property
    def ragflow_httpx_verify(self) -> bool | str:
        return self._httpx_verify(self.ragflow_verify_ssl, self.ragflow_ca_bundle)

    @property
    def openwebui_httpx_verify(self) -> bool | str:
        return self._httpx_verify(self.openwebui_verify_ssl, self.openwebui_ca_bundle)

    @property
    def openwebui_proxy_httpx_verify(self) -> bool | str:
        return self._httpx_verify(
            self.openwebui_proxy_verify_ssl,
            self.openwebui_proxy_ca_bundle,
        )

    def _httpx_verify(self, verify_ssl: bool, service_ca_bundle: str | None) -> bool | str:
        return build_service_httpx_verify(
            verify_ssl,
            service_ca_bundle,
            fallback_ca_bundle=self.connector_ca_bundle,
        )


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
