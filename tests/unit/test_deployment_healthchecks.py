from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_DEPLOYMENTS = (
    "deploy/compose/external-services.compose.yml",
    "deploy/compose/openwebui.compose.yml",
    "deploy/compose/shared-network.compose.yml",
    "deploy/portainer/docker-compose.yml",
    "deploy/swarm/docker-stack.yml",
)


def test_controller_container_healthchecks_use_liveness() -> None:
    for relative_path in CONTROLLER_DEPLOYMENTS:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        controller_block = _service_block(text, "connector-controller")

        assert "/livez" in controller_block, relative_path
        assert "/readyz" not in controller_block, relative_path


def _service_block(text: str, service: str) -> str:
    marker = f"  {service}:"
    start = text.index(marker)
    remainder = text[start + len(marker) :]
    next_service = re.search(r"(?m)^  [a-z0-9][a-z0-9_-]*:\s*$", remainder)
    if next_service is None:
        return text[start:]
    return text[start : start + len(marker) + next_service.start()]
