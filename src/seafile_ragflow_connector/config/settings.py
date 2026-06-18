from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from seafile_ragflow_connector.clients.tls import (
    VerifyConfig,
    build_service_httpx_verify,
    validate_tls_file,
)
from seafile_ragflow_connector.i18n import normalize_language

DEFAULT_AUTOMATION_INTERVAL_SECONDS = 1800
MIN_AUTOMATION_INTERVAL_SECONDS = 60


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
    connector_language: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CONNECTOR_LANGUAGE", "LANGUAGE"),
    )
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
    connector_dashboard_auth_username: str | None = None
    connector_dashboard_auth_password: str | None = None
    connector_transport_status: dict[str, object] = Field(default_factory=dict)

    authz_api_enabled: bool = True
    authz_api_shared_secret: str = "change-me"
    authz_api_allow_networks_csv: str = Field(
        default="",
        validation_alias="AUTHZ_API_ALLOW_NETWORKS",
    )
    authz_api_fail_closed: bool = True
    authz_api_max_acl_age_seconds: int = 7200

    search_acl_sync_enabled: bool = True
    search_acl_sync_interval_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
    search_acl_include_subfolder_permissions: bool = False
    search_acl_include_share_links: bool = False

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
    seafile_public_base_url: str | None = Field(
        default=None,
        validation_alias="SEAFILE_PUBLIC_BASE_URL",
    )
    seafile_file_url_template: str | None = Field(
        default=None,
        validation_alias="SEAFILE_FILE_URL_TEMPLATE",
    )

    ragflow_base_url: str
    ragflow_internal_url: str | None = None
    ragflow_api_key: str
    ragflow_template_dataset_name: str = "connector_template"
    ragflow_template_auto_create: bool = True
    ragflow_template_required: bool = True
    ragflow_template_chat_name: str = "connector_template_chat"
    ragflow_verify_ssl: bool = True
    ragflow_ca_bundle: str | None = None
    ragflow_template_refresh_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
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
    openwebui_pipe_answer_synthesis_enabled: bool = False
    openwebui_pipe_answer_llm_base_url: str | None = None
    openwebui_pipe_answer_llm_model: str | None = None
    openwebui_pipe_answer_llm_api_key: str | None = None
    openwebui_authz_enabled: bool = True
    openwebui_authz_base_url: str | None = None
    openwebui_authz_shared_secret: str | None = None
    openwebui_authz_fail_closed: bool = True
    ragflow_client_cert_file: str | None = None
    ragflow_client_key_file: str | None = None
    seafile_client_cert_file: str | None = None
    seafile_client_key_file: str | None = None
    connector_proxy_client_cert_file: str | None = None
    connector_proxy_client_key_file: str | None = None
    openwebui_sync_interval_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
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

    discovery_interval_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
    delta_sync_interval_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
    reconcile_interval_seconds: int = DEFAULT_AUTOMATION_INTERVAL_SECONDS
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
        "seafile_public_base_url",
        "ragflow_base_url",
        "ragflow_public_base_url",
        "openwebui_base_url",
        "openwebui_proxy_public_base_url",
        "openwebui_proxy_internal_base_url",
        "openwebui_pipe_answer_llm_base_url",
        "openwebui_authz_base_url",
    )
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @field_validator("seafile_file_url_template")
    @classmethod
    def strip_optional_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

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

    @field_validator("connector_language")
    @classmethod
    def validate_connector_language(cls, value: str | None) -> str | None:
        language = normalize_language(value)
        return language

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

    @field_validator("openwebui_request_timeout_seconds")
    @classmethod
    def validate_openwebui_positive_int(cls, value: int) -> int:
        if value <= 0:
            msg = "openwebui numeric settings must be positive"
            raise ValueError(msg)
        return value

    @field_validator(
        "ragflow_template_refresh_seconds",
        "openwebui_sync_interval_seconds",
        "search_acl_sync_interval_seconds",
        "discovery_interval_seconds",
        "delta_sync_interval_seconds",
        "reconcile_interval_seconds",
    )
    @classmethod
    def validate_automation_interval(cls, value: int) -> int:
        if value < MIN_AUTOMATION_INTERVAL_SECONDS:
            msg = (
                "automation interval settings must be at least "
                f"{MIN_AUTOMATION_INTERVAL_SECONDS} seconds"
            )
            raise ValueError(msg)
        return value

    @field_validator("authz_api_max_acl_age_seconds")
    @classmethod
    def validate_authz_max_acl_age(cls, value: int) -> int:
        if value <= 0:
            msg = "AUTHZ_API_MAX_ACL_AGE_SECONDS must be positive"
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

    @field_validator("connector_dashboard_auth_username", "connector_dashboard_auth_password")
    @classmethod
    def strip_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def build_service_urls(self) -> Settings:
        if bool(self.connector_dashboard_auth_username) != bool(
            self.connector_dashboard_auth_password
        ):
            msg = (
                "CONNECTOR_DASHBOARD_AUTH_USERNAME and "
                "CONNECTOR_DASHBOARD_AUTH_PASSWORD must be set together"
            )
            raise ValueError(msg)
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
        if self.openwebui_authz_base_url is None:
            self.openwebui_authz_base_url = self.openwebui_proxy_base_url_for_functions
        if self.openwebui_authz_shared_secret is None:
            self.openwebui_authz_shared_secret = self.authz_api_shared_secret
        for name in (
            "seafile_public_base_url",
            "ragflow_public_base_url",
            "openwebui_proxy_public_base_url",
            "openwebui_proxy_internal_base_url",
            "openwebui_pipe_answer_llm_base_url",
            "openwebui_authz_base_url",
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
    def authz_api_allow_networks(self) -> tuple[str, ...]:
        return _split_csv(self.authz_api_allow_networks_csv)

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
    def effective_seafile_public_base_url(self) -> str | None:
        base_url = self.seafile_public_base_url or self.seafile_base_url
        return base_url.rstrip("/") if base_url else None

    @property
    def effective_seafile_file_url_template(self) -> str | None:
        if self.seafile_file_url_template:
            return self.seafile_file_url_template
        base_url = self.effective_seafile_public_base_url
        if not base_url:
            return None
        return f"{base_url}/lib/{{repo_id}}/file{{path_quoted}}{{page_fragment}}"

    @property
    def seafile_httpx_verify(self) -> VerifyConfig:
        return self._httpx_verify(self.seafile_verify_ssl, self.seafile_ca_bundle)

    @property
    def ragflow_httpx_verify(self) -> VerifyConfig:
        return self._httpx_verify(self.ragflow_verify_ssl, self.ragflow_ca_bundle)

    @property
    def openwebui_httpx_verify(self) -> VerifyConfig:
        return self._httpx_verify(self.openwebui_verify_ssl, self.openwebui_ca_bundle)

    @property
    def openwebui_proxy_httpx_verify(self) -> VerifyConfig:
        return self._httpx_verify(
            self.openwebui_proxy_verify_ssl,
            self.openwebui_proxy_ca_bundle,
        )

    def _httpx_verify(self, verify_ssl: bool, service_ca_bundle: str | None) -> VerifyConfig:
        return build_service_httpx_verify(
            verify_ssl,
            service_ca_bundle,
            fallback_ca_bundle=self.connector_ca_bundle,
        )


class SearchServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="stack.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "production"
    connector_language: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CONNECTOR_LANGUAGE", "LANGUAGE"),
    )
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    connector_ca_bundle: str | None = None

    search_service_enabled: bool = True
    search_service_host: str = "0.0.0.0"  # nosec B104
    search_service_port: int = 8090

    search_auth_mode: Literal["trusted_header"] = "trusted_header"
    search_trusted_username_header: str = "X-Forwarded-User"
    search_trusted_email_header: str = "X-Forwarded-Email"
    search_trusted_display_name_header: str = "X-Forwarded-Name"

    search_authz_base_url: str = "http://connector-controller:8080"
    search_authz_shared_secret: str = "change-me"

    search_ragflow_base_url: str = "http://ragflow:9380"
    search_ragflow_api_key: str = "change-me"
    search_ragflow_verify_ssl: bool = True
    search_ragflow_ca_bundle: str | None = None
    search_seafile_public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEARCH_SEAFILE_PUBLIC_BASE_URL", "SEAFILE_PUBLIC_BASE_URL"),
    )
    search_seafile_file_url_template: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SEARCH_SEAFILE_FILE_URL_TEMPLATE",
            "SEAFILE_FILE_URL_TEMPLATE",
        ),
    )

    search_default_top_k: int = 8
    search_max_top_k: int = 20
    search_max_selected_profiles: int = 25
    search_enable_chat_mode: bool = True
    search_enable_retrieval_mode: bool = True
    search_source_preview_enabled: bool = True
    search_source_hover_enabled: bool = True
    search_text_fragment_links_enabled: bool = True
    search_result_snippet_context_chars: int = 420
    search_answer_max_sources: int = 8
    search_source_preview_secret: str | None = None

    @field_validator("connector_language")
    @classmethod
    def validate_connector_language(cls, value: str | None) -> str | None:
        return normalize_language(value)

    @field_validator(
        "search_authz_base_url",
        "search_ragflow_base_url",
        "search_seafile_public_base_url",
    )
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    @property
    def effective_search_seafile_file_url_template(self) -> str | None:
        if self.search_seafile_file_url_template:
            return self.search_seafile_file_url_template
        base_url = self.search_seafile_public_base_url
        if not base_url:
            return None
        return f"{base_url}/lib/{{repo_id}}/file{{path_quoted}}{{page_fragment}}"

    @field_validator("connector_ca_bundle", "search_ragflow_ca_bundle", mode="before")
    @classmethod
    def strip_optional_path(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("search_service_port")
    @classmethod
    def validate_search_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            msg = "SEARCH_SERVICE_PORT must be between 1 and 65535"
            raise ValueError(msg)
        return value

    @field_validator(
        "search_default_top_k",
        "search_max_top_k",
        "search_max_selected_profiles",
        "search_result_snippet_context_chars",
        "search_answer_max_sources",
    )
    @classmethod
    def validate_search_positive_int(cls, value: int) -> int:
        if value <= 0:
            msg = "search numeric settings must be positive"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_search_urls_and_limits(self) -> SearchServiceSettings:
        for name in ("search_authz_base_url", "search_ragflow_base_url"):
            value = getattr(self, name)
            if not _is_http_url(value):
                msg = f"{name.upper()} must be an http or https URL"
                raise ValueError(msg)
        if self.search_default_top_k > self.search_max_top_k:
            msg = "SEARCH_DEFAULT_TOP_K must be <= SEARCH_MAX_TOP_K"
            raise ValueError(msg)
        if not self.search_enable_chat_mode and not self.search_enable_retrieval_mode:
            msg = "at least one search mode must be enabled"
            raise ValueError(msg)
        for name in ("connector_ca_bundle", "search_ragflow_ca_bundle"):
            value = getattr(self, name)
            if value:
                validate_tls_file(str(value), label=name.upper())
        return self

    @property
    def search_ragflow_httpx_verify(self) -> VerifyConfig:
        return build_service_httpx_verify(
            self.search_ragflow_verify_ssl,
            self.search_ragflow_ca_bundle,
            fallback_ca_bundle=self.connector_ca_bundle,
        )

    @property
    def effective_search_source_preview_secret(self) -> str:
        return self.search_source_preview_secret or self.search_authz_shared_secret


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_search_service_settings() -> SearchServiceSettings:
    return SearchServiceSettings()
