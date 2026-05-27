<p align="center">
  <img src="docs/assets/hero.png" alt="Seafile RAGFlow Connector: offline-ready sync control plane between Seafile, RAGFlow, and optional OpenWebUI">
</p>

<p align="center">
  🌐 Languages: <a href="README.md">Deutsch</a> | <strong>English</strong>
</p>

<h1 align="center">Seafile RAGFlow Connector</h1>

<p align="center">
  Turns Seafile libraries into reproducible RAGFlow datasets and optional OpenWebUI custom models with delta sync, delete propagation, drift repair, TLS, audit, and Portainer-ready deployment.
</p>

<p align="center">
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/test.yml"><img alt="CI" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/test.yml/badge.svg?branch=master"></a>
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/docker.yml"><img alt="Docker image" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/docker.yml/badge.svg?branch=master"></a>
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/codeql.yml/badge.svg?branch=master"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="pyproject.toml"><img alt="Version 0.1.3" src="https://img.shields.io/badge/version-0.1.3-informational.svg"></a>
</p>

## Overview

The connector is an offline-ready sync control plane for environments where Seafile remains the document source of truth and RAGFlow receives reliable knowledge datasets. It can create one RAGFlow dataset per Seafile library from a template, import changed files incrementally, propagate deletions, repair drift in target systems, and optionally expose datasets as OpenWebUI tools and pipes without storing RAGFlow secrets inside OpenWebUI functions.

## Quick Links

| Goal | Entry point |
| --- | --- |
| Quick start | [Docker Compose](#docker-compose-quick-start) or [Portainer](#portainer-start) |
| Configuration | [`connector.env.example`](connector.env.example), [environment reference](docs/environment.md) |
| Operations | [operations guide](docs/operations.md) |
| Architecture | [architecture](docs/architecture.md) |
| Internationalization | [i18n and Unicode](docs/en/i18n.md), [German docs](docs/de/index.md) |
| TLS | [TLS topology](docs/tls-topology.md), [certificates](docs/tls-certificates.md), [troubleshooting](docs/troubleshooting-ssl.md) |
| Development | [development checks](#development) and [tests](docs/testing.md) |
| Contributing | [CONTRIBUTING.en.md](CONTRIBUTING.en.md), [security policy](SECURITY.en.md), [support](SUPPORT.en.md) |

## Features

| Area | Capability |
| --- | --- |
| Source of truth | Seafile remains authoritative. Target drift is repaired from Seafile, never written back to Seafile. |
| Dataset lifecycle | Library discovery, dataset creation from `connector_template`, upload, parse control, and state tracking. |
| Delta and delete | File changes, removed files, and deleted libraries are propagated to RAGFlow and optionally OpenWebUI. |
| Drift repair | Missing RAGFlow datasets/documents and owned OpenWebUI artifacts can be rebuilt from state and Seafile. |
| OpenWebUI | Auditable `Seafile · <dataset>` custom models with citation events, Markdown evidence tables, locators, and connector preview links. |
| Operations | PostgreSQL state, Redis jobs, dashboard, health, metrics, Excel audit export, TLS/CA bundles, GHCR, Portainer, Compose, and Swarm. |
| Quality | Ruff, strict mypy, pytest, unittest, CodeQL, Docker build workflow, and Dependabot. |

## Internationalization

German is the project default for CLI help, human-readable errors, dashboard text, OpenWebUI artifacts, the main README, and default documentation. English is the primary alternative language. Product components are also integrated for `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `uk`, `zh`, `ja`, and `ar`. Set `CONNECTOR_LANGUAGE=de`, `CONNECTOR_LANGUAGE=en`, or one of the additional language codes to choose explicitly. If no reliable language can be detected, the connector falls back to German. UTF-8 is preserved throughout, including umlauts, accents, non-Latin text, emoji, and bidirectional text stored or displayed as user content.

GitHub does not automatically switch the normal repository view by visitor language. This repository therefore uses explicit files and links: `README.md` is German, `README.en.md` is English, German docs start at `docs/de/index.md`, and English docs start at `docs/en/index.md`. More details are in [docs/en/i18n.md](docs/en/i18n.md).

## Docker Compose Quick Start

Copy the operator configuration and set the required values:

```bash
cp connector.env.example connector.env

docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet
```

Minimum values for Seafile to RAGFlow with the bundled PostgreSQL service:

| Variable | Purpose |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile URL reachable from the connector container |
| `SEAFILE_ADMIN_TOKEN` | Seafile admin API token for library discovery |
| `SEAFILE_SYNC_USER_TOKEN` | Seafile API token for file downloads |
| `RAGFLOW_BASE_URL` | RAGFlow API URL reachable from the connector container |
| `RAGFLOW_API_KEY` | API key of the target RAGFlow user |
| `POSTGRES_PASSWORD` | Password for the stack database when `DATABASE_URL` is not set |

Start the stack:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  up -d
```

Check logs and health:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  logs -f connector-controller connector-worker connector-reconciler

curl http://127.0.0.1:18080/api/health
```

## Portainer Start

1. Create a new stack in Portainer.
2. Paste `deploy/portainer/docker-compose.yml` into the web editor or use this repository as a Git stack.
3. Import the values from `connector.env.example` as environment variables.
4. Replace only the required values; set OpenWebUI values only when that integration is enabled.
5. Deploy the stack and inspect the logs of `connector-controller`, `connector-worker`, and `connector-reconciler`.

For production-like deployments, pin `CONNECTOR_IMAGE` to a fixed release tag
such as `ghcr.io/adrianweidig/seafile-ragflow-connector:0.1.3` after that
release has been published. Treat `latest` as a convenience tag for smoke tests
and fresh test environments.

## CLI

The package exposes the `connector` command:

| Command | Purpose |
| --- | --- |
| `connector init-db` | Create or migrate connector state tables |
| `connector check-live` | Check database, Redis, Seafile, and RAGFlow without mutation |
| `connector sync-once` | Run one full discovery and sync pass |
| `connector cleanup-orphans` | Plan or delete connector-owned orphan target artifacts |
| `connector openwebui-sync-once` | Run one OpenWebUI sync pass |
| `connector serve-dashboard` | Start the read-only dashboard |
| `connector run-controller`, `run-worker`, `run-reconciler` | Start runtime processes |

## Development

```bash
uv sync --locked --all-extras
python -m compileall src tests migrations
PYTHONPATH=src python -m unittest discover -s tests/unit
```

Full development environments can additionally run:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
python scripts/verify.py --skip-compose
```

When Docker Compose is available on the host, the verify runner can also check the Portainer Compose configuration:

```bash
python scripts/verify.py --with-compose
```

## Documentation

- [German documentation entry](docs/de/index.md)
- [English documentation entry](docs/en/index.md)
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Environment variables](docs/environment.md)
- [Testing model](docs/testing.md)
- [Operations](docs/operations.md)
- [Local HTTPS Compose path with connector.top.secret](docs/local-https-compose.md)
- [RAGFlow template behavior](docs/ragflow-template.md)
- [TLS certificates](docs/tls-certificates.md)
- [TLS topology](docs/tls-topology.md)
- [Docker Compose with TLS](docs/docker-compose-tls.md)
- [SSL/TLS troubleshooting](docs/troubleshooting-ssl.md)
- [FAQ](docs/FAQ.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [Maintainer checklist](docs/MAINTAINER_CHECKLIST.md)

## Contributing, Support, and Security

Contributions are welcome when they preserve the conservative sync model: Seafile remains the source of truth, target systems are rebuilt from it, secrets stay outside the repository, and productive systems are not mutated without an explicit operator action.

- Contributing: [CONTRIBUTING.en.md](CONTRIBUTING.en.md)
- Support: [SUPPORT.en.md](SUPPORT.en.md)
- Security reports: [SECURITY.en.md](SECURITY.en.md)
- Code of Conduct: [CODE_OF_CONDUCT.en.md](CODE_OF_CONDUCT.en.md)
- Changes: [CHANGELOG.en.md](CHANGELOG.en.md)

## License

This project is licensed under the [MIT License](LICENSE). For commercial or legally sensitive use, have the license decision reviewed by a human.
