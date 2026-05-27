from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path

import certifi
from pydantic import ValidationError

from seafile_ragflow_connector.clients.tls import TlsConfigurationError
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


def _write_valid_ca_bundle(path: Path) -> None:
    path.write_text(Path(certifi.where()).read_text(encoding="utf-8"), encoding="utf-8")


def _assert_ssl_context(test_case: unittest.TestCase, value: object) -> ssl.SSLContext:
    test_case.assertIsInstance(value, ssl.SSLContext)
    return value  # type: ignore[return-value]


class SettingsTlsTests(unittest.TestCase):
    def test_connector_ca_bundle_is_used_for_all_https_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "company-ca.pem"
            _write_valid_ca_bundle(ca_bundle)

            settings = _settings(connector_ca_bundle=str(ca_bundle))

            _assert_ssl_context(self, settings.seafile_httpx_verify)
            _assert_ssl_context(self, settings.ragflow_httpx_verify)
            _assert_ssl_context(self, settings.openwebui_httpx_verify)

    def test_service_ca_bundle_overrides_connector_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shared = Path(tmpdir) / "shared-ca.pem"
            seafile = Path(tmpdir) / "seafile-ca.pem"
            _write_valid_ca_bundle(shared)
            seafile.write_text("not a usable ca bundle", encoding="utf-8")

            settings = _settings(
                connector_ca_bundle=str(shared),
                seafile_ca_bundle=str(seafile),
                ragflow_verify_ssl=False,
            )

            with self.assertRaisesRegex(TlsConfigurationError, "CA bundle is not usable"):
                _ = settings.seafile_httpx_verify
            self.assertFalse(settings.ragflow_httpx_verify)
            _assert_ssl_context(self, settings.openwebui_httpx_verify)

    def test_missing_ca_bundle_fails_config_validation(self) -> None:
        with self.assertRaises(ValidationError):
            _settings(connector_ca_bundle="/certs/missing-ca.pem")

    def test_openwebui_proxy_accepts_connector_proxy_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "connector-proxy-ca.pem"
            _write_valid_ca_bundle(ca_bundle)

            settings = _settings(
                CONNECTOR_PROXY_VERIFY_SSL=True,
                CONNECTOR_PROXY_CA_BUNDLE=str(ca_bundle),
            )

            _assert_ssl_context(self, settings.openwebui_proxy_httpx_verify)

    def test_openwebui_proxy_ca_bundle_is_validated(self) -> None:
        with self.assertRaises(ValidationError):
            _settings(openwebui_proxy_ca_bundle="/certs/missing-openwebui-proxy-ca.pem")


if __name__ == "__main__":
    unittest.main()
