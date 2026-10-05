<p align="center">
  <img src="docs/assets/hero.png" alt="Seafile RAGFlow Connector: offline-ready sync control plane between Seafile, RAGFlow, and optional OpenWebUI">
</p>

<p align="center">
  🌐 Languages: <a href="README.md">Deutsch</a> | <strong>English</strong>
</p>

<h1 align="center">Seafile RAGFlow Connector</h1>

<p align="center">
  Syncs Seafile libraries into RAGFlow and can expose them as OpenWebUI models.
</p>

<p align="center">
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/test.yml"><img alt="CI" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/test.yml/badge.svg?branch=master"></a>
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/docker.yml"><img alt="Docker image" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/docker.yml/badge.svg?branch=master"></a>
  <a href="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/adrianweidig/seafile-ragflow-connector/actions/workflows/codeql.yml/badge.svg?branch=master"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="pyproject.toml"><img alt="Version 2.6.3" src="https://img.shields.io/badge/version-2.6.3-informational.svg"></a>
</p>

## Overview

The connector keeps Seafile as the source of truth. It discovers libraries,
creates matching RAGFlow datasets, imports changed files, and triggers parsing.
Removed files or libraries are cleaned up in the target systems in a traceable
way; missing target artifacts can be rebuilt from Seafile.

Optionally, the connector creates OpenWebUI chats, tools, and pipes for those
datasets. OpenWebUI talks to the connector proxy, so RAGFlow admin secrets do
not have to live inside OpenWebUI function code.

## Quick Links

| Goal | Entry point |
| --- | --- |
| Demo | [Demo video](#demo) |
| Quick start | [Docker Compose](#docker-compose-quick-start) or [Portainer](#portainer-start) |
| Admin first start | [first-start checklist](docs/en/admin-first-start-checklist.md) |
| Dashboard administration | [interactive surface](#dashboard-administration), [safe operations](docs/operations.md#dashboard-im-betrieb) |
| Configuration | [`connector.env.example`](connector.env.example), [environment reference](docs/environment.md) |
| Operations | [operations guide](docs/operations.md) |
| Architecture | [architecture](docs/architecture.md) |
| Internationalization | [i18n and Unicode](docs/en/i18n.md), [German docs](docs/de/index.md) |
| TLS | [TLS topology](docs/tls-topology.md), [certificates](docs/tls-certificates.md), [troubleshooting](docs/troubleshooting-ssl.md) |
| Development | [development checks](#development) and [tests](docs/testing.md) |
| Contributing | [CONTRIBUTING.en.md](CONTRIBUTING.en.md), [security policy](SECURITY.en.md), [support](SUPPORT.en.md) |

## Demo

The video shows the normal connector flow, not a manual RAGFlow setup: prepare
the Seafile library, upload a file, start connector sync, and then verify that
the RAGFlow dataset, RAGFlow chat, and OpenWebUI pipe were created
automatically. The final step checks the OpenWebUI answer against preview and
original file.

The final silent recording is checked in as MKV. The MP4 file is a
browser-friendly derivative of the same recording.

[![Demo video: connector creates RAGFlow dataset and chat automatically](docs/assets/demo/seafile-ragflow-connector-demo-poster.jpg)](docs/assets/demo/seafile-ragflow-connector-demo.mkv)

[Download final MKV](docs/assets/demo/seafile-ragflow-connector-demo.mkv)
· [Watch MP4 preview](docs/assets/demo/seafile-ragflow-connector-demo.mp4)
· [Contact sheet](artifacts/demo-recording-contact-sheet.jpg)
· [Recording runbook](docs/en/demo-recording.md)

## Features

| Area | Capability |
| --- | --- |
| Source of truth | Seafile remains authoritative. Target drift is repaired from Seafile, never written back to Seafile. |
| Dataset lifecycle | Library discovery, dataset creation from `connector_template`, upload, parse control, and state tracking. |
| Sync and delete | Commit-pinned snapshots and cursors provide real delta runs. When no trustworthy baseline exists, the connector falls back to a controlled full sync. Deletions are propagated to RAGFlow and optionally OpenWebUI. |
| Drift repair | A reconciliation plan compares the Seafile snapshot, connector state, and RAGFlow; repairs run as persistent, deduplicated jobs. |
| OpenWebUI | Auditable `Seafile · <dataset>` custom models with German evidence tables by default, stable `[S1]` source IDs, claim coverage, source roles, scores, locators, and connector preview links. |
| Dashboard and administration | Persistent global and per-library controls, delta/full/reconcile runs, processing and parsing progress, targeted connector-owned artifact deletion, health, metrics, logs, and Excel audit export. |
| Operations | PostgreSQL state, Redis jobs, TLS/CA bundles, GHCR, Portainer, Compose, and Swarm. |
| Quality | Ruff, strict mypy, pytest, unittest, CodeQL, Docker build workflow, and Dependabot. |

## Internationalization

German is the project default for CLI help, human-readable errors, dashboard text, OpenWebUI artifacts, the main README, and default documentation. English is the primary alternative language. Product components are also integrated for `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `uk`, `zh`, `ja`, and `ar`. Set `CONNECTOR_LANGUAGE=de`, `CONNECTOR_LANGUAGE=en`, or one of the additional language codes to choose explicitly. If no reliable language can be detected, the connector falls back to German. UTF-8 is preserved throughout, including umlauts, accents, non-Latin text, emoji, and bidirectional text stored or displayed as user content.

GitHub does not automatically switch the normal repository view by visitor language. This repository therefore uses explicit files and links: `README.md` is German, `README.en.md` is English, German docs start at `docs/de/index.md`, and English docs start at `docs/en/index.md`. More details are in [docs/en/i18n.md](docs/en/i18n.md).

## Docker Compose Quick Start

For enterprise networks with HTTPS, optional internal root CA, and optional
OpenWebUI wiring, the guided wizard is the fastest path:

```bash
bash scripts/configure-enterprise-compose.sh
bash output/enterprise-compose/check-config.sh
bash output/enterprise-compose/up.sh
bash output/enterprise-compose/check-live.sh
```

It generates `connector.env`, selects the Compose files, and writes a
Portainer-ready `portainer-compose.yml` plus matching `portainer.env`. Unknown
optional values keep robust defaults: without a CA path the stack uses system
CAs, without an OpenWebUI admin key OpenWebUI sync stays disabled, and startup
defaults to `CONNECTOR_STARTUP_CHECK=infra` so dashboard and logs remain
reachable while external service, TLS, auth, or parser issues are fixed.
For the first administrator acceptance after deployment, use the compact
[admin first-start checklist](docs/en/admin-first-start-checklist.md).

Copy the operator configuration and set the required values:

```bash
cp connector.env.example connector.env

docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet
```

Minimum values for the static Portainer default profile with Search and bundled
state:

| Variable | Purpose |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile URL reachable from the connector container |
| `SEAFILE_ADMIN_TOKEN` | Seafile admin API token for library discovery |
| `SEAFILE_SYNC_USER_TOKEN` | Seafile API token for file downloads |
| `RAGFLOW_BASE_URL` | RAGFlow API URL reachable from the connector container |
| `RAGFLOW_API_KEY` | API key of the target RAGFlow user |
| `AUTHZ_API_SHARED_SECRET` | Technical secret used by core and Search |
| `SEARCH_AUTHZ_SHARED_SECRET` | The same value as `AUTHZ_API_SHARED_SECRET` |
| `SEARCH_RAGFLOW_BASE_URL`, `SEARCH_RAGFLOW_API_KEY` | RAGFlow target as reached by the Search container |
| `POSTGRES_PASSWORD` | Password for the bundled stack database |

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

## Automations

`connector-controller` schedules discovery, commit-pinned delta runs, RAGFlow
template refresh, and optional OpenWebUI sync. Without a complete snapshot or
cursor it automatically schedules a safe full sync. `connector-reconciler`
compares the Seafile snapshot, connector state, and RAGFlow documents and
repairs detected drift through deduplicated jobs. All periodic runtime
automations default to `1800` seconds, or 30 minutes, and values below 60
seconds are rejected. The active intervals are logged when the processes start.

Manual checks and syncs remain independent of the schedule:

```bash
connector check-live
connector doctor --effective
connector library status --json
connector library sync --repo-id <repo-id> --mode auto
connector library reconcile --repo-id <repo-id>
connector openwebui-sync-once
```

For Compose and Portainer, tune the schedule with
`DISCOVERY_INTERVAL_SECONDS`, `DELTA_SYNC_INTERVAL_SECONDS`,
`RECONCILE_INTERVAL_SECONDS`, `RAGFLOW_TEMPLATE_REFRESH_SECONDS`, and
`OPENWEBUI_SYNC_INTERVAL_SECONDS`.

## Dashboard Administration

The HTTP dashboard embedded in the running `connector-controller` is both the
existing log and status view and an interactive administration surface. Its
**Administration** area lists every library visible to the configured Seafile
admin token and provides separate control levels:

- Administrators can globally start, deactivate, pause, resume, or stop
  connector work. Start enables automation, releases the queue, and triggers
  discovery immediately; deactivate only prevents new automation; stop turns
  automation off, pauses the queue, and requests cooperative cancellation of
  active jobs.
- Each Seafile library has a persistent `active`, `paused`, or `disabled`
  policy and can be selected for a delta, full, or reconciliation run.
- A concrete run can be paused, resumed, stopped, or retried after a terminal
  failure or stop.

These actions control the connector scheduler, queue, workers, and reconciler;
they never start or stop containers or Portainer services. The dashboard and
diagnostics therefore remain reachable while connector work is paused,
stopped, or disabled. Pause and stop are cooperative: an in-flight download,
upload, or RAGFlow request finishes before the next safe checkpoint. A paused
job returns to the queue there; stop or cancellation wins over pause. Completed
target-side effects are not rolled back and can be completed safely with
resume, retry, or reconciliation.

Library and run views expose the current phase plus file and parsing counters.
Parsing reports `tracked`, `done`, `pending`, `failed`, and a percentage
derived from those known counts; missing RAGFlow values are not guessed. Control
policies and runs are stored in PostgreSQL and survive browser and controller
restarts.

The standalone `connector dashboard` command intentionally starts a read-only
status view. It has no runtime controller, job queue, or signalling path and
therefore cannot expose administration actions. Production administration must
use the published `connector-controller` route.

Mutating actions require `CONNECTOR_DASHBOARD_CONTROL_ENABLED=true` in addition
to the dashboard switch. The setting is valid only with an enabled dashboard
and fully configured Basic authentication. Mutations require
`Content-Type: application/json` and `X-Connector-Admin-Action: 1`; global stop
and run stop/cancel additionally require `{"confirm":"STOP"}`. LAN access requires HTTPS through a
reverse proxy or an equivalently protected internal path. Connector controls
never modify Seafile libraries and never receive
Portainer or Docker credentials.

For an isolated first-ever start, set
`CONNECTOR_AUTOMATION_INITIAL_STATE=stopped` before `up -d`. It initializes the
global state once, before the first scheduler cycle; later restarts always
preserve the persisted operator state. Without the variable, the
backward-compatible initial state remains `running`.

## Portainer Start

1. Create a new stack in Portainer.
2. Paste `deploy/portainer/docker-compose.yml` into the web editor or use this repository as a Git stack.
3. Import the values from `connector.env.example` as environment variables.
4. Replace only the required values; set OpenWebUI values only when that integration is enabled.
5. If images are provided offline, align `CONNECTOR_IMAGE`, `POSTGRES_IMAGE`, `REDIS_IMAGE`, and the `*_PULL_POLICY` values with the imported local images.
6. Deploy the stack and inspect the logs of `connector-controller`, `connector-worker`, and `connector-reconciler`.

Use the enterprise wizard for a core-only or external-state Portainer bundle:
`ENTERPRISE_WITH_SEARCH=false` omits Search completely;
`ENTERPRISE_STATE_MODE=external` requires `DATABASE_URL` and `REDIS_URL` and
removes the local state containers from the started model.

For production-like deployments, pin `CONNECTOR_IMAGE` to a fixed release tag
such as `ghcr.io/adrianweidig/seafile-ragflow-connector:2.6.3` after that
release has been published. Treat `latest` as a convenience tag for smoke tests
and fresh test environments.
The first acceptance path after deployment is summarized in the
[admin first-start checklist](docs/en/admin-first-start-checklist.md).

## CLI

The package exposes the `connector` command:

| Command | Purpose |
| --- | --- |
| `connector init-db` | Create or migrate connector state tables |
| `connector doctor --effective` | Show redacted configuration truth and optional database/Redis diagnostics |
| `connector check-live` | Check database, Redis, Seafile, and RAGFlow without mutation |
| `connector sync-once` | Run one full discovery and sync pass |
| `connector library status`, `plan`, `sync`, `reconcile` | Inspect library state and control delta/full sync or reconciliation |
| `connector jobs list`, `show`, `cancel`, `retry` | Inspect, cancel, and retry persistent jobs |
| `connector cleanup list`, `retry` | Inspect failed target cleanups and queue persistent retries |
| `connector cleanup-orphans` | Plan or delete connector-owned orphan target artifacts |
| `connector openwebui-sync-once` | Run one OpenWebUI sync pass |
| `connector dashboard` | Start the standalone read-only status dashboard without administration controls |
| `connector controller`, `worker`, `reconciler` | Start runtime processes |

## Development

```bash
uv sync --locked --all-extras
python -m compileall src tests migrations scripts
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

On Windows with Docker in WSL, use the WSL wrapper. It keeps the `uv`
environment outside the Windows checkout and avoids conflicts with an existing
Windows `.venv`:

```bash
wsl -d Debian -- bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && bash scripts/verify_wsl.sh --with-compose --with-dashboard-browser-smoke'
```

## Documentation

- [German documentation entry](docs/de/index.md)
- [English documentation entry](docs/en/index.md)
- [Admin first-start checklist](docs/en/admin-first-start-checklist.md)
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Environment variables](docs/environment.md)
- [Manual Seafile-RAGFlow-OpenWebUI verification](docs/en/manual-workflow-verification.md)
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
