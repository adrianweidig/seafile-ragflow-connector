# Tests

Dieser Ordner enthält die automatisierten Prüfungen.

- `unit/`: schnelle Unit-Tests mit Fakes, SQLite und lokalen Fixtures.
- `integration/`: Platz für Tests gegen echte oder containerisierte
  Abhängigkeiten sowie lokale Fake-basierte End-to-End-Prüfungen.
- `fixtures/`: kleine Beispielantworten und Testdaten.
- `support/`: geteilte Testhilfen.

Die Standardprüfung für Pull Requests ist:

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
```

Für schnelle lokale Windows-Prüfungen funktioniert auch:

```powershell
$env:PYTHONPATH='src'; python -m unittest discover -s tests/unit
```
