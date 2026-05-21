from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from seafile_ragflow_connector.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "seafile_base_url": "https://seafile.example.local",
        "seafile_admin_token": "admin-token",
        "seafile_sync_user_token": "sync-token",
        "ragflow_base_url": "https://ragflow.example.local",
        "ragflow_api_key": "ragflow-token",
        "postgres_password": "postgres-password",
    }
    values.update(overrides)
    return Settings(**values)


class SettingsTlsTests(unittest.TestCase):
    def test_connector_ca_bundle_is_used_for_all_https_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "company-ca.pem"
            ca_bundle.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")

            settings = _settings(connector_ca_bundle=str(ca_bundle))

        self.assertEqual(settings.seafile_httpx_verify, str(ca_bundle))
        self.assertEqual(settings.ragflow_httpx_verify, str(ca_bundle))
        self.assertEqual(settings.openwebui_httpx_verify, str(ca_bundle))

    def test_service_ca_bundle_overrides_connector_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shared = Path(tmpdir) / "shared-ca.pem"
            seafile = Path(tmpdir) / "seafile-ca.pem"
            shared.write_text("shared")
            seafile.write_text("seafile")

            settings = _settings(
                connector_ca_bundle=str(shared),
                seafile_ca_bundle=str(seafile),
                ragflow_verify_ssl=False,
            )

        self.assertEqual(settings.seafile_httpx_verify, str(seafile))
        self.assertFalse(settings.ragflow_httpx_verify)
        self.assertEqual(settings.openwebui_httpx_verify, str(shared))

    def test_missing_ca_bundle_fails_config_validation(self) -> None:
        with self.assertRaises(ValidationError):
            _settings(connector_ca_bundle="/certs/missing-ca.pem")


if __name__ == "__main__":
    unittest.main()
