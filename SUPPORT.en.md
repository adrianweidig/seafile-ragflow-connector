# Support

🌐 Languages: [Deutsch](SUPPORT.md) | **English**

This repository provides community support through GitHub Issues and Pull
Requests. There is no published commercial support channel and no SLA.

## Suitable Issues

- Reproducible bugs in connector code.
- Contradictions or gaps in README, `docs/`, or deployment examples.
- Problems with local Compose or Portainer configuration when logs and relevant
  environment names are provided without secrets.
- Suggestions for tests, CI, developer experience, or internationalization.

## Before Opening an Issue

1. Check [README.en.md](README.en.md), [docs/en/index.md](docs/en/index.md), and [docs/troubleshooting-ssl.md](docs/troubleshooting-ssl.md).
2. Run `python scripts/verify.py --skip-compose` when possible.
3. Remove secrets from logs, screenshots, and environment excerpts.
4. State whether Docker Compose, Portainer, Swarm, or a local TLS lab is affected.

## Not Suitable for Public Issues

- Productive credentials, tokens, private keys, or complete environment files.
- Vulnerabilities with exploit details. Use [SECURITY.en.md](SECURITY.en.md).
- General support for Seafile, RAGFlow, or OpenWebUI outside the connector integration.

## Useful Information

- Connector version or commit hash.
- Operating system and Docker/Compose version when deployment is affected.
- Relevant environment names with values redacted or replaced by placeholders.
- Excerpt from controller, worker, or reconciler logs without secrets.
- Expected and actual behavior.
