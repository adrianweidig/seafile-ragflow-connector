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
  OpenWebUI, lokale HTTPS-Mocks, lokalen `connector.top.secret`-HTTPS-Edge und
  TLS-Beispiele.
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
- Für lokale Windows-/WSL-Prüfungen über `https://connector.top.secret` die
  Anleitung in `docs/local-https-compose.md` verwenden. Das Overlay
  `deploy/compose/connector-top-secret.compose.yml` darf nur lokale
  Testzertifikate aus ungetrackten Pfaden mounten.
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
- Öffentliche Community-Dokumente wie `CONTRIBUTING.md`, `SECURITY.md`,
  `SUPPORT.md`, `CHANGELOG.md` und `.github/ISSUE_TEMPLATE/*` müssen konkrete
  Projektregeln enthalten und dürfen keine generischen Platzhaltertexte
  verwenden.
- README-Badges und GitHub-Links nur setzen, wenn Owner, Repository und
  Workflow-Dateien eindeutig vorhanden sind.
- Deutsche Fließtexte verwenden echte UTF-8-Umlaute, z. B. `für`, `über`,
  `vollständig`, `prüfen` und `zurück`. ASCII-Umschreibungen deutscher Umlaute
  bleiben unerwünscht. Keine blinden globalen Ersetzungen in Code, Pfaden,
  Env-Variablen, IDs oder technischen Strings.
- Beispielwerte bleiben offensichtliche Platzhalter wie `change-me` oder
  `YOUR_API_KEY`.
- Deutsch ist die Standardsprache. Neue menschenlesbare Laufzeittexte müssen
  über `src/seafile_ragflow_connector/locales/de.json` und `en.json` oder über
  die dokumentierte Dashboard-Sprachstruktur pflegbar sein. GitHub-Dateien
  brauchen sichtbare Sprachlinks oder deutsch/englische Beschriftungen, weil
  GitHub die Repository-Ansicht nicht automatisch übersetzt.

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
- HTML- oder Markdown-Fragmente aus RAGFlow/OpenWebUI nicht mit unbounded
  regulären Ausdrücken bereinigen. Für Vorschauen und Snippets parserbasierte
  Bereinigung oder strikt begrenzte Eingaben verwenden, damit CodeQL-ReDoS-
  Alerts nicht erneut entstehen.
- TLS-Testserver und lokale HTTPS-Mocks müssen TLS 1.2 oder neuer erzwingen,
  auch wenn sie nur für Tests oder lokale Labs gedacht sind.

## Definition of Done

- Relevante Dokumentation und Agentenhinweise sind konsistent.
- `README.md`, `docs/README.md`, `connector.env.example` und Deployment-
  Beispiele widersprechen sich nicht.
- Lizenzangaben in `LICENSE`, `README.md` und `pyproject.toml` sind konsistent.
- `python scripts/verify.py --skip-compose` oder begründete Alternativen
  wurden ausgeführt und dokumentiert.
- `git diff --check` ist sauber.
- Es wurden keine Secrets oder lokalen privaten Dateien hinzugefügt.
