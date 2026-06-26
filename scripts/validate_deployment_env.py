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

SEARCH_COMPOSE_FILES = (
    Path("deploy/compose/search.compose.yml"),
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
    "SEARCH_SERVICE_PUBLISHED_PORT",
}

CONNECTOR_SHARED_SEARCH_KEYS = {
    "SEARCH_ANSWER_GENERATION_MODE",
    "SEARCH_ANSWER_LLM_API_KEY",
    "SEARCH_ANSWER_LLM_BASE_URL",
    "SEARCH_ANSWER_LLM_MAX_TOKENS",
    "SEARCH_ANSWER_LLM_MODEL",
    "SEARCH_ANSWER_LLM_TEMPERATURE",
    "SEARCH_ANSWER_LLM_TIMEOUT_SECONDS",
    "SEARCH_DOCUMENT_VIEWER_ENABLED",
    "SEARCH_DOCUMENT_VIEWER_MAX_MB",
    "SEARCH_RAGFLOW_CANDIDATE_TOP_K",
    "SEARCH_RAGFLOW_CROSS_LANGUAGES",
    "SEARCH_RAGFLOW_HIGHLIGHT",
    "SEARCH_RAGFLOW_KEYWORD",
    "SEARCH_RAGFLOW_RERANK_ID",
    "SEARCH_RAGFLOW_SIMILARITY_THRESHOLD",
    "SEARCH_RAGFLOW_TEMPLATE_SOURCE_ORDER",
    "SEARCH_RAGFLOW_TOC_ENHANCE",
    "SEARCH_RAGFLOW_TOP_N",
    "SEARCH_RAGFLOW_USE_KG",
    "SEARCH_RAGFLOW_VECTOR_SIMILARITY_WEIGHT",
}


def main() -> int:
    env_keys = _connector_env_example_keys()
    search_service_keys = {
        key
        for key in env_keys
        if key.startswith("SEARCH_")
        and not key.startswith("SEARCH_ACL_")
        and key not in CONNECTOR_SHARED_SEARCH_KEYS
    }
    shared_search_keys = env_keys & CONNECTOR_SHARED_SEARCH_KEYS
    expected = env_keys - HOST_ONLY_ENV_KEYS - search_service_keys
    expected_search = (search_service_keys | shared_search_keys) - HOST_ONLY_ENV_KEYS
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
    for compose_file in SEARCH_COMPOSE_FILES:
        actual = _compose_search_env_keys(compose_file, expected_search)
        missing = sorted(expected_search - actual)
        if missing:
            failed = True
            print(f"{compose_file}: search environment drift detected", file=sys.stderr)
            print("  missing: " + ", ".join(missing), file=sys.stderr)
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


def _compose_search_env_keys(path: Path, expected_search: set[str]) -> set[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    if "connector-search:" not in text:
        raise RuntimeError(f"{path}: connector-search service not found")
    return {
        match.group(1)
        for match in re.finditer(r"^\s+([A-Z][A-Z0-9_]*):", text, flags=re.MULTILINE)
        if match.group(1) in expected_search
    }


if __name__ == "__main__":
    raise SystemExit(main())
