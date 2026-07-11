from __future__ import annotations

import unittest

try:
    from seafile_ragflow_connector.config.settings import SearchServiceSettings, Settings
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise
    Settings = None  # type: ignore[assignment]
    SearchServiceSettings = None  # type: ignore[assignment]


@unittest.skipIf(Settings is None, "pydantic is not installed in this Python environment")
class SettingsTests(unittest.TestCase):
    def base_values(self) -> dict[str, object]:
        return {
            "seafile_base_url": "http://seafile.local/",
            "seafile_admin_token": "admin-token",
            "seafile_sync_user_token": "sync-token",
            "ragflow_base_url": "http://ragflow.local/",
            "ragflow_api_key": "ragflow-token",
        }

    def test_builds_database_and_redis_urls_from_portainer_env_parts(self) -> None:
        values = self.base_values()
        values.update(
            {
                "postgres_password": "pass@word/with spaces",
                "redis_host": "connector-redis",
                "redis_db": 2,
            }
        )

        settings = Settings(**values)

        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://sync:pass%40word%2Fwith%20spaces@"
            "connector-postgres:5432/seafile_ragflow_sync",
        )
        self.assertEqual(settings.redis_url, "redis://connector-redis:6379/2")

    def test_explicit_urls_win_over_component_defaults(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "redis_url": "redis://custom-redis:6379/4",
            }
        )

        settings = Settings(**values)

        self.assertEqual(settings.database_url, "postgresql+psycopg://custom/db")
        self.assertEqual(settings.redis_url, "redis://custom-redis:6379/4")

    def test_internal_service_urls_are_normalized_and_validated(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "seafile_internal_url": "  https://seafile.internal:8082/  ",
                "ragflow_internal_url": "https://ragflow.internal:9380/",
            }
        )

        settings = Settings(**values)

        self.assertEqual(settings.seafile_internal_url, "https://seafile.internal:8082")
        self.assertEqual(settings.ragflow_internal_url, "https://ragflow.internal:9380")

        values["seafile_internal_url"] = "  "
        values["ragflow_internal_url"] = ""
        values["seafile_public_base_url"] = ""
        values["ragflow_public_base_url"] = ""
        settings = Settings(**values)
        self.assertIsNone(settings.seafile_internal_url)
        self.assertIsNone(settings.ragflow_internal_url)

        for field in ("seafile_internal_url", "ragflow_internal_url"):
            for value in ("ftp://service.internal", "service.internal:8080"):
                invalid = dict(values)
                invalid[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Settings(**invalid)

    def test_search_settings_build_database_url_from_postgres_parts(self) -> None:
        settings = SearchServiceSettings(
            search_authz_base_url="http://connector-controller:8080",
            search_authz_shared_secret="authz-secret",
            search_ragflow_base_url="http://ragflow.local",
            search_ragflow_api_key="ragflow-token",
            postgres_host="connector-postgres",
            postgres_password="pass@word/with spaces",
        )

        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://sync:pass%40word%2Fwith%20spaces@"
            "connector-postgres:5432/seafile_ragflow_sync",
        )

    def test_dashboard_defaults_to_disabled_with_bounded_limits(self) -> None:
        values = self.base_values()
        values["database_url"] = "postgresql+psycopg://custom/db"

        settings = Settings(**values)

        self.assertFalse(settings.connector_dashboard_enabled)
        self.assertEqual(settings.connector_dashboard_host, "0.0.0.0")
        self.assertEqual(settings.connector_dashboard_port, 8080)
        self.assertEqual(settings.connector_dashboard_max_log_entries, 5000)
        self.assertEqual(settings.connector_dashboard_max_event_entries, 10000)
        self.assertEqual(settings.connector_dashboard_log_page_size, 100)
        self.assertIsNone(settings.connector_dashboard_auth_username)
        self.assertIsNone(settings.connector_dashboard_auth_password)
        self.assertIsNone(settings.connector_language)
        self.assertTrue(settings.authz_api_enabled)
        self.assertTrue(settings.authz_api_fail_closed)
        self.assertEqual(settings.authz_api_max_acl_age_seconds, 7200)
        self.assertTrue(settings.search_acl_sync_enabled)
        self.assertFalse(settings.search_acl_include_subfolder_permissions)
        self.assertFalse(settings.search_acl_include_share_links)

    def test_automation_intervals_default_to_30_minutes(self) -> None:
        values = self.base_values()
        values["database_url"] = "postgresql+psycopg://custom/db"

        settings = Settings(**values)

        self.assertEqual(settings.ragflow_template_refresh_seconds, 1800)
        self.assertEqual(settings.openwebui_sync_interval_seconds, 1800)
        self.assertEqual(settings.discovery_interval_seconds, 1800)
        self.assertEqual(settings.delta_sync_interval_seconds, 1800)
        self.assertEqual(settings.reconcile_interval_seconds, 1800)

    def test_automation_intervals_have_safe_minimum(self) -> None:
        for field in (
            "ragflow_template_refresh_seconds",
            "openwebui_sync_interval_seconds",
            "discovery_interval_seconds",
            "delta_sync_interval_seconds",
            "reconcile_interval_seconds",
        ):
            values = self.base_values()
            values.update(
                {
                    "database_url": "postgresql+psycopg://custom/db",
                    field: 59,
                }
            )

            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings(**values)

    def test_job_retry_settings_accept_positive_bounded_values(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "job_max_attempts": 7,
                "job_retry_base_seconds": 15,
                "job_retry_max_seconds": 120,
                "job_lease_seconds": 300,
                "job_heartbeat_seconds": 100,
            }
        )

        settings = Settings(**values)

        self.assertEqual(settings.job_max_attempts, 7)
        self.assertEqual(settings.job_retry_base_seconds, 15)
        self.assertEqual(settings.job_retry_max_seconds, 120)
        self.assertEqual(settings.job_lease_seconds, 300)
        self.assertEqual(settings.job_heartbeat_seconds, 100)

    def test_job_retry_settings_must_be_positive_and_ordered(self) -> None:
        for field in (
            "job_max_attempts",
            "job_retry_base_seconds",
            "job_retry_max_seconds",
            "job_lease_seconds",
            "job_heartbeat_seconds",
        ):
            values = self.base_values()
            values.update(
                {
                    "database_url": "postgresql+psycopg://custom/db",
                    field: 0,
                }
            )

            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings(**values)

        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "job_retry_base_seconds": 61,
                "job_retry_max_seconds": 60,
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "job_lease_seconds": 179,
                "job_heartbeat_seconds": 60,
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

    def test_connector_language_accepts_supported_locales_and_drops_unknown_values(self) -> None:
        values = self.base_values()
        values["database_url"] = "postgresql+psycopg://custom/db"
        values["connector_language"] = "en_US.UTF-8"

        settings = Settings(**values)

        self.assertEqual(settings.connector_language, "en")

        values["connector_language"] = "fr_FR.UTF-8"
        settings = Settings(**values)

        self.assertEqual(settings.connector_language, "fr")

        values["connector_language"] = "xx_XX.UTF-8"
        settings = Settings(**values)

        self.assertIsNone(settings.connector_language)

    def test_rejects_invalid_dashboard_port_and_limits(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "connector_dashboard_port": 70000,
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

    def test_dashboard_auth_requires_username_and_password_together(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "connector_dashboard_auth_username": "admin",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

        values["connector_dashboard_auth_password"] = "secret"
        settings = Settings(**values)

        self.assertEqual(settings.connector_dashboard_auth_username, "admin")
        self.assertEqual(settings.connector_dashboard_auth_password, "secret")

    def test_openwebui_defaults_to_disabled_without_required_secrets(self) -> None:
        values = self.base_values()
        values["database_url"] = "postgresql+psycopg://custom/db"

        settings = Settings(**values)

        self.assertFalse(settings.openwebui_integration_enabled)
        self.assertEqual(settings.openwebui_effective_sync_mode, "disabled")
        self.assertEqual(settings.openwebui_base_url, "http://localhost:3000")
        self.assertEqual(settings.openwebui_function_namespace, "ragflow")
        self.assertTrue(settings.ragflow_template_auto_create)
        self.assertEqual(settings.ragflow_template_chat_name, "connector_template_chat")
        self.assertFalse(settings.openwebui_pipe_answer_synthesis_enabled)
        self.assertIsNone(settings.openwebui_pipe_answer_llm_base_url)
        self.assertIsNone(settings.openwebui_pipe_answer_llm_model)
        self.assertIsNone(settings.openwebui_pipe_answer_llm_api_key)
        self.assertTrue(settings.delete_dataset_when_library_deleted)
        self.assertFalse(settings.archive_dataset_when_library_deleted)

    def test_seafile_public_base_url_defaults_original_link_template(self) -> None:
        values = self.base_values()
        values["database_url"] = "postgresql+psycopg://custom/db"

        settings = Settings(**values)

        self.assertEqual(settings.effective_seafile_public_base_url, "http://seafile.local")
        self.assertEqual(
            settings.effective_seafile_file_url_template,
            "http://seafile.local/lib/{repo_id}/file{path_quoted}{page_fragment}",
        )

        values["seafile_public_base_url"] = "https://files.example/"
        settings = Settings(**values)

        self.assertEqual(settings.effective_seafile_public_base_url, "https://files.example")
        self.assertEqual(
            settings.effective_seafile_file_url_template,
            "https://files.example/lib/{repo_id}/file{path_quoted}{page_fragment}",
        )

        values["seafile_file_url_template"] = (
            "https://proxy.example/seafile/{repo_id_quoted}?path={path_query}"
        )
        settings = Settings(**values)

        self.assertEqual(
            settings.effective_seafile_file_url_template,
            "https://proxy.example/seafile/{repo_id_quoted}?path={path_query}",
        )

    def test_openwebui_sync_requires_admin_key_and_proxy_secret(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "openwebui_integration_enabled": True,
                "openwebui_sync_mode": "sync",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

        values["openwebui_admin_api_key"] = "admin-key"
        with self.assertRaises(ValueError):
            Settings(**values)

        values["openwebui_proxy_shared_secret"] = "proxy-secret"
        with self.assertRaises(ValueError):
            Settings(**values)

        values["openwebui_proxy_internal_base_url"] = "http://connector:8080"
        settings = Settings(**values)

        self.assertEqual(settings.openwebui_effective_sync_mode, "sync")

    def test_openwebui_rejects_invalid_proxy_urls_when_enabled(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "openwebui_integration_enabled": True,
                "openwebui_sync_mode": "dry-run",
                "openwebui_proxy_public_base_url": "connector:8080",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

    def test_rejects_invalid_pipe_answer_llm_base_url(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "openwebui_pipe_answer_llm_base_url": "litellm:4000/v1",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

    def test_rejects_invalid_search_answer_llm_base_url(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "search_answer_llm_base_url": "litellm:4000/v1",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

    def test_openwebui_dry_run_does_not_require_proxy_secret_or_preview_url(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "openwebui_integration_enabled": True,
                "openwebui_sync_mode": "dry-run",
                "openwebui_source_preview_mode": "connector_viewer",
            }
        )

        settings = Settings(**values)

        self.assertEqual(settings.openwebui_effective_sync_mode, "dry-run")
        self.assertIsNone(settings.openwebui_proxy_shared_secret)

    def test_connector_viewer_requires_public_proxy_url_only_when_artifacts_are_synced(
        self,
    ) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "openwebui_integration_enabled": True,
                "openwebui_sync_mode": "sync",
                "openwebui_admin_api_key": "admin-key",
                "openwebui_proxy_shared_secret": "proxy-secret",
                "openwebui_proxy_internal_base_url": "http://connector:8080",
                "openwebui_source_preview_mode": "connector_viewer",
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)

        values["openwebui_proxy_public_base_url"] = "http://localhost:18080"
        settings = Settings(**values)

        self.assertEqual(settings.openwebui_source_preview_mode, "connector_viewer")

    def test_search_service_settings_do_not_require_seafile_admin_token(self) -> None:
        settings = SearchServiceSettings(
            search_authz_base_url="http://connector-controller:8080",
            search_authz_shared_secret="authz-secret",
            search_ragflow_base_url="http://ragflow:9380",
            search_ragflow_api_key="ragflow-key",
        )

        self.assertEqual(settings.search_service_port, 8090)
        self.assertEqual(settings.search_auth_mode, "trusted_header")
        self.assertEqual(settings.search_trusted_proxy_cidrs, ())
        self.assertEqual(settings.search_default_top_k, 8)
        self.assertEqual(settings.search_max_top_k, 20)
        self.assertTrue(settings.ragflow_search_template_enabled)
        self.assertEqual(settings.ragflow_search_template_name, "search_template")
        self.assertEqual(settings.search_answer_generation_mode, "ragflow_chat")
        self.assertEqual(settings.ragflow_search_answer_chat_name, "connector_search_answer")
        self.assertIsNone(settings.search_answer_llm_base_url)
        self.assertIsNone(settings.search_answer_llm_model)
        self.assertIsNone(settings.search_answer_llm_api_key)
        self.assertEqual(settings.search_answer_llm_timeout_seconds, 60)
        self.assertEqual(settings.search_answer_llm_max_tokens, 900)
        self.assertEqual(settings.search_answer_llm_temperature, 0.2)
        self.assertTrue(settings.search_document_viewer_enabled)
        self.assertEqual(settings.search_document_viewer_max_mb, 100)
        self.assertEqual(
            settings.search_ragflow_template_source_order_csv,
            "search_app,chat,builtin",
        )
        self.assertIsNone(settings.search_ragflow_candidate_top_k)
        self.assertIsNone(settings.search_ragflow_similarity_threshold)

        with self.assertRaises(ValueError):
            SearchServiceSettings(
                search_authz_base_url="http://connector-controller:8080",
                search_authz_shared_secret="authz-secret",
                search_ragflow_base_url="http://ragflow:9380",
                search_ragflow_api_key="ragflow-key",
                search_trusted_proxy_cidrs_csv="not-a-network",
            )

        blank_overrides = SearchServiceSettings(
            search_authz_base_url="http://connector-controller:8080",
            search_authz_shared_secret="authz-secret",
            search_ragflow_base_url="http://ragflow:9380",
            search_ragflow_api_key="ragflow-key",
            search_ragflow_candidate_top_k="",
            search_ragflow_top_n="",
            search_ragflow_similarity_threshold="",
            search_ragflow_vector_similarity_weight="",
            search_ragflow_rerank_id="",
            search_ragflow_keyword="",
            search_ragflow_highlight="",
            search_answer_llm_base_url="",
            search_answer_llm_model="",
            search_answer_llm_api_key="",
        )
        self.assertIsNone(blank_overrides.search_ragflow_candidate_top_k)
        self.assertIsNone(blank_overrides.search_ragflow_keyword)
        self.assertIsNone(blank_overrides.search_answer_llm_base_url)
        self.assertIsNone(blank_overrides.search_answer_llm_model)
        self.assertIsNone(blank_overrides.search_answer_llm_api_key)

    def test_search_service_accepts_openai_compatible_answer_settings(self) -> None:
        settings = SearchServiceSettings(
            search_authz_base_url="http://connector-controller:8080",
            search_authz_shared_secret="authz-secret",
            search_ragflow_base_url="http://ragflow:9380",
            search_ragflow_api_key="ragflow-key",
            search_answer_llm_base_url="http://litellm:4000/v1/",
            search_answer_llm_model="local-model",
            search_answer_llm_api_key="llm-key",
            search_answer_llm_timeout_seconds=30,
            search_answer_llm_max_tokens=512,
            search_answer_llm_temperature=0.1,
        )

        self.assertEqual(settings.search_answer_llm_base_url, "http://litellm:4000/v1")
        self.assertEqual(settings.search_answer_llm_model, "local-model")
        self.assertEqual(settings.search_answer_llm_api_key, "llm-key")
        self.assertEqual(settings.search_answer_llm_timeout_seconds, 30)
        self.assertEqual(settings.search_answer_llm_max_tokens, 512)
        self.assertEqual(settings.search_answer_llm_temperature, 0.1)

    def test_search_service_rejects_invalid_answer_llm_settings(self) -> None:
        base = {
            "search_authz_base_url": "http://connector-controller:8080",
            "search_authz_shared_secret": "authz-secret",
            "search_ragflow_base_url": "http://ragflow:9380",
            "search_ragflow_api_key": "ragflow-key",
        }

        with self.assertRaises(ValueError):
            SearchServiceSettings(
                **base,
                search_answer_llm_base_url="litellm:4000/v1",
                search_answer_llm_model="local-model",
            )

        with self.assertRaises(ValueError):
            SearchServiceSettings(
                **base,
                search_answer_llm_base_url="http://litellm:4000/v1",
                search_answer_llm_model="local-model",
                search_answer_llm_temperature=2.1,
            )

        with self.assertRaises(ValueError):
            SearchServiceSettings(
                **base,
                search_answer_llm_base_url="http://litellm:4000/v1",
                search_answer_llm_model="local-model",
                search_answer_llm_max_tokens=0,
            )

    def test_global_dry_run_forces_openwebui_dry_run(self) -> None:
        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "dry_run": True,
                "openwebui_integration_enabled": True,
            }
        )

        settings = Settings(**values)

        self.assertEqual(settings.openwebui_effective_sync_mode, "dry-run")

        values = self.base_values()
        values.update(
            {
                "database_url": "postgresql+psycopg://custom/db",
                "connector_dashboard_max_log_entries": 0,
            }
        )

        with self.assertRaises(ValueError):
            Settings(**values)


if __name__ == "__main__":
    unittest.main()
