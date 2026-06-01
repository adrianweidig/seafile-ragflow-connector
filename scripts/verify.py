from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the repository's repeatable local verification checks."
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Assume dependencies are already installed and skip uv sync.",
    )
    parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Skip Docker Compose configuration validation.",
    )
    parser.add_argument(
        "--with-compose",
        action="store_true",
        help="Require Docker Compose configuration validation.",
    )
    parser.add_argument(
        "--with-mock-smoke",
        action="store_true",
        help="Run the local HTTPS mock Compose smoke check. Requires Docker Compose.",
    )
    parser.add_argument(
        "--with-dashboard-browser-smoke",
        action="store_true",
        help="Run the local Playwright browser smoke check for the dashboard.",
    )
    args = parser.parse_args()

    checks: list[tuple[str, Sequence[str], dict[str, str] | None]] = []
    if not args.skip_sync:
        checks.append(("Install dependencies", ("uv", "sync", "--locked", "--all-extras"), None))
    checks.extend(
        [
            (
                "Compile Python sources",
                (
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "compileall",
                    "src",
                    "tests",
                    "migrations",
                    "scripts",
                ),
                None,
            ),
            ("Lint", ("uv", "run", "ruff", "check", "."), None),
            ("Typecheck", ("uv", "run", "mypy", "src"), None),
            (
                "Deployment environment drift check",
                ("uv", "run", "python", "scripts/validate_deployment_env.py"),
                None,
            ),
            ("Pytest suite", ("uv", "run", "pytest"), None),
            (
                "Unit tests via unittest",
                ("uv", "run", "python", "-m", "unittest", "discover", "-s", "tests/unit"),
                {"PYTHONPATH": "src"},
            ),
        ]
    )

    for label, command, env_overlay in checks:
        if not run(label, command, env_overlay=env_overlay):
            return 1

    if not run_optional("Git diff whitespace check", ("git", "diff", "--check")):
        return 1

    if not args.skip_compose:
        compose_command = (
            "docker",
            "compose",
            "--env-file",
            "connector.env.example",
            "-f",
            "deploy/portainer/docker-compose.yml",
            "config",
            "--quiet",
        )
        if args.with_compose:
            if not run("Docker Compose config", compose_command):
                return 1
        else:
            run_optional("Docker Compose config", compose_command)

    if args.with_mock_smoke and not run_mock_smoke():
        return 1

    if args.with_dashboard_browser_smoke and not run(
        "Dashboard browser smoke",
        ("uv", "run", "--extra", "dev", "python", "scripts/playwright_dashboard_smoke.py"),
    ):
        return 1

    print("\nAll requested verification checks completed.")
    return 0


def run(label: str, command: Sequence[str], *, env_overlay: dict[str, str] | None = None) -> bool:
    print(f"\n==> {label}")
    print(format_command(command))
    env = os.environ.copy()
    if env_overlay:
        env.update(env_overlay)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        print(f"FAILED: {label} exited with {completed.returncode}", file=sys.stderr)
        return False
    return True


def run_optional(label: str, command: Sequence[str]) -> bool:
    executable = command[0]
    if shutil.which(executable) is None:
        print(f"\n==> {label}")
        print(f"SKIPPED: {executable!r} is not available on PATH")
        return True
    return run(label, command)


def run_mock_smoke() -> bool:
    if shutil.which("docker") is None:
        print("\n==> Local HTTPS mock smoke")
        print("FAILED: 'docker' is not available on PATH", file=sys.stderr)
        return False
    if not run_optional("Docker Compose version", ("docker", "compose", "version")):
        return False

    certs_dir = ROOT / "deploy" / "tls-lab" / "certs"
    if not run(
        "Generate local TLS lab certificates",
        (
            "uv",
            "run",
            "python",
            "deploy/tls-lab/generate_certs.py",
            "--out-dir",
            str(certs_dir),
        ),
    ):
        return False

    env_overlay = {
        "COMPOSE_PROJECT_NAME": "seafile-ragflow-connector-mock-smoke",
        "CONNECTOR_IMAGE": "seafile-ragflow-connector:mock-smoke",
        "CONNECTOR_IMAGE_PULL_POLICY": "never",
        "CONNECTOR_CERTS_HOST_DIR": str(certs_dir),
        "CONNECTOR_DASHBOARD_ENABLED": "true",
        "CONNECTOR_DASHBOARD_AUTH_USERNAME": "admin",
        "CONNECTOR_DASHBOARD_AUTH_PASSWORD": "change-me-dashboard-password",
        "CONNECTOR_STARTUP_CHECK": "infra",
        "POSTGRES_PASSWORD": "mock-smoke-postgres",
        "SEAFILE_BASE_URL": "https://seafile.top.secret:8443",
        "SEAFILE_ADMIN_TOKEN": "mock-smoke-seafile-admin",
        "SEAFILE_SYNC_USER_TOKEN": "mock-smoke-seafile-sync",
        "SEAFILE_CA_BUNDLE": "/certs/top-secret-root-ca.pem",
        "RAGFLOW_BASE_URL": "https://rag.top.secret:8443",
        "RAGFLOW_API_KEY": "mock-smoke-ragflow",
        "RAGFLOW_CA_BUNDLE": "/certs/top-secret-root-ca.pem",
        "OPENWEBUI_INTEGRATION_ENABLED": "false",
        "OPENWEBUI_SYNC_MODE": "disabled",
    }
    compose_command = (
        "docker",
        "compose",
        "--env-file",
        "connector.env.example",
        "-f",
        "deploy/compose/external-services.compose.yml",
        "-f",
        "deploy/compose/local-mocks.compose.yml",
    )
    try:
        if not run(
            "Local HTTPS mock connector image build",
            (
                "docker",
                "build",
                "-t",
                "seafile-ragflow-connector:mock-smoke",
                "-f",
                "deploy/docker/Dockerfile",
                ".",
            ),
            env_overlay=env_overlay,
        ):
            return False
        if not run(
            "Local HTTPS mock Compose pre-clean",
            (*compose_command, "down", "--remove-orphans", "--volumes"),
            env_overlay=env_overlay,
        ):
            return False
        if not run(
            "Local HTTPS mock Compose up",
            (*compose_command, "up", "-d"),
            env_overlay=env_overlay,
        ):
            return False
        if not wait_for_compose_services(
            compose_command,
            (
                "connector-postgres",
                "connector-redis",
                "seafile-mock",
                "ragflow-mock",
                "connector-controller",
                "connector-worker",
                "connector-reconciler",
            ),
            env_overlay=env_overlay,
        ):
            return False
        if not run(
            "Local HTTPS mock check-live",
            (
                *compose_command,
                "exec",
                "-T",
                "connector-controller",
                "connector",
                "check-live",
                "--json",
            ),
            env_overlay=env_overlay,
        ):
            return False
        return run(
            "Local HTTPS mock TLS health",
            (
                *compose_command,
                "exec",
                "-T",
                "connector-controller",
                "python",
                "-c",
                (
                    "import base64, os, urllib.request; "
                    "auth = base64.b64encode("
                    "(os.environ['CONNECTOR_DASHBOARD_AUTH_USERNAME'] + ':' + "
                    "os.environ['CONNECTOR_DASHBOARD_AUTH_PASSWORD']).encode()).decode(); "
                    "request = urllib.request.Request("
                    "'http://127.0.0.1:8080/health/tls', "
                    "headers={'Authorization': 'Basic ' + auth}); "
                    "print(urllib.request.urlopen(request, "
                    "timeout=10).read().decode())"
                ),
            ),
            env_overlay=env_overlay,
        )
    finally:
        run(
            "Local HTTPS mock Compose down",
            (*compose_command, "down", "--remove-orphans", "--volumes"),
            env_overlay=env_overlay,
        )


def wait_for_compose_services(
    compose_command: Sequence[str],
    services: Sequence[str],
    *,
    env_overlay: dict[str, str],
    timeout_seconds: int = 180,
) -> bool:
    print("\n==> Local HTTPS mock service health")
    deadline = time.monotonic() + timeout_seconds
    env = os.environ.copy()
    env.update(env_overlay)
    last_statuses: dict[str, str] = {}
    while time.monotonic() < deadline:
        statuses: dict[str, str] = {}
        failed = False
        for service in services:
            container_id = _capture((*compose_command, "ps", "-q", service), env=env)
            if not container_id:
                statuses[service] = "missing"
                failed = True
                continue
            status = _capture(
                (
                    "docker",
                    "inspect",
                    "-f",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    container_id,
                ),
                env=env,
            )
            statuses[service] = status or "unknown"
            if status in {"exited", "dead", "removing", "unhealthy"}:
                failed = True
        if statuses != last_statuses:
            print(format_statuses(statuses))
            last_statuses = statuses
        if statuses and all(status in {"healthy", "running"} for status in statuses.values()):
            return True
        if failed:
            break
        time.sleep(5)
    print("FAILED: local HTTPS mock services did not become healthy", file=sys.stderr)
    return False


def _capture(command: Sequence[str], *, env: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def format_statuses(statuses: dict[str, str]) -> str:
    return ", ".join(f"{service}={status}" for service, status in statuses.items())


if __name__ == "__main__":
    raise SystemExit(main())
