from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path

import certifi

from seafile_ragflow_connector.app.transport import (
    TransportProbeResult,
    resolve_service_transports,
)
from seafile_ragflow_connector.clients.tls import VerifyConfig
from seafile_ragflow_connector.config.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "seafile_base_url": "http://seafile.local",
        "seafile_admin_token": "admin-token",
        "seafile_sync_user_token": "sync-token",
        "ragflow_base_url": "http://ragflow.local:9380",
        "ragflow_api_key": "ragflow-token",
        "database_url": "sqlite://",
        "redis_url": "redis://127.0.0.1:1/0",
        "openwebui_integration_enabled": True,
        "openwebui_sync_mode": "dry-run",
        "openwebui_base_url": "http://openwebui.local:8080",
    }
    values.update(overrides)
    return Settings(**values)


def _write_valid_ca_bundle(path: Path) -> None:
    path.write_text(Path(certifi.where()).read_text(encoding="utf-8"), encoding="utf-8")


class TransportResolutionTests(unittest.TestCase):
    def test_prefers_https_even_when_configured_url_is_http(self) -> None:
        calls: list[str] = []

        def probe(
            base_url: str,
            path: str,
            headers: dict[str, str],
            params: dict[str, str | int | float | bool | None],
            verify: bool | str,
            timeout_seconds: float,
        ) -> TransportProbeResult:
            _ = (path, headers, params, verify, timeout_seconds)
            calls.append(base_url)
            return TransportProbeResult(ok=base_url.startswith("https://"), status_code=200)

        settings = _settings()

        resolve_service_transports(settings, probe=probe)

        self.assertEqual(settings.seafile_base_url, "https://seafile.local")
        self.assertEqual(settings.ragflow_base_url, "https://ragflow.local:9380")
        self.assertEqual(settings.openwebui_base_url, "https://openwebui.local:8080")
        self.assertEqual(settings.connector_transport_status["seafile"]["scheme"], "https")
        self.assertFalse(settings.connector_transport_status["seafile"]["fallback_used"])
        self.assertIn("https://seafile.local", calls)

    def test_internal_urls_are_probed_and_preserve_base_urls(self) -> None:
        calls: list[str] = []

        def probe(
            base_url: str,
            path: str,
            headers: dict[str, str],
            params: dict[str, str | int | float | bool | None],
            verify: bool | str,
            timeout_seconds: float,
        ) -> TransportProbeResult:
            _ = (path, headers, params, verify, timeout_seconds)
            calls.append(base_url)
            return TransportProbeResult(ok=base_url.startswith("https://"), status_code=200)

        settings = _settings(
            seafile_base_url="https://files.example.local",
            seafile_internal_url="http://seafile.internal:8082",
            seafile_public_base_url="https://files.public.example.local",
            ragflow_base_url="https://ragflow.example.local",
            ragflow_internal_url="http://ragflow.internal:9380",
            openwebui_integration_enabled=False,
        )

        resolve_service_transports(settings, probe=probe)

        self.assertEqual(settings.seafile_base_url, "https://files.example.local")
        self.assertEqual(settings.seafile_public_base_url, "https://files.public.example.local")
        self.assertEqual(settings.seafile_internal_url, "https://seafile.internal:8082")
        self.assertEqual(settings.ragflow_base_url, "https://ragflow.example.local")
        self.assertEqual(settings.ragflow_internal_url, "https://ragflow.internal:9380")
        self.assertNotIn("https://files.example.local", calls)
        self.assertNotIn("https://ragflow.example.local", calls)
        seafile_status = settings.connector_transport_status["seafile"]
        self.assertEqual(seafile_status["configured_url"], "http://seafile.internal:8082")
        self.assertEqual(seafile_status["selected_url"], "https://seafile.internal:8082")
        self.assertEqual(seafile_status["scheme"], "https")
        self.assertFalse(seafile_status["fallback_used"])

    def test_falls_back_to_http_only_after_https_probe_fails(self) -> None:
        calls: list[str] = []

        def probe(
            base_url: str,
            path: str,
            headers: dict[str, str],
            params: dict[str, str | int | float | bool | None],
            verify: bool | str,
            timeout_seconds: float,
        ) -> TransportProbeResult:
            _ = (path, headers, params, verify, timeout_seconds)
            calls.append(base_url)
            if base_url.startswith("https://"):
                return TransportProbeResult(ok=False, error_type="CONNECT_ERROR")
            return TransportProbeResult(ok=True, status_code=200)

        settings = _settings(openwebui_integration_enabled=False)

        resolve_service_transports(settings, probe=probe)

        self.assertEqual(settings.seafile_base_url, "http://seafile.local")
        self.assertEqual(settings.ragflow_base_url, "http://ragflow.local:9380")
        seafile_status = settings.connector_transport_status["seafile"]
        self.assertEqual(seafile_status["scheme"], "http")
        self.assertTrue(seafile_status["fallback_used"])
        self.assertEqual(seafile_status["https_error_type"], "CONNECT_ERROR")
        self.assertLess(
            calls.index("https://seafile.local"),
            calls.index("http://seafile.local"),
        )

    def test_marks_http_fallback_when_http_probe_is_initially_unreachable(self) -> None:
        def probe(
            base_url: str,
            path: str,
            headers: dict[str, str],
            params: dict[str, str | int | float | bool | None],
            verify: bool | str,
            timeout_seconds: float,
        ) -> TransportProbeResult:
            _ = (base_url, path, headers, params, verify, timeout_seconds)
            return TransportProbeResult(ok=False, error_type="CONNECT_ERROR")

        settings = _settings(openwebui_integration_enabled=False)

        resolve_service_transports(settings, probe=probe)

        seafile_status = settings.connector_transport_status["seafile"]
        self.assertEqual(seafile_status["scheme"], "http")
        self.assertTrue(seafile_status["fallback_used"])
        self.assertEqual(
            seafile_status["fallback_reason"],
            "https_failed:CONNECT_ERROR;http_unreachable",
        )

    def test_custom_ca_bundle_uses_context_but_safe_status_label(self) -> None:
        seen_verify: list[VerifyConfig] = []

        def probe(
            base_url: str,
            path: str,
            headers: dict[str, str],
            params: dict[str, str | int | float | bool | None],
            verify: VerifyConfig,
            timeout_seconds: float,
        ) -> TransportProbeResult:
            _ = (base_url, path, headers, params, timeout_seconds)
            seen_verify.append(verify)
            return TransportProbeResult(ok=True, status_code=200)

        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "company-ca.pem"
            _write_valid_ca_bundle(ca_bundle)
            settings = _settings(connector_ca_bundle=str(ca_bundle))

            resolve_service_transports(settings, probe=probe)

        self.assertTrue(any(isinstance(value, ssl.SSLContext) for value in seen_verify))
        self.assertEqual(settings.connector_transport_status["seafile"]["tls_verify"], "custom_ca")


if __name__ == "__main__":
    unittest.main()
