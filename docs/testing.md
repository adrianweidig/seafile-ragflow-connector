# Test- und Ausführungsmodell

Dieses Projekt ist ein Python-3.12+-Connector mit externer Seafile-, RAGFlow-
und optionaler OpenWebUI-Anbindung. Die normalen Repository-Checks laufen ohne
echte Server, Secrets oder produktive Dienste. Externe Systeme werden in Unit-
und Integrationstests durch Fakes, lokale HTTP-Server, temporäre TLS-
Zertifikate und SQLite ersetzt.

## Standardablauf für Codex

1. Arbeitsbaum prüfen:

   ```bash
   git status --short --branch
   ```

2. Abhängigkeiten synchronisieren:

   ```bash
   uv sync --locked --all-extras
   ```

   Das Dev-Tooling liegt im optionalen Extra `dev`. Es gibt keine separate
   `dependency-groups.dev`, damit lokale Installation und CI denselben Pfad
   nutzen.

3. Schnelle komplette Prüfung ohne Docker Compose:

   ```bash
   python scripts/verify.py --skip-compose
   ```

4. Wenn Docker Compose verfügbar ist, zusätzlich die Portainer-Compose-
   Konfiguration prüfen:

   ```bash
   python scripts/verify.py --with-compose
   ```

   Für einen lokalen HTTPS-Mock-Smoke-Check mit Seafile-/RAGFlow-Mocks,
   `connector check-live --json` und Dashboard-TLS-Health:

   ```bash
   python scripts/verify.py --skip-compose --with-mock-smoke
   ```

   Dieser Check startet Docker-Services und ist deshalb explizit opt-in. Ohne
   Docker bleibt der Standardlauf mit `--skip-compose` rein lokal.

5. Vor Abschluss immer prüfen:

   ```bash
   git diff --check
   git status --short --branch
   ```

## Einzelchecks

Diese Befehle sind hilfreich, wenn nur ein Fehlerbereich eingegrenzt werden
soll:

```bash
uv run python -m compileall src tests migrations scripts
uv run ruff check .
uv run mypy src
uv run python scripts/validate_deployment_env.py
uv run pytest
PYTHONPATH=src uv run python -m unittest discover -s tests/unit
```

## Testbereiche

- `tests/unit/`: schnelle Tests für Settings, CLI, Clients, Dashboard, Domain-
  Logik, Jobs, OpenWebUI-Artifact-Generierung und Sync-Orchestrierung.
- `tests/integration/clients/`: lokale TLS-Szenarien mit temporären
  Zertifikaten und lokalem HTTPS-Testserver.
- `deploy/tls-lab/`: manuelles Docker-Compose-Lab für CA-Bundle- und
  Zertifikatsdiagnose.
- `deploy/portainer/docker-compose.yml`: zentrale Compose-Konfiguration für
  Betreiber; syntaktisch mit `docker compose ... config --quiet` prüfbar.
- `deploy/compose/local-mocks.compose.yml`: opt-in Smoke-Overlay für lokale
  Seafile-/RAGFlow-HTTPS-Mocks über `python scripts/verify.py --with-mock-smoke`.
- `scripts/validate_deployment_env.py`: prüft ohne Docker, dass die
  `x-connector-env`-Blöcke der Compose-/Portainer-/Swarm-Dateien dieselben
  runtime-relevanten Schlüssel wie `connector.env.example` enthalten.

## Dashboard-UI- und Visual-QA

Das Dashboard-HTML liegt als paketierte Ressource unter
`src/seafile_ragflow_connector/dashboard/assets/dashboard.html` und wird über
`seafile_ragflow_connector.dashboard.ui.DASHBOARD_HTML` geladen. Unit-Tests
prüfen die Ressource, Sprachwahl, Busy-/Empty-States, OpenWebUI-Tab und
Touch-Zielgrößen.

Bei sichtbaren Dashboard-Änderungen zusätzlich den opt-in Browser-Smoke mit
Playwright ausführen:

```bash
uv run --extra dev python scripts/playwright_dashboard_smoke.py
```

oder über den Verify-Runner:

```bash
uv run python scripts/verify.py --skip-sync --skip-compose --with-dashboard-browser-smoke
```

Der Check startet einen lokalen Dashboard-Server mit SQLite-Fixtures, klickt die
zentralen Tabs, prüft die Sprachwahl und schreibt Desktop-/Mobile-Screenshots
nach `output/playwright/`. Falls Browser-Binaries fehlen, einmalig Chromium
installieren:

```bash
uv run --extra dev python -m playwright install chromium
```

Manuelle Visual-QA bleibt sinnvoll, wenn Layout, Farben oder Responsiveness
geändert wurden. Dabei besonders Navigation, Sprachwahl, Tabellenbreiten,
Auth-Fehlerzustand, Health/TLS-Karten und leere Ansichten kontrollieren.

## Externe Dienste und Secrets

Die Standardchecks benötigen keine echten Tokens. Werte wie
`SEAFILE_ADMIN_TOKEN`, `RAGFLOW_API_KEY`, `OPENWEBUI_ADMIN_API_KEY` und
`OPENWEBUI_PROXY_SHARED_SECRET` bleiben Platzhalter in Beispieldateien.

Live-Kommandos wie `connector check-live`, `connector sync-once` oder
`connector cleanup-orphans` dürfen nur gegen eine bewusst gewählte Test- oder
Demo-Umgebung ausgeführt werden. Sie gehören nicht zum Standard-CI-Lauf.

## Typische Diagnose

- `ModuleNotFoundError` bei direktem `python -m unittest`: Abhängigkeiten fehlen
  im globalen Python. `uv sync --locked --all-extras` ausführen und danach
  `uv run ...` nutzen.
- `docker` nicht gefunden: Compose-Prüfung mit `--skip-compose` auslassen oder
  aus einer Umgebung mit Docker/WSL-Docker ausführen.
- TLS-Fehler in Live-Checks: CA-Bundle-Pfade aus Sicht des jeweiligen
  Containers prüfen, nicht nur aus Sicht des Hosts.
- OpenWebUI-Sync schlägt in Live-Umgebungen fehl: zuerst prüfen, ob das
  Ziel-Dataset mindestens ein geparstes Dokument besitzt und ob API-Keys
  persistent aktiviert sind.

## CI-Abgleich

GitHub Actions nutzt denselben Verify-Runner ohne Compose:

```bash
uv sync --locked --all-extras
uv run python scripts/verify.py --skip-sync --skip-compose
```

Damit bleiben lokale Codex-Prüfung und CI-Reihenfolge konsistent. Compose- und
Live-Stack-Prüfungen bleiben bewusst manuelle beziehungsweise umgebungsnahe
Diagnosen.
