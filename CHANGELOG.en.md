# Changelog

🌐 Languages: [Deutsch](CHANGELOG.md) | **English**

All notable changes to this repository should be documented here. The format is
based on a simple `Unreleased` section; historical releases are not invented
retroactively.

## Unreleased

## 2.6.2 - 2026-07-20

### Added

- Automatically generated library datasets can be provisioned as RAGFlow team
  datasets while the internal template remains private.
- An optional interactive RAGFlow identity owns the managed chats and native
  Search app. Its dataset bindings are refreshed from all active connector
  libraries and the same identity is used by Connector Search and OpenWebUI.
- The administration dashboard exposes the effective dataset permission mode,
  interactive owner, and chat model without disclosing the associated API key.

### Fixed

- The enterprise Compose wizard now preserves and validates the dataset
  permission and every interactive RAGFlow identity setting, and writes secret
  environment files with owner-only permissions.
- Existing exactly matched connector datasets are idempotently migrated to the
  configured team permission when switching the target identity, without
  overwriting parser or template settings.
- The interactive RAGFlow identity is verified against the current API-key
  owner before every mutation. Unverifiable Search creations are rolled back
  by their exact ID instead of creating more Search apps on later cycles.
- Legacy-chat and orphan cleanup now requires deterministic connector
  provenance. Owner migrations that have not passed a completion smoke test
  and multi-step dataset replacements remain visibly pending without deleting
  manually created administrator chats.
- The expected RAGFlow duplicate-name collision during the preparatory
  blue/green document rename is accepted only for the exact known response and
  only before parsing; generic final-rename failures enter a controlled retry.

## 2.6.1 - 2026-07-19

### Fixed

- Updated Seafile files continue parsing in RAGFlow under a unique transitional
  name while the active previous version still occupies the final document
  name. Once parsing succeeds, the previous version is removed through the
  persistent cleanup outbox and the readable name is restored.
- During several rapid changes to the same file, only the newest document
  version can become active; even a version that has not been uploaded yet
  prevents an outdated promotion.
- Document promotion and the cleanup request for the previous version are
  stored atomically so a pause, cancellation, or process failure cannot leave
  an orphaned RAGFlow document without a cleanup request.

## 2.6.0 - 2026-07-19

### Added

- The dashboard embedded in `connector-controller` now also serves as an
  interactive administration surface: connector work and individual Seafile
  libraries can be persistently enabled, disabled, paused, and resumed, while
  delta, full, and reconciliation runs can be started, paused, resumed,
  stopped, and retried selectively.
- Library and run views expose the current processing phase plus file and
  parsing progress, including pending, successful, and failed documents.
- Administration actions are persistently audited with actor, target,
  before/after state, and result without storing passwords or other secrets.
- Knowledge search can use the existing OpenWebUI LDAP/AD pipeline for login
  and group synchronization, then manages its own short-lived signed browser
  session with explicit logout.
- Commit-pinned delta sync with confirmed snapshots/cursors, repository
  leases/fencing tokens, document versions, cleanup outbox, and a dedicated
  reconciliation plan.
- Persistent dashboard verification runs with progress, cancellation, and
  retry, plus new `library`, `jobs`, and `doctor` CLI commands.
- Visible failed target cleanups in the dashboard plus `cleanup list` and
  `cleanup retry` for persistent operational recovery jobs.
- Explicit Compose, Portainer, and Swarm profiles for bundled or external state
  and for core-only or Search deployments.

### Changed

- Mutating dashboard actions are separated from read-only status access and
  are accepted only when control is enabled, dashboard authentication is
  configured, and JSON carries `X-Connector-Admin-Action: 1`; global stop and
  run stop/cancel also require `{"confirm":"STOP"}`. The standalone
  `connector dashboard` command remains an intentionally read-only status
  view; administration is available only in the running controller and never
  controls containers or Portainer services.
- `CONNECTOR_AUTOMATION_INITIAL_STATE=stopped` provides a scheduler-free first
  start. The backward-compatible default remains `running`, and an existing
  persisted operator state is never overwritten.
- Dashboard and knowledge search now use responsive, state-preserving
  navigation, denser default views, and collapsed technical details.
- Search and OpenWebUI sources expose consistent evidence, coverage, and
  locations; active searches can be cancelled or retried.
- Opaque result snapshots bound to user and ACL state keep Search pagination
  stable across follow-up pages without querying RAGFlow again from page one.
- Dashboard logs are persisted asynchronously in batches so high log volume no
  longer blocks application paths on individual database commits; transient
  write failures are retried within bounds and permanent loss increments the
  drop metric.

### Fixed

- Deployment profiles now share the same authorization secret between core and
  Search and expose Search consistently in supported standard profiles.
- Library deletion requires repeated observations and explicit confirmation for
  suspicious mass changes before target artifacts are removed.
- Waiting CLI syncs now return a failing exit code on timeout, cancellation, or
  terminal job failure, and invalid configuration is reported concisely instead
  of exposing an internal Python traceback.

## 2.5.6 - 2026-07-04

### Removed

- Removed repo-internal Codex readiness and goal-state notes so the published
  project root only contains user-relevant project files.

## 2.5.5 - 2026-06-30

### Fixed

- The PDF page preview in the knowledge search document viewer now uses a
  scrollable fit-to-width container, making PDF pages readable instead of
  showing them as tiny full-page thumbnails.

## 2.5.4 - 2026-06-30

### Fixed

- PDF sources in knowledge search are now rendered server-side as page images
  so browsers without an enabled native PDF viewer no longer download the source
  automatically.
- The new PDF page-image endpoint uses the same preview token and server-side
  authorization check as the document proxy.
- The PDF passage remains visible and copyable; original and preview links stay
  available as explicit user actions.

## 2.5.3 - 2026-06-30

### Fixed

- PDFs and images are now loaded into the knowledge search document viewer via
  blob URLs so source selection no longer performs direct browser navigation to
  the PDF download endpoint.
- The search document proxy now enforces Content-Disposition deterministically:
  PDF, text, and images are served inline, while Office files remain explicit
  downloads.
- The viewer toolbar only shows the direct file download action for download
  file types; inline-capable sources stay in the center viewer.

## 2.5.2 - 2026-06-30

### Fixed

- The search service now also receives the connector state database
  configuration so path repair for PDF, Office, and image sources is active in
  production.
- The document viewer can therefore map RAGFlow display names back to real
  Seafile paths in subfolders from the separate `connector-search` container.

## 2.5.1 - 2026-06-30

### Fixed

- Knowledge search now repairs RAGFlow-returned source paths against the
  connector state database when RAGFlow only returns a library-name display path.
- Document viewer links for PDF, Office, and image files therefore continue to
  point at the real Seafile path for files in subfolders.

## 2.5.0 - 2026-06-28

### Changed

- Knowledge search now uses a calmer workspace hierarchy after visual review,
  with a subtler hit passage, prioritized viewer action, and denser source and
  library panels.
- Text and Markdown viewers now highlight only one short prioritized in-document
  hit anchor; the full passage remains visible as a copyable excerpt with a left
  accent rail.
- The dashboard now uses denser operational UI tokens with flatter panels,
  compact metrics, calmer status surfaces, and more stable tablet/mobile
  breakpoints.

## 2.4.11 - 2026-06-27

### Fixed

- Knowledge search now highlights only one short, relevant focus hit in the
  text/Markdown viewer instead of painting the entire RAG chunk yellow.
- The hit passage below the viewer remains a neutral, copyable excerpt and no
  longer repeats the same large yellow highlight block.
- Viewer helper text now states more clearly that the full passage remains
  copyable while only the most relevant in-document hit is highlighted.

## 2.4.10 - 2026-06-26

### Fixed

- Knowledge search answer mode continues to return a synthesized cited answer
  and now uses the exact passage text for prompting, copying, and text
  highlighting instead of the shortened source-card snippet.
- Text and Markdown viewers now mark the relevant passage directly in the
  document DOM with `<mark>` and scroll to the hit when sources change.
- Citation markers such as `[S2]` inside the answer are clickable and
  synchronize the viewer, active source, and source rails.

## 2.4.9 - 2026-06-26

### Fixed

- Knowledge search now stages libraries, workspace, and sources more
  responsively, keeping sources available as a compact in-workspace strip on
  medium viewports.
- The document viewer, hit passage, answer area, and composer are more compact
  and keep the answer directly below the document.
- Text and Markdown sources now render as a safe dark text preview instead of a
  dominant white browser surface.

## 2.4.8 - 2026-06-26

### Added

- Knowledge search can optionally synthesize answers through an
  OpenAI-compatible `/chat/completions` endpoint configured with
  `SEARCH_ANSWER_LLM_*`.

### Fixed

- Answer generation now continues to fall back cleanly to RAGFlow or the local
  source-grounded summary when the OpenAI-compatible model is not configured or
  fails.

## 2.4.7 - 2026-06-26

### Fixed

- Knowledge search now reliably hides the empty document-viewer state once a
  source is loaded in the native viewer.
- Answer mode now keeps source result cards compact below the answer and uses
  toast feedback for passage copying so the answer does not jump down.
- The source-grounded answer fallback now produces a readable summary with
  source markers instead of technical raw excerpts.

## 2.4.6 - 2026-06-25

### Added

- Search service now generates a RAGFlow-backed answer from retrieved sources
  with source markers and falls back to a short source-grounded answer when
  RAGFlow answer generation is unavailable.
- Knowledge search now includes a centered document viewer with a safe
  connector proxy, source selection, answer area, and bottom chat composer.
- The local HTTPS edge now also supports `https://search.top.secret/search`
  for Portainer/Compose testing.

## 2.4.5 - 2026-06-18

### Fixed

- Synchronized release metadata, README examples, and operator guidance with
  the current GHCR release tag.

## 2.4.4 - 2026-06-18

### Fixed

- The controller remains stable at startup when RAGFlow or OpenWebUI template
  requests are temporarily unavailable.
- RAGFlow `search_template` resolution now tolerates older RAGFlow versions
  without Search App endpoints and falls back to chat or built-in defaults in a
  controlled way.
- The OpenWebUI pipe now shows only the concise user-facing deny message
  `Kein Zugriff auf diese Bibliothek.`.

## 2.4.3 - 2026-06-18

### Fixed

- The Search page header now uses a clear search/source icon instead of a
  single-letter watermark.
- Search-field and library-filter placeholders now use user-facing wording.

## 2.4.2 - 2026-06-18

### Added

- Added a shared evidence/source model for the Search service and OpenWebUI
  pipe so sources, locators, preview links, and original links render
  consistently.
- The Search service now displays sources with a source panel, hover/focus
  preview, signed evidence viewer, locator chips, and best-effort original or
  text-fragment links.

### Changed

- Answer mode and the OpenWebUI pipe now render compact clickable sources
  without raw RAGFlow projection markers such as `BEGIN SOURCE CONTENT`.

## 2.4.1 - 2026-06-17

### Fixed

- Search answer sources are rendered as clickable source cards with a direct
  `Open source` link instead of a static result list.

## 2.4 - 2026-06-17

### Fixed

- ACL snapshots now resolve technical Seafile user IDs from direct user shares
  through the admin user list to `contact_email`. This covers Seafile LDAP/SSO
  installations where `/api/v2.1/admin/shares/` only returns internal
  `@auth.local` IDs.

## 2.3 - 2026-06-17

### Fixed

- ACL snapshots now prefer `contact_email` and `owner_contact_email` for
  Seafile LDAP/SSO identities before technical internal Seafile IDs such as
  `@auth.local`. Search-Service and OpenWebUI pipes therefore make the same
  allow/deny decision for real user email addresses.

## 2.2 - 2026-06-17

### Fixed

- Search results now show user-facing document names and source paths for real
  RAGFlow retrieval responses even when RAGFlow only exposes them through
  `document_keyword` or `doc_aggs`.
- The central Authz API returns all profile fields required by the search UI in
  `filter-profiles` responses.
- OpenWebUI pipes no longer treat technical RAGFlow backend errors as generated
  user answers and show only the safe `No access to this library.` denial for
  Connector 403 responses.

## 2.1 - 2026-06-16

### Added

- Added ACL snapshots and a central Authz API for user-scoped RAGFlow queries.
  The connector core mirrors Seafile library permissions, expands group shares,
  and makes fail-closed decisions for the Search service and OpenWebUI pipe.
- Added a separate `connector search-server` with an end-user knowledge search
  UI, trusted-header auth, SearchProfiles, retrieval search, source/preview
  actions, and Portainer/Compose/Swarm artifacts.

### Changed

- OpenWebUI proxy requests now check the same central ACL decision as the
  Search service before RAGFlow is queried. The OpenWebUI artifact version was
  bumped to 25 for this change.
- Updated development/runtime dependency pins from Dependabot:
  `cryptography` 49.0.0, `ruff` 0.15.17, and `pytest` 9.1.0.

## 2.0 - 2026-06-04

### Added

- Added the full Seafile -> RAGFlow -> OpenWebUI demo video to the repository
  and linked it from the README.
- The Dashboard OpenWebUI tab can delete connector-owned pipes, RAGFlow chats,
  and RAGFlow datasets without deleting the related Seafile library.

### Changed

- README, changelog, release process, and version references were prepared for
  version `2.0`.
- Documentation was checked for conflicting demo, release, and encoding notes;
  safe corrections were applied directly.
- Docker context hygiene now excludes the repository demo videos from local
  container images.
- Docker image publishing also supports `vX.Y` tags such as `v2.0` as image tag
  `2.0`.
- Normal OpenWebUI/RAGFlow chat answers now curate visible sources to cited
  documents so irrelevant hits no longer appear as answer evidence. The
  OpenWebUI pipe artifact version was bumped to 24 for this change.

### Fixed

- RAGFlow template datasets containing `graphrag.batch_chunk_token_size` from
  RAGFlow 0.25.4 can again be used as templates for newly created connector
  datasets.
- Dashboard deletion of OpenWebUI pipes now also recognizes OpenWebUI's compact
  persisted function metadata shape as connector-owned.

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
