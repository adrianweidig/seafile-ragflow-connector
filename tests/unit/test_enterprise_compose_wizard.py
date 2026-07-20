from __future__ import annotations

import os
import shutil
import stat
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


def _assert_owner_only(path: Path) -> None:
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _find_portable_bash() -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is required for enterprise compose wizard")
    if os.name == "nt" and "system32" in str(Path(bash)).lower():
        pytest.skip("Windows WSL bash cannot execute repository-local Windows paths")
    return bash


def _clean_process_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "RAGFLOW_INTERACTIVE_API_KEY",
        "RAGFLOW_INTERACTIVE_OWNER_ID",
        "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID",
        "RAGFLOW_GENERATED_DATASET_PERMISSION",
    ):
        env.pop(name, None)
    return env


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
    output_env.write_text("RAGFLOW_API_KEY=previous-secret\n", encoding="utf-8")
    output_env.chmod(0o644)
    secret_values = {
        "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
        "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
        "RAGFLOW_API_KEY": "ragflow-secret",
        "RAGFLOW_INTERACTIVE_API_KEY": "ragflow-interactive-secret",
        "AUTHZ_API_SHARED_SECRET": "authz-secret",
        "OPENWEBUI_ADMIN_API_KEY": "openwebui-secret",
        "POSTGRES_PASSWORD": "postgres-secret",
        "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
        "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
    }
    env = _clean_process_env()
    env.pop("SSL_CERT_FILE", None)
    env.pop("REQUESTS_CA_BUNDLE", None)
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
            "CONNECTOR_DASHBOARD_CONTROL_ENABLED": "true",
            "SEAFILE_SYNC_USER_EMAIL": "sync@auth.local",
            "SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED": "true",
            "RAGFLOW_INTERACTIVE_OWNER_ID": "interactive-owner-id",
            "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID": "interactive-chat-model-id",
            "RAGFLOW_GENERATED_DATASET_PERMISSION": "team",
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
    _assert_owner_only(output_env)
    backups = list(tmp_path.glob("connector.env.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "RAGFLOW_API_KEY=previous-secret\n"
    _assert_owner_only(backups[0])
    ca_env_path = _env_value(generated_env, "CONNECTOR_ENTERPRISE_CA_HOST_FILE")
    assert ca_env_path
    assert ca_env_path.replace("\\", "/").endswith("/root-ca.pem")
    assert "CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE=/certs/company-root-ca.pem" in generated_env
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in generated_env
    assert "SEAFILE_VERIFY_SSL=true" in generated_env
    assert "SEAFILE_PUBLIC_BASE_URL=https://files.internal" in generated_env
    assert "SEAFILE_SYNC_USER_EMAIL=sync@auth.local" in generated_env
    assert "SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED=true" in generated_env
    assert "SEAFILE_FILE_URL_TEMPLATE=\n" in generated_env
    assert "RAGFLOW_CA_BUNDLE=/certs/company-root-ca.pem" in generated_env
    assert "AUTHZ_API_SHARED_SECRET=authz-secret" in generated_env
    assert "SEARCH_AUTHZ_SHARED_SECRET=authz-secret" in generated_env
    assert "SEARCH_RAGFLOW_BASE_URL=https://ragflow.internal" in generated_env
    assert "RAGFLOW_INTERACTIVE_API_KEY=ragflow-interactive-secret" in generated_env
    assert "RAGFLOW_INTERACTIVE_OWNER_ID=interactive-owner-id" in generated_env
    assert "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID=interactive-chat-model-id" in generated_env
    assert "RAGFLOW_GENERATED_DATASET_PERMISSION=team" in generated_env
    assert "SEARCH_RAGFLOW_API_KEY=ragflow-interactive-secret" in generated_env
    assert "SEARCH_SERVICE_ENABLED=true" in generated_env
    assert "OPENWEBUI_SOURCE_PREVIEW_MODE=connector_viewer" in generated_env
    assert "OPENWEBUI_PROXY_PUBLIC_BASE_URL=https://connector.internal" in generated_env
    assert "CONNECTOR_DASHBOARD_CONTROL_ENABLED=true" in generated_env
    assert "CONNECTOR_AUTOMATION_INITIAL_STATE=stopped" in generated_env
    assert "CONNECTOR_STARTUP_CHECK=infra" in generated_env
    assert "CONNECTOR_BOOTSTRAP_CHECK_LIVE=false" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/external-services.compose.yml" in compose_files
    assert "deploy/compose/bundled-state.compose.yml" in compose_files
    assert "deploy/compose/search.compose.yml" in compose_files
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
    env = _clean_process_env()
    env.pop("CONNECTOR_DASHBOARD_CONTROL_ENABLED", None)
    env.pop("CONNECTOR_AUTOMATION_INITIAL_STATE", None)
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
    assert "RAGFLOW_INTERACTIVE_API_KEY=\n" in generated_env
    assert "RAGFLOW_INTERACTIVE_OWNER_ID=\n" in generated_env
    assert "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID=\n" in generated_env
    assert "RAGFLOW_GENERATED_DATASET_PERMISSION=me" in generated_env
    assert "SEARCH_RAGFLOW_API_KEY=ragflow-secret" in generated_env
    assert "OPENWEBUI_ADMIN_API_KEY=\n" in generated_env
    assert "OPENWEBUI_SYNC_MODE=disabled" in generated_env
    assert "SEAFILE_PUBLIC_BASE_URL=https://seafile.internal" in generated_env
    assert "CONNECTOR_STARTUP_CHECK=infra" in generated_env
    assert "CONNECTOR_BOOTSTRAP_CHECK_LIVE=false" in generated_env
    assert "CONNECTOR_DASHBOARD_CONTROL_ENABLED=false" in generated_env
    assert "CONNECTOR_AUTOMATION_INITIAL_STATE=running" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/external-services.compose.yml" in compose_files
    assert "deploy/compose/bundled-state.compose.yml" in compose_files
    assert "deploy/compose/search.compose.yml" in compose_files
    assert "deploy/compose/enterprise-ca.compose.yml" not in compose_files


@pytest.mark.parametrize(
    ("interactive_values", "expected_error"),
    [
        (
            {
                "RAGFLOW_INTERACTIVE_API_KEY": "ragflow-interactive-secret",
                "RAGFLOW_GENERATED_DATASET_PERMISSION": "team",
            },
            "RAGFLOW_INTERACTIVE_OWNER_ID ist erforderlich",
        ),
        (
            {
                "RAGFLOW_INTERACTIVE_API_KEY": "ragflow-interactive-secret",
                "RAGFLOW_INTERACTIVE_OWNER_ID": "interactive-owner-id",
                "RAGFLOW_GENERATED_DATASET_PERMISSION": "team",
            },
            "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID ist erforderlich",
        ),
        (
            {
                "RAGFLOW_INTERACTIVE_API_KEY": "ragflow-interactive-secret",
                "RAGFLOW_INTERACTIVE_OWNER_ID": "interactive-owner-id",
                "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID": "interactive-chat-model-id",
                "RAGFLOW_GENERATED_DATASET_PERMISSION": "me",
            },
            "RAGFLOW_GENERATED_DATASET_PERMISSION muss bei gesetztem "
            "RAGFLOW_INTERACTIVE_API_KEY team sein",
        ),
    ],
)
def test_enterprise_compose_wizard_rejects_incomplete_interactive_owner_config(
    tmp_path: Path,
    interactive_values: dict[str, str],
    expected_error: str,
) -> None:
    bash = _find_portable_bash()
    env = _clean_process_env()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_PORTAINER_BUNDLE": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_WITH_SEARCH": "false",
            "ENTERPRISE_WITH_OPENWEBUI": "false",
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
            "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
            "RAGFLOW_API_KEY": "ragflow-secret",
            **interactive_values,
        }
    )

    result = subprocess.run(
        [
            bash,
            str(SCRIPT),
            "--non-interactive",
            "--assume-yes",
            "--no-config-check",
            "--output-env",
            str(tmp_path / "connector.env"),
            "--output-dir",
            str(tmp_path / "generated"),
        ],
        cwd=ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr


def test_enterprise_compose_wizard_supports_external_state_and_core_only(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()

    output_env = tmp_path / "connector.env"
    output_dir = tmp_path / "generated"
    env = _clean_process_env()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_PORTAINER_BUNDLE": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_STATE_MODE": "external",
            "ENTERPRISE_WITH_SEARCH": "false",
            "ENTERPRISE_WITH_OPENWEBUI": "false",
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
            "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
            "RAGFLOW_API_KEY": "ragflow-secret",
            "AUTHZ_API_SHARED_SECRET": "authz-secret",
            "DATABASE_URL": "postgresql://sync:db-secret@database.internal/connector",
            "REDIS_URL": "redis://:redis-secret@redis.internal/0",
            "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
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
    assert "POSTGRES_PASSWORD=\n" in generated_env
    assert "DATABASE_URL=postgresql://sync:db-secret@database.internal/connector" in generated_env
    assert "REDIS_URL=redis://:redis-secret@redis.internal/0" in generated_env
    assert "SEARCH_SERVICE_ENABLED=false" in generated_env

    compose_files = (output_dir / "compose-files.txt").read_text(encoding="utf-8")
    assert "deploy/compose/external-services.compose.yml" in compose_files
    assert "deploy/compose/external-state.compose.yml" in compose_files
    assert "deploy/compose/bundled-state.compose.yml" not in compose_files
    assert "deploy/compose/search.compose.yml" not in compose_files


def test_enterprise_compose_wizard_keeps_proxy_ca_empty_for_internal_http(
    tmp_path: Path,
) -> None:
    bash = _find_portable_bash()

    ca_file = _make_root_ca(tmp_path)
    output_env = tmp_path / "shared.env"
    output_dir = tmp_path / "shared-generated"
    env = _clean_process_env()
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
            "AUTHZ_API_SHARED_SECRET": "authz-secret",
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
        "RAGFLOW_INTERACTIVE_API_KEY": "ragflow-interactive-secret",
        "AUTHZ_API_SHARED_SECRET": "authz-secret",
        "OPENWEBUI_ADMIN_API_KEY": "openwebui-secret",
        "POSTGRES_PASSWORD": "postgres-secret",
        "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
        "OPENWEBUI_PROXY_SHARED_SECRET": "proxy-secret",
    }
    env = _clean_process_env()
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
            "RAGFLOW_INTERACTIVE_OWNER_ID": "interactive-owner-id",
            "RAGFLOW_INTERACTIVE_CHAT_MODEL_ID": "interactive-chat-model-id",
            "RAGFLOW_GENERATED_DATASET_PERMISSION": "team",
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
    _assert_owner_only(output_env)
    _assert_owner_only(portainer_env)
    assert portainer_env.read_text(encoding="utf-8") == output_env.read_text(encoding="utf-8")
    rendered_compose = portainer_compose.read_text(encoding="utf-8")
    assert "connector-controller:" in rendered_compose
    assert "CONNECTOR_SYSTEM_CA_BUNDLE=${CONNECTOR_SYSTEM_CA_BUNDLE:-" in rendered_compose
    assert "source: ${CONNECTOR_CERTS_HOST_DIR:-./certs}" in rendered_compose
    assert "type: bind" in rendered_compose
    assert str(ca_file) not in rendered_compose
    for secret in secret_values.values():
        assert secret not in rendered_compose


def test_enterprise_compose_wizard_renders_external_state_core_only_bundle(
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

    output_env = tmp_path / "connector.env"
    output_dir = tmp_path / "generated"
    env = _clean_process_env()
    env.update(
        {
            "ENTERPRISE_NONINTERACTIVE": "true",
            "ENTERPRISE_ASSUME_YES": "true",
            "ENTERPRISE_RUN_CONFIG_CHECK": "false",
            "ENTERPRISE_MODE": "external",
            "ENTERPRISE_STATE_MODE": "external",
            "ENTERPRISE_WITH_SEARCH": "false",
            "ENTERPRISE_WITH_OPENWEBUI": "false",
            "ENTERPRISE_SEAFILE_BASE_URL": "https://seafile.internal",
            "ENTERPRISE_RAGFLOW_BASE_URL": "https://ragflow.internal",
            "SEAFILE_ADMIN_TOKEN": "seafile-admin-secret",
            "SEAFILE_SYNC_USER_TOKEN": "seafile-sync-secret",
            "RAGFLOW_API_KEY": "ragflow-secret",
            "AUTHZ_API_SHARED_SECRET": "authz-secret",
            "DATABASE_URL": "postgresql://sync:db-secret@database.internal/connector",
            "REDIS_URL": "redis://:redis-secret@redis.internal/0",
            "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "dashboard-secret",
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

    rendered_compose = (output_dir / "portainer-compose.yml").read_text(encoding="utf-8")
    assert "connector-controller:" in rendered_compose
    assert rendered_compose.count("\n  connector-postgres:\n") == 1
    assert rendered_compose.count("\n  connector-redis:\n") == 1
    assert rendered_compose.count("    profiles:\n      - bundled-state") >= 2
    assert "connector-search:" not in rendered_compose
    assert "db-secret" not in rendered_compose
    assert "redis-secret" not in rendered_compose
