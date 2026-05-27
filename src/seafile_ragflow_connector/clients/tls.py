from __future__ import annotations

import ssl
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

VerifyConfig = bool | str | ssl.SSLContext


class TlsConfigurationError(ValueError):
    """Raised when TLS configuration references unusable local files."""


def build_httpx_verify(verify_ssl: bool, ca_bundle: str | None) -> VerifyConfig:
    if not bool(verify_ssl):
        return False

    ca_path = str(ca_bundle or "").strip()
    if not ca_path:
        return True

    path = Path(ca_path)
    if not path.exists():
        msg = f"CA bundle does not exist: {ca_path}"
        raise TlsConfigurationError(msg)
    if not path.is_file():
        msg = f"CA bundle is not a file: {ca_path}"
        raise TlsConfigurationError(msg)

    try:
        return ssl.create_default_context(cafile=ca_path)
    except OSError as exc:
        msg = f"CA bundle is not usable: {ca_path}"
        raise TlsConfigurationError(msg) from exc


def build_service_httpx_verify(
    verify_ssl: bool,
    service_ca_bundle: str | None,
    *,
    fallback_ca_bundle: str | None = None,
) -> VerifyConfig:
    return build_httpx_verify(verify_ssl, service_ca_bundle or fallback_ca_bundle)


def validate_tls_file(path_value: str | None, *, label: str) -> str | None:
    path_text = str(path_value or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        msg = f"{label} does not exist: {path_text}"
        raise TlsConfigurationError(msg)
    if not path.is_file():
        msg = f"{label} is not a file: {path_text}"
        raise TlsConfigurationError(msg)
    return path_text


def safe_url_for_logs(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").split("?", 1)[0]
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/") or "", "", ""))


def classify_httpx_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "TIMEOUT"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP_{exc.response.status_code}"
    if isinstance(exc, httpx.ConnectError):
        text = str(exc).lower()
        if "certificate" in text or "cert" in text or "ssl" in text:
            return "CERTIFICATE_VERIFY_FAILED"
        return "CONNECT_ERROR"
    if isinstance(exc, httpx.RequestError):
        text = str(exc).lower()
        if "certificate" in text or "cert" in text or "ssl" in text:
            return "CERTIFICATE_VERIFY_FAILED"
        return exc.__class__.__name__.upper()
    if isinstance(exc, TlsConfigurationError | ValueError):
        return "TLS_CONFIGURATION_ERROR"
    return exc.__class__.__name__.upper()
