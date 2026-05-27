from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path

import certifi

from seafile_ragflow_connector.clients.tls import (
    TlsConfigurationError,
    build_httpx_verify,
    classify_httpx_error,
    safe_url_for_logs,
)


def _valid_ca_bundle_text() -> str:
    return Path(certifi.where()).read_text(encoding="utf-8")


class TlsHelperTests(unittest.TestCase):
    def test_verify_ssl_false_returns_false(self) -> None:
        self.assertFalse(build_httpx_verify(False, "/missing/ca.pem"))

    def test_verify_ssl_true_without_ca_uses_default_trust(self) -> None:
        self.assertTrue(build_httpx_verify(True, None))
        self.assertTrue(build_httpx_verify(True, ""))
        self.assertTrue(build_httpx_verify(True, "   "))

    def test_valid_ca_file_path_returns_ssl_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "internal-ca.pem"
            ca_bundle.write_text(_valid_ca_bundle_text(), encoding="utf-8")

            verify = build_httpx_verify(True, str(ca_bundle))

            self.assertIsInstance(verify, ssl.SSLContext)
            self.assertEqual(verify.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(verify.check_hostname)

    def test_invalid_ca_file_content_fails_without_leaking_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_bundle = Path(tmpdir) / "invalid-ca.pem"
            ca_bundle.write_text(
                "-----BEGIN CERTIFICATE-----\nnot-a-real-ca\n-----END CERTIFICATE-----\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(TlsConfigurationError, "CA bundle is not usable") as caught:
                build_httpx_verify(True, str(ca_bundle))

        self.assertNotIn("not-a-real-ca", str(caught.exception))

    def test_missing_ca_file_path_fails(self) -> None:
        with self.assertRaisesRegex(TlsConfigurationError, "CA bundle does not exist"):
            build_httpx_verify(True, "/certs/missing-ca.pem")

    def test_ca_path_must_be_file(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            self.assertRaisesRegex(TlsConfigurationError, "CA bundle is not a file"),
        ):
            build_httpx_verify(True, tmpdir)

    def test_safe_url_for_logs_removes_credentials_query_and_fragment(self) -> None:
        self.assertEqual(
            safe_url_for_logs("https://user:pass@example.local:9443/api?token=secret#x"),
            "https://example.local:9443/api",
        )

    def test_error_classification_covers_tls_configuration_errors(self) -> None:
        self.assertEqual(
            classify_httpx_error(TlsConfigurationError("bad ca")),
            "TLS_CONFIGURATION_ERROR",
        )


if __name__ == "__main__":
    unittest.main()
