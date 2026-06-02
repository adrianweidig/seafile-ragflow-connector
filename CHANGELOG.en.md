# Changelog

🌐 Languages: [Deutsch](CHANGELOG.md) | **English**

All notable changes to this repository should be documented here. The format is
based on a simple `Unreleased` section; historical releases are not invented
retroactively.

## Unreleased

## 0.1.13 - 2026-06-02

### Changed

- Audited OpenWebUI evidence is rendered as narrow source blocks instead of a
  wide Markdown table so the evidence register remains readable in OpenWebUI
  without horizontal clipping.
- The OpenWebUI artifact version was bumped to 22 so existing pipes reliably
  receive the corrected audit rendering.

## 0.1.12 - 2026-06-02

### Added

- OpenWebUI pipe audit mode is now the default: answers start with the user
  answer and then show a German evidence register with audit status, claim
  coverage, source roles, match type, audit score, and safe run metadata.
- Source normalization now carries `source_role`, `match_type`, `audit_score`,
  `score_components`, `used_in_answer`, claim IDs, and the original RAGFlow
  provider citation.

### Changed

- RAGFlow references are ranked by audit relevance and then re-labelled
  consistently as `S1`, `S2`, and so on. Exact marker, ID, hash, ticket, and
  filename questions prioritize exact matches over semantically similar hits.
- OpenWebUI pipe defaults changed from native citation events to visible audit
  mode so OpenWebUI does not render a second, differently numbered source list.

### Fixed

- Answer markers such as `[ID:3]` are resolved against the original RAGFlow
  reference ID after audit sorting and rendered consistently as `[S1]`/`[S2]`.

## 0.1.11 - 2026-06-02

### Added

- Dashboard action to clean dead sync jobs directly from the `Sync jobs` health
  card. Jobs are marked as `cancelled` so history is preserved while the active
  dead-job counter returns to 0.

### Changed

- Dead sync jobs are now shown as dashboard maintenance work instead of a hard
  connector failure when the other system checks are healthy.

## 0.1.10 - 2026-06-01

### Changed

- OpenWebUI pipes now strictly separate generated chat answers from
  retrieval-only results and only mark runs as generated when a trusted answer
  path or the synthesis fallback was used.
- Native OpenWebUI citations are the default source channel; Markdown evidence
  tables are explicit audit or debug modes.
- RAGFlow/OpenAI-compatible answer and reference paths, source deduplication,
  score sorting, and redacted proxy diagnostics were tightened.

### Fixed

- Source or file titles can no longer be treated as generated answers.

## 0.1.9 - 2026-06-01

### Added

- Dashboard tab `Workflow` that lists libraries visible to the Seafile API key
  and can start selected libraries for RAGFlow dataset, document, chat, and
  OpenWebUI tool/pipe sync.
- Fake-based integration test and German/English runbook for the manually
  verifiable Seafile-RAGFlow-OpenWebUI workflow.

### Changed

- OpenWebUI sync can be scoped to selected repo IDs so dashboard-triggered
  verification runs do not touch unselected libraries.
- Dashboard, operations, and configuration docs now describe the controller
  workflow and distinguish it from the standalone status dashboard.

## 0.1.8 - 2026-06-01

### Changed

- Updated runtime dependencies: `python-multipart` to `0.0.30` and `typer` to
  `0.26.4`.
- Updated development and test dependencies: `pytest-asyncio` to `1.4.0` and
  `ruff` to `0.15.15`.

### Fixed

- Dependabot lockfile updates were merged on top of the current `master` and
  verified with the repository verify runner.

## 0.1.7 - 2026-06-01

### Added

- WSL verify wrapper for Windows hosts that runs `uv` in a WSL-owned
  environment instead of touching an existing Windows `.venv`.
- Reproducible Docker mock smoke check in the verify runner. It builds a local
  connector test image from the current checkout, cleans test volumes before
  and after the run, and checks both `check-live` and `/health/tls`.

### Changed

- Periodic discovery, delta sync, reconcile, RAGFlow template refresh, and
  OpenWebUI sync defaults are consolidated to 30 minutes across configuration,
  Compose, Portainer, Swarm examples, and documentation.
- Dashboard and export labels are localized in more operator-facing views,
  including first-paint placeholders, systems tables, audit export, OpenWebUI
  labels, and log labels.
- The local HTTPS mock smoke uses the same Basic Auth path for `/health/tls` as
  the operator examples.

### Fixed

- Parallel controller, worker, and reconciler starts now serialize PostgreSQL
  schema initialization with an advisory lock.
- `language_from_settings()` keeps the documented German default when no
  connector language is explicitly configured, independent of host locale.
- README CLI examples now use the existing Typer commands `dashboard`,
  `controller`, `worker`, and `reconciler`.
- Short-lived runtime check paths close database and Redis resources more
  deterministically.

## 0.1.6 - 2026-05-28

### Fixed

- The OpenWebUI chat proxy now falls back to retrieval sources when RAGFlow chat
  completion times out instead of hanging until the HTTP timeout without a
  response.

## 0.1.5 - 2026-05-28

### Added

- Public Seafile base URL and flexible file-link template for original-file
  links in OpenWebUI sources.

### Changed

- OpenWebUI source links now distinguish internal Docker service URLs from
  externally reachable browser and preview URLs more clearly.
- The enterprise Compose wizard now asks for internal service endpoints and
  external browser endpoints separately, making shared-network deployments
  easier to configure.

## 0.1.4 - 2026-05-28

### Added

- Portainer-ready enterprise Compose wizard that asks for existing Seafile,
  RAGFlow, and optional OpenWebUI targets and generates a pasteable
  `portainer-compose.yml` plus matching `portainer.env`.
- Enterprise CA Compose overlay for HTTPS targets with an internal root CA.

### Changed

- The connector image now runs `update-ca-certificates` on every container
  start, copies a configured `CONNECTOR_CA_BUNDLE` into the system trust store
  first, and then starts the connector as an unprivileged user again.
- Enterprise Compose now defaults to `CONNECTOR_STARTUP_CHECK=infra` so the
  dashboard and logs stay reachable even while external TLS, auth, or parser
  issues are being fixed; strict live validation remains available through
  `check-live.sh`.
- The enterprise wizard treats unknown root CA paths and missing OpenWebUI admin
  keys as values that can be filled in later instead of blocking the base stack
  start.

## 0.1.3 - 2026-05-27

### Added

- Auditable OpenWebUI source mode `audit` with `[S1]` source markers, a
  Markdown evidence table, evidence quality, and transparent locator quality.
- Normalized `locator_quality` values for line, page, section, position, chunk,
  document, snippet-only fallback, and unknown locations.
- Tests for audit Markdown, citation event payloads, missing locations, debug
  metadata, connector preview links, and conflicting or missing sources.

### Changed

- OpenWebUI pipes now appear in the model picker as `Seafile · <Dataset>` and
  describe themselves as verifiable knowledge models for synchronized Seafile
  libraries.
- OpenWebUI answers append a visible evidence table by default, while numeric
  scores and internal IDs stay hidden during normal operation.
- Connector preview links are the preferred jump target for citations; internal
  proxy backend URLs continue to be filtered from OpenWebUI output.

## 0.1.2 - 2026-05-27

### Changed

- TLS/CA-bundle handling now passes `ssl.SSLContext` objects to HTTPX so
  private CAs work consistently without relying on the deprecated `verify=<path>`
  path.
- OpenWebUI tool and pipe artifacts were bumped to `artifact_version` 17 and now
  use the same SSLContext approach for the connector proxy.
- Release and operator guidance now explain fixed SemVer image tags such as
  `0.1.2` more clearly and position `latest` as a convenience tag.

### Fixed

- Invalid CA bundles are reported as controlled TLS configuration errors without
  exposing CA contents or secret values.
- OpenWebUI source snippets are cleaned through an HTML parser so malformed HTML
  is not processed through unbounded regex fallbacks.
- Transport and dashboard diagnostics show custom CA usage as `custom_ca`
  without exposing local CA paths or internal TLS objects.

## 0.1.1 - 2026-05-27

### Added

- Resource-based internationalization with German as default, English as
  alternative language, `CONNECTOR_LANGUAGE`, dashboard language selection,
  OpenWebUI artifact language metadata, and UTF-8/Unicode tests.
- Public repository documentation with community files, issue/PR templates,
  security policy, support guidance, and maintainer checklist.
- RAG Evidence Viewer for OpenWebUI source previews with a clear separation
  between connector preview and original Seafile link.
- Tests for preview tokens, original-link safety, XSS escaping, score display,
  and fallback views.

### Changed

- Repository structure extended with `README.en.md`, `docs/de/`, `docs/en/`,
  and English community files; GitHub language switching is handled through
  visible links.
- README oriented more strongly toward public use, quick entry, and
  documentation navigation.
- OpenWebUI source previews now prioritize the used RAG context, locations,
  dataset metadata, and technical details more clearly.
