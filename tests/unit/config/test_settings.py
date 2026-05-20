from __future__ import annotations

import unittest

try:
    from seafile_ragflow_connector.config.settings import Settings
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise
    Settings = None  # type: ignore[assignment]


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


if __name__ == "__main__":
    unittest.main()
