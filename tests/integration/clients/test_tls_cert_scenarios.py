from __future__ import annotations

import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx

from seafile_ragflow_connector.clients.tls import classify_httpx_error

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tls"
_TLS_FIXTURES_TEMP: tempfile.TemporaryDirectory[str] | None = None


class _HealthHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.end_headers()

    def do_GET(self) -> None:
        body = b'{"status":"ok"}'
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _HttpsServer:
    def __init__(self, *, cert_name: str) -> None:
        self.cert_path = FIXTURES / f"{cert_name}.cert.pem"
        self.key_path = FIXTURES / f"{cert_name}.key.pem"
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> _HttpsServer:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert_path), str(self.key_path))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    @property
    def port(self) -> int:
        if self.server is None:
            raise RuntimeError("HTTPS server is not running")
        return int(self.server.server_address[1])


def _top_secret_dns_patch():
    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(
        host: str,
        port: int | str | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ):
        if str(host).endswith(".top.secret"):
            return original_getaddrinfo("127.0.0.1", port, family, type, proto, flags)
        return original_getaddrinfo(host, port, family, type, proto, flags)

    return patch("socket.getaddrinfo", side_effect=getaddrinfo)


class TlsCertificateScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global FIXTURES, _TLS_FIXTURES_TEMP

        _TLS_FIXTURES_TEMP = tempfile.TemporaryDirectory()
        FIXTURES = Path(_TLS_FIXTURES_TEMP.name)
        generator = Path(__file__).resolve().parents[3] / "deploy" / "tls-lab" / "generate_certs.py"
        subprocess.run(
            [sys.executable, str(generator), "--out-dir", str(FIXTURES)],
            check=True,
            stdout=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        global _TLS_FIXTURES_TEMP

        if _TLS_FIXTURES_TEMP is not None:
            _TLS_FIXTURES_TEMP.cleanup()
            _TLS_FIXTURES_TEMP = None

    def test_ca_signed_server_succeeds_with_root_ca_bundle(self) -> None:
        with _HttpsServer(cert_name="rag.top.secret") as server, _top_secret_dns_patch():
            response = httpx.get(
                f"https://rag.top.secret:{server.port}/health",
                verify=str(FIXTURES / "top-secret-root-ca.pem"),
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_ca_signed_server_fails_without_root_ca_bundle(self) -> None:
        with (
            _HttpsServer(cert_name="rag.top.secret") as server,
            _top_secret_dns_patch(),
            self.assertRaises(httpx.ConnectError) as caught,
        ):
            httpx.get(
                f"https://rag.top.secret:{server.port}/health",
                verify=True,
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(classify_httpx_error(caught.exception), "CERTIFICATE_VERIFY_FAILED")

    def test_ca_signed_leaf_certificate_direct_trust_is_runtime_specific(self) -> None:
        with _HttpsServer(cert_name="rag.top.secret") as server, _top_secret_dns_patch():
            try:
                response = httpx.get(
                    f"https://rag.top.secret:{server.port}/health",
                    verify=str(FIXTURES / "rag.top.secret.cert.pem"),
                    timeout=5,
                    trust_env=False,
                )
            except httpx.ConnectError as exc:
                self.assertEqual(classify_httpx_error(exc), "CERTIFICATE_VERIFY_FAILED")
            else:
                self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_unrelated_leaf_certificate_fails_as_ca_bundle(self) -> None:
        with (
            _HttpsServer(cert_name="rag.top.secret") as server,
            _top_secret_dns_patch(),
            self.assertRaises(httpx.ConnectError) as caught,
        ):
            httpx.get(
                f"https://rag.top.secret:{server.port}/health",
                verify=str(FIXTURES / "seafile.top.secret.cert.pem"),
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(classify_httpx_error(caught.exception), "CERTIFICATE_VERIFY_FAILED")

    def test_self_signed_leaf_certificate_can_be_used_only_as_diagnostic_trust_anchor(
        self,
    ) -> None:
        with _HttpsServer(
            cert_name="selfsigned-rag.top.secret"
        ) as server, _top_secret_dns_patch():
            response = httpx.get(
                f"https://selfsigned-rag.top.secret:{server.port}/health",
                verify=str(FIXTURES / "selfsigned-rag.top.secret.cert.pem"),
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_hostname_mismatch_fails_even_with_trusted_root_ca(self) -> None:
        with (
            _HttpsServer(cert_name="wronghost.top.secret") as server,
            _top_secret_dns_patch(),
            self.assertRaises(httpx.ConnectError) as caught,
        ):
            httpx.get(
                f"https://rag.top.secret:{server.port}/health",
                verify=str(FIXTURES / "top-secret-root-ca.pem"),
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(classify_httpx_error(caught.exception), "CERTIFICATE_VERIFY_FAILED")

    def test_expired_certificate_fails_even_with_trusted_root_ca(self) -> None:
        with (
            _HttpsServer(cert_name="expired-rag.top.secret") as server,
            _top_secret_dns_patch(),
            self.assertRaises(httpx.ConnectError) as caught,
        ):
            httpx.get(
                f"https://expired-rag.top.secret:{server.port}/health",
                verify=str(FIXTURES / "top-secret-root-ca.pem"),
                timeout=5,
                trust_env=False,
            )

        self.assertEqual(classify_httpx_error(caught.exception), "CERTIFICATE_VERIFY_FAILED")


if __name__ == "__main__":
    unittest.main()
