from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMPOSE_FILES = (
    Path("deploy/compose/external-services.compose.yml"),
    Path("deploy/compose/openwebui.compose.yml"),
    Path("deploy/compose/shared-network.compose.yml"),
    Path("deploy/portainer/docker-compose.yml"),
    Path("deploy/swarm/docker-stack.yml"),
)

HOST_ONLY_ENV_KEYS = {
    "COMPOSE_PROJECT_NAME",
    "CONNECTOR_CERTS_HOST_DIR",
    "CONNECTOR_DASHBOARD_PUBLISHED_PORT",
    "CONNECTOR_DOCKER_NETWORK_EXTERNAL",
    "CONNECTOR_DOCKER_NETWORK_NAME",
    "CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE",
    "CONNECTOR_ENTERPRISE_CA_HOST_FILE",
    "CONNECTOR_IMAGE",
    "CONNECTOR_IMAGE_PULL_POLICY",
    "CONNECTOR_SWARM_NETWORK_NAME",
    "POSTGRES_IMAGE",
    "POSTGRES_IMAGE_PULL_POLICY",
    "REDIS_IMAGE",
    "REDIS_IMAGE_PULL_POLICY",
}


def main() -> int:
    expected = _connector_env_example_keys() - HOST_ONLY_ENV_KEYS
    failed = False
    for compose_file in COMPOSE_FILES:
        actual = _compose_connector_env_keys(compose_file)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing or unknown:
            failed = True
            print(f"{compose_file}: connector environment drift detected", file=sys.stderr)
            if missing:
                print("  missing: " + ", ".join(missing), file=sys.stderr)
            if unknown:
                print("  unknown: " + ", ".join(unknown), file=sys.stderr)
    if failed:
        return 1
    print("Deployment connector environment blocks are aligned.")
    return 0


def _connector_env_example_keys() -> set[str]:
    text = (ROOT / "connector.env.example").read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE)
    }


def _compose_connector_env_keys(path: Path) -> set[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    start_marker = "x-connector-env:"
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{path}: x-connector-env block not found")
    end = text.find("\nx-", start + len(start_marker))
    if end < 0:
        end = text.find("\nservices:", start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"{path}: x-connector-env block end not found")
    block = text[start:end]
    return {
        match.group(1)
        for match in re.finditer(r"^  ([A-Z][A-Z0-9_]*):", block, flags=re.MULTILINE)
    }


if __name__ == "__main__":
    raise SystemExit(main())
