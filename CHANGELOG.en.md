# Changelog

🌐 Languages: [Deutsch](CHANGELOG.md) | **English**

All notable changes to this repository should be documented here. The format is
based on a simple `Unreleased` section; historical releases are not invented
retroactively.

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
