# Changelog

🌐 Languages: [Deutsch](CHANGELOG.md) | **English**

All notable changes to this repository should be documented here. The format is
based on a simple `Unreleased` section; historical releases are not invented
retroactively.

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
