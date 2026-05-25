# Contributing

🌐 Languages: [Deutsch](CONTRIBUTING.md) | **English**

Thank you for contributing to the Seafile RAGFlow Connector. This project is
designed for cautious operations automation: Seafile remains the source of
truth, target systems are rebuilt from it, and productive data is not changed
without clear operator intent.

## Suitable Contributions

- Bug reports with reproducible steps.
- Improvements to documentation, deployment guidance, and TLS runbooks.
- Tests for sync, delete, repair, OpenWebUI, dashboard, and i18n behavior.
- Small focused fixes for code, CI, or packaging.
- Suggestions that improve Portainer, Compose, or Swarm usability.

## Local Environment

Requirements:

- Python `>=3.12`
- `uv`
- Optional Docker with Compose plugin for Compose checks

Setup:

```bash
uv sync --locked --all-extras
```

Standard check without Docker side effects:

```bash
python scripts/verify.py --skip-compose
```

Individual checks:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
python -m compileall src tests migrations
PYTHONPATH=src python -m unittest discover -s tests/unit
```

When Docker Compose is safely available locally:

```bash
python scripts/verify.py --with-compose
```

## Pull Request Process

1. Open an issue first when a change affects multiple modules, deployments, or public interfaces.
2. Keep the diff small and focused.
3. Do not change public CLI flags, environment names, file formats, or defaults without rationale.
4. Add tests when behavior changes.
5. Update README, `docs/`, `connector.env.example`, or deployment examples when usage or operations change.
6. Run `python scripts/verify.py --skip-compose` and document any skipped or changed checks in the PR.

## Code and Documentation Style

- Python code follows Ruff and mypy configuration from `pyproject.toml`.
- German prose uses real UTF-8 umlauts.
- Do not perform global formatting waves without a functional reason.
- Examples use placeholders such as `change-me` or `YOUR_API_KEY`, never real credentials.
- Portainer and Compose documentation remains environment-driven and must not depend on local `env_file` paths.
- New human-facing strings should use the i18n resources in `src/seafile_ragflow_connector/locales/`.

## Security

Do not report security issues as public issues. Follow [SECURITY.en.md](SECURITY.en.md).
Secrets, tokens, private keys, and productive certificates must not appear in
commits, issues, logs, or screenshots.

## Conduct

Please follow the [Code of Conduct](CODE_OF_CONDUCT.en.md). Technical critique
is welcome when it is concrete, respectful, and aimed at a verifiable
improvement.
