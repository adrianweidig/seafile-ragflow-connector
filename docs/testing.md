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

   Unter Windows mit Docker in WSL sollte der Wrapper genutzt werden, damit
   `uv` eine WSL-eigene virtuelle Umgebung außerhalb des Windows-Checkouts
   verwendet:

   ```bash
   wsl -d Debian -- bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && bash scripts/verify_wsl.sh --with-compose --with-dashboard-browser-smoke'
   ```

   Für einen lokalen HTTPS-Mock-Smoke-Check mit Seafile-/RAGFlow-Mocks,
   `connector check-live --json` und Dashboard-TLS-Health:

   ```bash
   python scripts/verify.py --skip-compose --with-mock-smoke
   ```

   Dieser Check baut zuerst ein lokales Test-Image aus dem aktuellen Checkout,
   startet Docker-Services und ist deshalb explizit opt-in. Ohne Docker bleibt
   der Standardlauf mit `--skip-compose` rein lokal.

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
- `tests/integration/test_manual_workflow.py`: lokaler Fake-basierter
  End-to-End-Test für Seafile-Discovery, RAGFlow-Dataset-/Dokument-Sync und
  OpenWebUI-Tool-/Pipe-Bindung.
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
prüfen die Ressource, Sprachwahl, Busy-/Empty-States, Workflow- und
OpenWebUI-Tab sowie Touch-Zielgrößen. Für die Adminoberfläche prüfen sie
zusätzlich globale, bibliotheksspezifische und laufbezogene Aktionen, den
Schutzheader und die getrennte lesende Darstellung ohne Controller-Kontext.

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
Auth-Fehlerzustand, Health/TLS-Karten, Adminzustände, Fortschrittsanzeigen und
leere Ansichten kontrollieren.

## Admin-Control-Regression

Die Adminsteuerung betrifft Settings, Migrationen, Dashboard-Server, JobStore,
Worker, Orchestrator und OpenWebUI-Scheduling. Der gezielte lokale Lauf ist:

```bash
uv run --offline --no-sync pytest \
  tests/unit/dashboard \
  tests/unit/jobs \
  tests/unit/test_job_store.py \
  tests/unit/persistence \
  tests/unit/sync \
  tests/unit/app/test_cli.py \
  tests/unit/openwebui/test_sync.py \
  tests/unit/config/test_settings.py
```

Die Regression muss mindestens diese Verträge abdecken:

- `CONNECTOR_DASHBOARD_CONTROL_ENABLED=true` wird ohne aktiviertes Dashboard
  und vollständige Basic-Auth-Werte bereits als ungültige Konfiguration
  abgelehnt.
- Mutationen lehnen fehlende Authentifizierung, anderen Content-Type und einen
  fehlenden oder falschen Header `X-Connector-Admin-Action: 1` ab; Authz- und
  OpenWebUI-Service-POSTs behalten ihren getrennten Vertrag.
- Globaler Start, Deaktivieren, Pause, Fortsetzen und bestätigter Stop bilden
  exakt Automatik- und Queue-Zustand ab. Stop ohne `{"confirm":"STOP"}` bleibt
  wirkungslos.
- Bibliothekszustände überleben einen neuen Store-/Prozesskontext. `disabled`
  und `paused` blockieren manuelle und automatische Arbeit, markieren die
  Bibliothek aber nicht als gelöscht und planen keine Zielbereinigung.
- Wartende oder retryende pausierte Jobs werden nicht geclaimt. Ein laufender
  Job kehrt kooperativ nach `queued` zurück; Resume löscht nur den Hold, und
  Cancel gewinnt bei konkurrierenden Anforderungen.
- Parsing-Fortschritt enthält konsistente `tracked`, `done`, `pending`,
  `failed` und `percent`-Werte. Workflowfortschritt bleibt zwischen API-Abrufen
  und Neustarts persistent und regressiert nicht durch fehlende Rohwerte.
- Die persistente Änderungs-/Audit-Historie unter `/api/changes` erfasst
  Akteur, Aktion, Ziel, Vorher-/Nachher-Zustand und Ergebnis, aber weder
  Basic-Auth-Passwort noch Tokens oder andere Secrets.

Für die gerenderte Abnahme muss das Browserziel die Controller-Variante mit
Control-Store, Orchestrator, JobStore und SignalQueue verwenden. Die
Standalone-Variante ist ein eigener negativer Test: Dort muss die Oberfläche
lesend bleiben und Adminaktionen als nicht verfügbar zeigen. Der interaktive
Browser-Smoke deckt Authentifizierung, globales Pause/Fortsetzen,
bibliotheksspezifisches Pause/Fortsetzen, einen manuellen Delta-Lauf,
Lauf- und Dateifortschritt, den Parsing-Bereich einschließlich Leerzustand,
Historie und mobile Darstellung repräsentativ ab. Server- und Unit-Tests prüfen
die globale Aktionsmatrix, Laufübergänge und Bestätigungen, persistente
Bibliothekszustände sowie die Zuordnung von Delta-, Voll- und
Reconcile-Spezifikationen; Stop/Cancel ohne `{"confirm":"STOP"}` bleibt
wirkungslos.

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

`--skip-sync` verwendet für alle nachfolgenden Prüfungen automatisch
`uv run --no-sync`. Mit `--offline` wird zusätzlich jeglicher Netzwerkzugriff
von uv unterbunden; dafür müssen Lockfile-Abhängigkeiten bereits im lokalen
Cache vorhanden sein.

CI misst zusätzlich Branch-Coverage ohne vorzeitig einen blinden Mindestwert zu
erzwingen:

```bash
uv run coverage run -m pytest
uv run coverage report
```

Damit bleiben lokale Codex-Prüfung und CI-Reihenfolge konsistent. Compose- und
Live-Stack-Prüfungen bleiben bewusst manuelle beziehungsweise umgebungsnahe
Diagnosen.
