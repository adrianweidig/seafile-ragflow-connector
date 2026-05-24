# Mitwirken

Danke, dass du zum Seafile RAGFlow Connector beitragen möchtest. Dieses Projekt
ist auf vorsichtige Betriebsautomatisierung ausgelegt: Seafile bleibt Quelle der
Wahrheit, Zielsysteme werden daraus aufgebaut und produktive Daten werden nicht
ohne klare Absicht verändert.

## Geeignete Beiträge

- Fehlerberichte mit reproduzierbaren Schritten.
- Verbesserungen an Dokumentation, Deployment-Hinweisen und TLS-Runbooks.
- Tests für Sync-, Delete-, Repair-, OpenWebUI- und Dashboard-Verhalten.
- Kleine, fokussierte Fixes für Code, CI oder Packaging.
- Vorschläge für bessere Portainer-, Compose- oder Swarm-Nutzbarkeit.

## Lokale Umgebung

Voraussetzungen:

- Python `>=3.12`
- `uv`
- Optional Docker mit Compose Plugin für Compose-Prüfungen

Setup:

```bash
uv sync --locked --all-extras
```

Standardcheck ohne Docker-Nebenwirkungen:

```bash
python scripts/verify.py --skip-compose
```

Einzelchecks:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
python -m compileall src tests migrations
PYTHONPATH=src python -m unittest discover -s tests/unit
```

Wenn Docker Compose lokal sicher verfügbar ist:

```bash
python scripts/verify.py --with-compose
```

## Pull-Request-Prozess

1. Öffne zuerst ein Issue, wenn der gewünschte Change mehrere Module, Deployments oder öffentliche Schnittstellen betrifft.
2. Halte den Diff klein und zielgenau.
3. Ändere keine öffentlichen CLI-Flags, Env-Namen, Dateiformate oder Standardwerte ohne Begründung.
4. Ergänze Tests, wenn Verhalten geändert wird.
5. Aktualisiere README, `docs/`, `connector.env.example` oder Deployment-Beispiele, wenn sich Nutzung oder Betrieb ändern.
6. Führe `python scripts/verify.py --skip-compose` aus und dokumentiere abweichende Checks im PR.

## Code- und Dokumentationsstil

- Python-Code folgt der Ruff- und mypy-Konfiguration aus `pyproject.toml`.
- Deutsche Fließtexte verwenden echte UTF-8-Umlaute.
- Keine globalen Formatierungswellen ohne fachlichen Grund.
- Beispiele nutzen Platzhalter wie `change-me` oder `YOUR_API_KEY`, niemals echte Zugangsdaten.
- Portainer- und Compose-Dokumentation bleibt environment-driven und darf nicht von lokalen `env_file`-Pfaden abhängen.

## Security

Melde Sicherheitsprobleme nicht als öffentliches Issue. Folge stattdessen
[SECURITY.md](SECURITY.md). Secrets, Tokens, private Schlüssel und produktive
Zertifikate dürfen nicht in Commits, Issues, Logs oder Screenshots auftauchen.

## Verhalten

Bitte beachte den [Code of Conduct](CODE_OF_CONDUCT.md). Technische Kritik ist
willkommen, solange sie konkret, respektvoll und auf eine prüfbare Verbesserung
gerichtet ist.
