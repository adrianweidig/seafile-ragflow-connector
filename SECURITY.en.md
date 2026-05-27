# Security Policy

🌐 Languages: [Deutsch](SECURITY.md) | **English**

## Supported Versions

The repository currently declares package version `0.1.3` in `pyproject.toml`
and has no documented release branches. Security checks therefore refer to the
current default branch until maintainers publish a different release process.

## Reporting Security Issues

Do not publish sensitive vulnerability details as a public issue. Use GitHub
Private Vulnerability Reporting or GitHub Security Advisories when they are
enabled for this repository.

If no private channel is available, open a public issue without exploit details
and ask for a private reporting path. Do not attach tokens, passwords, private
keys, productive certificates, database dumps, or complete production logs.

## A Useful Report Contains

- Affected component, for example connector proxy, OpenWebUI sync, TLS configuration, or deployment artifact.
- Reproducible steps in an isolated test environment.
- Expected and actual behavior.
- Affected version or commit hash.
- Risk assessment without publishing sensitive details.

## Expected Handling

Maintainers review the report, reproduce the behavior where possible, and
decide whether to fix code, documentation, or configuration guidance. There is
no security guarantee and no fixed response time while the repository does not
publish a separate maintainer SLA.

## Project Boundaries

The connector does not replace Seafile, RAGFlow, or OpenWebUI. Security issues
in those external systems must also be reported to their respective projects or
operators. `*_VERIFY_SSL=false` is only intended for diagnosis and development
and must not be documented as a production recommendation.
