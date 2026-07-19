# Admin First-Start Checklist

🌐 Languages: [Deutsch](../admin-first-start-checklist.md) | **English**

This checklist covers the first checks after a new installation. It does not
replace the detailed operations documentation; it gives administrators a compact
acceptance path for Portainer, Docker Compose, and the first user-facing
release.

## Before Deployment

- Docker Compose Plugin or Portainer is available on the target host.
- Seafile and RAGFlow already run outside the connector stack.
- The URLs reachable from inside the connector container are known. In a shared
  Docker network these can be internal names such as `http://seafile` and
  `http://ragflow:9380`; over LAN or a reverse proxy they are the URLs reachable
  from that network.
- Seafile admin token, Seafile download token, RAGFlow API key, and, if
  OpenWebUI integration is enabled, an OpenWebUI admin key are ready.
- The network mode is chosen:
  `CONNECTOR_DOCKER_NETWORK_EXTERNAL=false` for a connector-owned network or
  `CONNECTOR_DOCKER_NETWORK_EXTERNAL=true` for an existing shared Docker
  network.
- Internal root or intermediate CAs are available as PEM files on the Docker
  host if Seafile, RAGFlow, or OpenWebUI use private certificate chains.
- Real secrets stay outside the Git worktree. `connector.env`, `stack.env`,
  Portainer exports, and TLS lab outputs are not committed.

## Prepare Configuration

For direct Docker Compose installs, the guided wizard is the fastest path:

```bash
bash scripts/configure-enterprise-compose.sh
bash output/enterprise-compose/check-config.sh
```

It creates a local `connector.env`, the selected Compose file combination,
start scripts, and `output/enterprise-compose/portainer-compose.yml` with
`output/enterprise-compose/portainer.env` for Portainer.

For a manual setup, start with:

```bash
cp connector.env.example connector.env
```

Set at least these values:

| Variable | Purpose |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile URL from the connector container |
| `SEAFILE_ADMIN_TOKEN` | Admin API token for library discovery |
| `SEAFILE_SYNC_USER_TOKEN` | API token for file downloads |
| `RAGFLOW_BASE_URL` | RAGFlow API URL from the connector container |
| `RAGFLOW_API_KEY` | API key of the RAGFlow target user |
| `POSTGRES_PASSWORD` or both `DATABASE_URL` and `REDIS_URL` | Bundled or external connector state |

Only add OpenWebUI, TLS, tuning, and dashboard values when they are needed for
the selected operating mode.

## Check Before First Start

For the generated Compose configuration:

```bash
bash output/enterprise-compose/check-config.sh
```

For the central Portainer/Compose file:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet
```

If no generated `check-live.sh` is used, run the live check explicitly in the
Compose stack's controller container:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  run --rm connector-controller connector check-live
```

The interactive administration surface requires
`CONNECTOR_DASHBOARD_ENABLED=true`,
`CONNECTOR_DASHBOARD_CONTROL_ENABLED=true`, and non-empty values for
`CONNECTOR_DASHBOARD_AUTH_USERNAME` and
`CONNECTOR_DASHBOARD_AUTH_PASSWORD`. Keep the control switch `false` for a
read-only dashboard. For local access,
`CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080` is the safer default; LAN
access should be published intentionally and protected with network or reverse
proxy controls plus HTTPS. Production requires a randomly generated password;
known example passwords are rejected.

## Prepare an Isolated First Start

Before the very first stack start, set this in the operator environment:

```env
CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_CONTROL_ENABLED=true
CONNECTOR_AUTOMATION_INITIAL_STATE=stopped
```

This value is applied only when the global control state is created for the
first time. `stopped` atomically initializes automation as disabled and the
queue as paused before the controller scheduler or a worker can begin work. It
never overwrites a persisted operator state. The backward-compatible `running`
default permits immediate automatic cycles and therefore cannot guarantee an
isolated first start. During upgrades, drain existing jobs before changing the
version; the initial value does not cancel old jobs.
The real, non-empty Basic Auth values described above must also be present
before startup; otherwise there is no safe UI activation path.

## Start

With generated scripts:

```bash
bash output/enterprise-compose/up.sh
```

Or manually:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  up -d
```

In Portainer, use `deploy/portainer/docker-compose.yml` or the generated
`portainer-compose.yml` as stack content. Values from `connector.env.example`
or `portainer.env` go into the stack environment section.

## Configure Immediately After Start

The controller dashboard must now show the global state as `stopped`. Run
**Check libraries**, disable or pause every non-test library, and leave exactly
one small test library active. Global **Resume** only releases the queue pause;
automation remains `deactivated`, so the selected manual run can start in
isolation. Choose global **Start** only when automatic scheduling is intended
for every remaining runnable library. If the first visible state is not
`stopped`, the initial value was set too late or a persisted state already
exists; stop in a controlled way and resolve existing jobs before assuming
isolation.

## Success Criteria After Start

First, the infrastructure should meet these criteria:

- With `bundled-state`, `connector-postgres` and `connector-redis` are running;
  with `external-state`, both are intentionally absent and the external URLs
  are reachable.
- `connector-controller`, `connector-worker`, and `connector-reconciler` are
  running; the standard profile also runs `connector-search`, while core-only
  intentionally omits it.
- Controller, worker, and reconciler logs do not show missing required
  variables or persistent authentication failures.
- `bash output/enterprise-compose/check-live.sh` or the direct
  `docker compose run --rm connector-controller connector check-live` exits
  successfully.
- The dashboard is reachable when enabled.
- The browser route terminates at the `connector-controller` dashboard, not a
  separate `connector dashboard` process. Only the controller variant exposes
  the interactive **Administration** area.
- `/api/health` reports dashboard, database, Redis, Seafile, and RAGFlow as
  `ok` or shows a concrete external error that can be fixed.
- RAGFlow contains one dataset for every Seafile library that was deliberately
  enabled afterward, created from the template, or the template is created when
  auto-create is enabled.
- After explicitly starting the test-library run, initial files are uploaded
  and parse status is visible in the dashboard or in RAGFlow.
- The library table shows the operator state plus parsing counters for
  `tracked`, `done`, `pending`, and `failed`; a started run keeps phase and
  progress across a browser refresh.
- If OpenWebUI integration is enabled, chat, tool, pipe, or custom model entries
  appear after a real sync or repair run.

## User Release

Before exposing the setup to end users, also check:

- The dashboard is reachable only by administrators and protected with Basic
  Auth or upstream access controls.
- Mutating requests accept only JSON with `X-Connector-Admin-Action: 1`; the UI
  adds the header automatically. Global stop and run stop/cancel require a
  visible `STOP` confirmation.
- The visible language fits the target users. German is the default; English
  and additional dashboard languages can be selected in the UI or through
  `CONNECTOR_LANGUAGE`.
- OpenWebUI shows clear custom model names and source links when integration is
  enabled.
- The Excel audit export downloads metadata only, not synchronized file
  contents.
- A small test dataset was synchronized successfully before large libraries are
  enabled.
- Delta, pause, resume, and stop/retry were checked on one small test library.
  Stop and pause control connector work, never Portainer containers.

## If It Does Not Turn Green

| Symptom | First check |
| --- | --- |
| `docker` or `docker compose` is missing | Docker installation, PATH, and on Windows/WSL the selected context |
| Compose config fails | Missing required values, typos, and invalid ports in `connector.env` |
| Seafile or RAGFlow is unreachable | Internal container URL versus host/browser URL |
| Certificate error | Set CA bundle through `CONNECTOR_CA_BUNDLE`, `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE`, or `OPENWEBUI_CA_BUNDLE` |
| Dashboard unreachable | `CONNECTOR_DASHBOARD_ENABLED`, port mapping, bind address, and port conflicts |
| Administration is missing or a mutation is rejected | Controller route, `CONNECTOR_DASHBOARD_CONTROL_ENABLED`, complete Basic Auth, HTTPS proxy, and JSON/admin header |
| Dashboard health is `degraded` | Open the detail row and fix DB, Redis, tokens, and target URLs first |
| No datasets appear | Seafile admin permissions, RAGFlow template, and `RAGFLOW_TEMPLATE_AUTO_CREATE` |
| OpenWebUI artifacts are missing | `OPENWEBUI_INTEGRATION_ENABLED`, `OPENWEBUI_SYNC_MODE`, and proxy reachability from the OpenWebUI container |

`*_VERIFY_SSL=false` is only a short-term diagnostic aid. For production,
repair the certificate chain with CA bundles instead.

## CLI Fallback

Start the isolated test-library delta run through **Start selection** and follow
the phase, file counters, and parsing counters to a terminal state. Exercise
pause/resume and stop/retry only on this disposable test run. Global stop leaves
the controller and dashboard running; container operations remain in Portainer
or Docker Compose.

When interactive control is intentionally disabled, use this CLI fallback:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  run --rm connector-controller connector sync-once
```

For a generated enterprise Compose setup, use the same Compose files as
`output/enterprise-compose/up.sh`. In Portainer, run the same command as a
one-off controller task or from a shell inside the controller container.

Then check the dashboard's persistent change/audit history, RAGFlow datasets,
OpenWebUI artifacts, and the audit export. Enable larger libraries and automated
schedules through the administration surface only after that run is stable.
