# Codex-/Agenten-Anweisungen

## Projektüberblick

Dieses Repository enthält einen offline-fähigen Python-Connector zwischen
einem bestehenden Seafile-Server, einem bestehenden RAGFlow-Server und optional
OpenWebUI. Seafile bleibt die Quelle der Wahrheit. Der Connector verwaltet
RAGFlow-Datasets, Dateiimport, Delete-/Repair-Logik, OpenWebUI-Tools/Pipes,
Dashboard-Status, Jobs, Metriken und Deployment-Artefakte für Docker Compose,
Portainer und Swarm.

## Wichtige Verzeichnisse

- `src/seafile_ragflow_connector/`: Anwendungscode für CLI, Konfiguration,
  Clients, Sync, Dashboard, Jobs, Persistenz und OpenWebUI.
- `tests/`: Unit-, Integrations- und Fixture-Tests.
- `migrations/`: Alembic-Migrationen für den Connector-State.
- `deploy/docker/`: Dockerfile und Entrypoint.
- `deploy/portainer/`: Portainer-fähiger Compose-Stack.
- `deploy/compose/`: direkte Compose-Varianten für Host/LAN, Shared Network,
  OpenWebUI und TLS-Beispiele.
- `deploy/swarm/`: Docker-Swarm-Stackfile und Env-Vorlage.
- `deploy/tls-lab/`: lokales TLS-Lab; generierte Zertifikate bleiben
  ungetrackt.
- `docs/`: Architektur-, Konfigurations-, Betriebs- und TLS-Dokumentation.

## Setup und Entwicklung

```bash
uv sync --locked --all-extras
```

Schnelle lokale Syntaxprüfung:

```bash
python -m compileall src tests migrations
```

Standardchecks:

```bash
python scripts/verify.py --skip-compose
```

Einzelchecks:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

Falls ohne `uv` getestet wird, muss `PYTHONPATH=src` gesetzt sein und die
Projektabhängigkeiten müssen installiert sein. Für Diagnosefälle kann der
Verify-Runner einzelne Schritte sichtbar ausgeben; Docker Compose wird nur
erzwungen, wenn `--with-compose` gesetzt ist.

## Betrieb und Deployment

- Zentrale Betreiberkonfiguration ist `connector.env.example`, kopiert nach
  `connector.env`. Echte Env-Dateien, Tokens, Passwörter und API-Keys werden
  nicht eingecheckt.
- Portainer und Docker Compose bekommen dieselben Werte über Environment-
  Variablen; die Compose-Dateien dürfen nicht von lokalen `env_file`-Pfaden
  abhängig werden.
- Seafile, RAGFlow und OpenWebUI sind externe Systeme und werden nicht durch
  diesen Connector ersetzt.
- Bestehende Docker-Volumes und produktive Daten dürfen bei Cleanup-Arbeiten
  nicht gelöscht werden.

## Coding-Konventionen

- Python 3.12+; Code unter `src/`, Tests unter `tests/`.
- Ruff-Konfiguration aus `pyproject.toml` respektieren; keine projektweite
  Formatierungswelle ohne Auftrag.
- Typen mit `mypy --strict` sauber halten.
- Öffentliche API-, Env- und CLI-Namen nicht ohne ausdrücklichen Auftrag
  ändern.
- Sync-, Delete- und Repair-Logik konservativ behandeln: Seafile ist die
  Quelle der Wahrheit, Zielartefakte werden daraus aufgebaut.
- Für HTTP-Clients zentrale Helfer und TLS-Konfiguration wiederverwenden.

## Dokumentationskonventionen

- `README.md` ist die zentrale Einstiegsdatei.
- Ausführliche Betriebs-, TLS- und Architekturdetails bleiben in `docs/` und
  werden aus der README verlinkt.
- Deutsche Fließtexte verwenden echte UTF-8-Umlaute. Keine blinden globalen
  Ersetzungen in Code, Pfaden, Env-Variablen, IDs oder technischen Strings.
- Beispielwerte bleiben offensichtliche Platzhalter wie `change-me` oder
  `YOUR_API_KEY`.

## Git- und Datei-Hygiene

- Vor Änderungen immer `git status --short --branch` prüfen.
- Fremde oder bereits vorhandene Änderungen nicht zurücksetzen oder
  überschreiben.
- Keine destruktiven Git-Befehle ohne ausdrückliche Nutzerfreigabe:
  `reset`, `restore`, `checkout --`, `clean`, Rebase, Amend oder Force-Push.
- Generierte lokale Artefakte bleiben ungetrackt, insbesondere Caches,
  `connector.env`, `stack.env`, TLS-Lab-Ausgaben und `output/`.
- Dateien nur löschen, wenn Referenzen, CI, Deployment und Dokumentation sicher
  geprüft sind. Unsichere Kandidaten im Abschlussbericht nennen.

## Sicherheit

- Keine Secrets, Tokens, Passwörter, API-Keys oder produktiven Zertifikate in
  Dateien schreiben oder ausgeben.
- TLS-Testzertifikate werden zur Laufzeit temporär erzeugt. Generierte
  Private Keys dürfen nicht eingecheckt werden.
- `*_VERIFY_SSL=false` ist nur für Diagnose/Entwicklung gedacht und darf nicht
  als produktive Empfehlung dokumentiert werden.
- Produktive Dienste nicht ohne konkreten Auftrag mutieren.

## Definition of Done

- Relevante Dokumentation und Agentenhinweise sind konsistent.
- `README.md`, `docs/README.md`, `connector.env.example` und Deployment-
  Beispiele widersprechen sich nicht.
- Lizenzangaben in `LICENSE`, `README.md` und `pyproject.toml` sind konsistent.
- `python scripts/verify.py --skip-compose` oder begründete Alternativen
  wurden ausgeführt und dokumentiert.
- `git diff --check` ist sauber.
- Es wurden keine Secrets oder lokalen privaten Dateien hinzugefügt.
