from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT = ROOT_DIR / "scripts" / "configure-enterprise-compose.sh"


def _env_value(env_text: str, key: str) -> str:
    prefix = f"{key}="
    for line in env_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"{key} missing from generated env")


def _find_portable_bash() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required for enterprise compose wizard")
    if os.name == "nt" and "system32" in str(Path(bash)).lower():
        pytest.skip("Windows WSL bash cannot execute repository-local Windows paths")
    return bash


def _make_root_ca(tmp_path: Path) -> Path:
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is required for enterprise compose wizard CA validation")

    key_file = tmp_path / "root-ca.key"
    cert_file = tmp_path / "root-ca.pem"
    config_file = tmp_path / "openssl.cnf"
    config_file.write_text(
        """
[req]
distinguished_name = dn
x509_extensions = v3_ca
prompt = no

[dn]
CN = Connector Enterprise Test Root CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key_file),
            "-out",
            str(cert_file),
            "-config",
            str(config_file),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return cert_file


def test_enterprise_compose_wizard_generates_env_and_helper_scripts(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()

    ca_file = _make_root_ca(tmp_path)
    output_env = tmp_path / "connector.env"
    output_dir = tmp_path / "generated"
    secret_values = {
        "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
        "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
        "RAGFLOW_API_KEY": "ragflow-secret",
        "OPENWEBUI_ADMIN_API_KEY": "openwebui-secret",
        "POSTGRES_PASSWORD": "postgres-secret",
        "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
        "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
    }
    env = os.environ.copy()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_PORTAINER_BUNDLE": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_WITH_OPENWEBUI": "true",
            "ENTERPRISE_CA_HOST_FILE": str(ca_file),
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_SEAFILE_PUBLIC_BASE_URL": "https://files.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "ENTERPRISE_OPENWEBUI_BASE_URL": "https://openwebui.internal",
            "ENTERPRISE_CONNECTOR_PUBLIC_BASE_URL": "https://connector.internal",
            **secret_values,
        }
    )

    subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--non-interactive",
            "--assume-yes",
            "--no-config-check",
            "--output-env",
            str(output_env),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    generated_env = output_env.read_text(encoding="utf-8")
    ca_env_path = _env_value(generated_env, "CONNECTOR_ENTERPRISE_CA_HOST_FILE")
    assert ca_env_path
    assert ca_env_path.replace("\\", "/").endswith("/root-ca.pem")
    assert "CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE=/certs/company-root-ca.pem" in generated_env
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in generated_env
    assert "SEAFILE_VERIFY_SSL=true" in generated_env
    assert "SEAFILE_PUBLIC_BASE_URL=https://files.internal" in generated_env
    assert "SEAFILE_FILE_URL_TEMPLATE=\n" in generated_env
    assert "RAGFLOW_CA_BUNDLE=/certs/company-root-ca.pem" in generated_env
    assert "OPENWEBUI_SOURCE_PREVIEW_MODE=connector_viewer" in generated_env
    assert "OPENWEBUI_PROXY_PUBLIC_BASE_URL=https://connector.internal" in generated_env
    assert "CONNECTOR_STARTUP_CHECK=infra" in generated_env
    assert "CONNECTOR_BOOTSTRAP_CHECK_LIVE=false" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/external-services.compose.yml" in compose_files
    assert "deploy/compose/enterprise-ca.compose.yml" in compose_files

    helper_scripts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            output_dir / "check-config.sh",
            output_dir / "up.sh",
            output_dir / "check-live.sh",
            output_dir / "down.sh",
        ]
    )
    assert "docker compose --env-file" in helper_scripts
    assert "connector.env" in helper_scripts
    for secret in secret_values.values():
        assert secret not in helper_scripts


def test_enterprise_compose_wizard_generates_installable_defaults_without_ca_or_openwebui_key(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()

    output_env = tmp_path / "connector.env"
    output_dir = tmp_path / "generated"
    env = os.environ.copy()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_PORTAINER_BUNDLE": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_WITH_OPENWEBUI": "true",
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "ENTERPRISE_OPENWEBUI_BASE_URL": "https://openwebui.internal",
            "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
            "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
            "RAGFLOW_API_KEY": "ragflow-secret",
            "POSTGRES_PASSWORD": "postgres-secret",
            "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
            "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
        }
    )

    subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--non-interactive",
            "--assume-yes",
            "--no-config-check",
            "--output-env",
            str(output_env),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    generated_env = output_env.read_text(encoding="utf-8")
    assert "CONNECTOR_ENTERPRISE_CA_HOST_FILE=\n" in generated_env
    assert "CONNECTOR_CA_BUNDLE=\n" in generated_env
    assert "SEAFILE_CA_BUNDLE=\n" in generated_env
    assert "RAGFLOW_CA_BUNDLE=\n" in generated_env
    assert "OPENWEBUI_ADMIN_API_KEY=\n" in generated_env
    assert "OPENWEBUI_SYNC_MODE=disabled" in generated_env
    assert "SEAFILE_PUBLIC_BASE_URL=https://seafile.internal" in generated_env
    assert "CONNECTOR_STARTUP_CHECK=infra" in generated_env
    assert "CONNECTOR_BOOTSTRAP_CHECK_LIVE=false" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/external-services.compose.yml" in compose_files
    assert "deploy/compose/enterprise-ca.compose.yml" not in compose_files


def test_enterprise_compose_wizard_keeps_proxy_ca_empty_for_internal_http(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()

    ca_file = _make_root_ca(tmp_path)
    output_env = tmp_path / "shared.env"
    output_dir = tmp_path / "shared-generated"
    env = os.environ.copy()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_PORTAINER_BUNDLE": "false",
            "ENTERPRISE_MODE": "shared",
            "ENTERPRISE_WITH_OPENWEBUI": "true",
            "ENTERPRISE_CA_HOST_FILE": str(ca_file),
            "ENTERPRISE_SEAFILE_BASE_URL": "http://seafile",
            "ENTERPRISE_SEAFILE_PUBLIC_BASE_URL": "https://files.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "http://ragflow:9380",
            "ENTERPRISE_OPENWEBUI_BASE_URL": "http://openwebui:8080",
            "CONNECTOR_DOCKER_NETWORK_NAME": "enterprise-network",
            "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
            "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
            "RAGFLOW_API_KEY": "ragflow-secret",
            "OPENWEBUI_ADMIN_API_KEY": "openwebui-secret",
            "POSTGRES_PASSWORD": "postgres-secret",
            "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
            "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
        }
    )

    subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--non-interactive",
            "--assume-yes",
            "--no-config-check",
            "--output-env",
            str(output_env),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    generated_env = output_env.read_text(encoding="utf-8")
    assert "SEAFILE_BASE_URL=http://seafile" in generated_env
    assert "SEAFILE_PUBLIC_BASE_URL=https://files.internal" in generated_env
    assert "RAGFLOW_BASE_URL=http://ragflow:9380" in generated_env
    assert "OPENWEBUI_BASE_URL=http://openwebui:8080" in generated_env
    assert "OPENWEBUI_SYNC_MODE=sync" in generated_env
    assert "OPENWEBUI_SOURCE_PREVIEW_MODE=citation_only" in generated_env
    assert "OPENWEBUI_PROXY_PUBLIC_BASE_URL=\n" in generated_env
    assert "OPENWEBUI_PROXY_INTERNAL_BASE_URL=http://connector-controller:8080" in generated_env
    assert "OPENWEBUI_PROXY_CA_BUNDLE=\n" in generated_env
    assert "CONNECTOR_PROXY_CA_BUNDLE=\n" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/openwebui.compose.yml" in compose_files
    assert "deploy/compose/enterprise-ca.compose.yml" in compose_files


def test_enterprise_compose_wizard_generates_portainer_bundle_when_docker_is_available(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose is required for Portainer bundle generation")
    try:
        subprocess.run(
            [docker, "compose", "version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        pytest.skip("Docker Compose is not available")

    ca_file = _make_root_ca(tmp_path)
    output_env = tmp_path / "connector.env"
    output_dir = tmp_path / "generated"
    secret_values = {
        "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
        "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
        "RAGFLOW_API_KEY": "ragflow-secret",
        "OPENWEBUI_ADMIN_API_KEY": "openwebui-secret",
        "POSTGRES_PASSWORD": "postgres-secret",
        "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
        "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
    }
    env = os.environ.copy()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_WITH_OPENWEBUI": "true",
            "ENTERPRISE_CA_HOST_FILE": str(ca_file),
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "ENTERPRISE_OPENWEBUI_BASE_URL": "https://openwebui.internal",
            "ENTERPRISE_CONNECTOR_PUBLIC_BASE_URL": "https://connector.internal",
            **secret_values,
        }
    )

    subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--non-interactive",
            "--assume-yes",
            "--no-config-check",
            "--output-env",
            str(output_env),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    portainer_env = output_dir / "portainer.env"
    portainer_compose = output_dir / "portainer-compose.yml"
    assert portainer_env.read_text(encoding="utf-8") == output_env.read_text(encoding="utf-8")
    rendered_compose = portainer_compose.read_text(encoding="utf-8")
    assert "connector-controller:" in rendered_compose
    assert "CONNECTOR_SYSTEM_CA_BUNDLE=${CONNECTOR_SYSTEM_CA_BUNDLE:-" in rendered_compose
    assert "source: ${CONNECTOR_CERTS_HOST_DIR:-./certs}" in rendered_compose
    assert "type: bind" in rendered_compose
    assert str(ca_file) not in rendered_compose
    for secret in secret_values.values():
        assert secret not in rendered_compose
