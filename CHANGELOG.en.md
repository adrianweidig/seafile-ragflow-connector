# Changelog

🌐 Languages: [Deutsch](CHANGELOG.md) | **English**

All notable changes to this repository should be documented here. The format is
based on a simple `Unreleased` section; historical releases are not invented
retroactively.

## Unreleased

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
