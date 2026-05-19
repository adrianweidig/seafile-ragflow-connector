# Seafile RAGFlow Connector

Offline-first sync orchestrator that runs between an existing Seafile server and an
existing RAGFlow server. It discovers Seafile libraries, creates one RAGFlow dataset
per library from a `connector_template`, imports files, tracks changes, handles safe
deletes, and keeps running through restarts.

## Core Principles

- Seafile API is the source of truth.
- RAGFlow API is the target system.
- PostgreSQL stores durable sync memory.
- Redis provides queueing, retries, and backpressure.
- RAGFlow dataset settings are live after creation. The template is only used to
  create new datasets.
- The runtime is offline-capable: no package downloads, no telemetry, and no
  external service dependency beyond configured Seafile and RAGFlow URLs.

## Offline Portainer Deployment

1. Import the required images on the Docker host, for example:
   `docker load -i images/seafile-ragflow-connector_0.1.0.tar`
2. Create a new Portainer stack.
3. Paste `docker-compose.portainer.yml`.
4. Copy `stack.env.example` to `stack.env` and fill in local Seafile/RAGFlow URLs
   and tokens.
5. Start the stack.
6. Check controller logs and `/readyz`.

Seafile and RAGFlow are not deployed by this stack. They remain external systems
reachable over your LAN, reverse proxy, or a shared Docker network.

## Development Checks

```bash
python -m compileall src tests
python -m unittest discover -s tests/unit
```

Full development environments can also run:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
```

## Documentation

- [Architecture](docs/architecture.md)
- [Offline deployment](docs/offline-deployment.md)
- [Portainer operations](docs/portainer.md)
- [Configuration](docs/configuration.md)
- [RAGFlow template behavior](docs/ragflow-template.md)
- [Recovery](docs/recovery.md)
- [Troubleshooting](docs/troubleshooting.md)

