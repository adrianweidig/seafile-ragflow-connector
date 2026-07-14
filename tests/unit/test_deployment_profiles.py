from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_compose_state_profiles_have_distinct_required_inputs() -> None:
    bundled = _text("deploy/compose/bundled-state.compose.yml")
    external = _text("deploy/compose/external-state.compose.yml")

    assert "POSTGRES_PASSWORD:?" in bundled
    assert "DATABASE_URL:?" not in bundled
    assert "DATABASE_URL:?" in external
    assert "REDIS_URL:?" in external
    assert "profiles: [bundled-state]" in external
    assert "required: false" in external
    assert "POSTGRES_PASSWORD" not in external

    for relative_path in (
        "deploy/compose/external-services.compose.yml",
        "deploy/compose/shared-network.compose.yml",
        "deploy/compose/openwebui.compose.yml",
        "deploy/compose/search.compose.yml",
    ):
        assert "POSTGRES_PASSWORD:?" not in _text(relative_path), relative_path


def test_search_service_is_standard_or_omitted_instead_of_disabled() -> None:
    for relative_path in (
        "deploy/compose/search.compose.yml",
        "deploy/portainer/docker-compose.yml",
        "deploy/swarm/search.yml",
    ):
        text = _text(relative_path)
        assert 'SEARCH_SERVICE_ENABLED: "true"' in text, relative_path
        assert "SEARCH_SERVICE_ENABLED: ${SEARCH_SERVICE_ENABLED" not in text, relative_path

    assert "connector-search:" not in _text("deploy/compose/external-services.compose.yml")
    assert "connector-search:" not in _text("deploy/compose/shared-network.compose.yml")
    assert "connector-search:" not in _text("deploy/compose/openwebui.compose.yml")


def test_swarm_search_port_and_state_overlays_are_explicit() -> None:
    stack = _text("deploy/swarm/search.yml")
    search_block = stack[stack.index("  connector-search:") :]

    assert "target: ${SEARCH_SERVICE_PORT:-8090}" in search_block
    assert "published: ${SEARCH_SERVICE_PUBLISHED_PORT:-18090}" in search_block
    assert "connector-search:" not in _text("deploy/swarm/docker-stack.yml")
    assert "POSTGRES_PASSWORD:?" in _text("deploy/swarm/bundled-state.yml")

    external = _text("deploy/swarm/external-state.yml")
    assert "DATABASE_URL:?" in external
    assert "REDIS_URL:?" in external
    assert external.count("replicas: 0") == 2
