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

3. Schnelle komplette Prüfung ohne Docker Compose:

   ```bash
   python scripts/verify.py --skip-compose
   ```

4. Wenn Docker Compose verfügbar ist, zusätzlich die Portainer-Compose-
   Konfiguration prüfen:

   ```bash
   python scripts/verify.py --with-compose
   ```

5. Vor Abschluss immer prüfen:

   ```bash
   git diff --check
   git status --short --branch
   ```

## Einzelchecks

Diese Befehle sind hilfreich, wenn nur ein Fehlerbereich eingegrenzt werden
soll:

```bash
uv run python -m compileall src tests migrations
uv run ruff check .
uv run mypy src
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
