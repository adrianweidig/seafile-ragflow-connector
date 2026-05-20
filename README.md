# Seafile RAGFlow Connector

Offline-fähiger Sync-Orchestrator für den Betrieb zwischen einem bestehenden
Seafile-Server und einem bestehenden RAGFlow-Server. Der Connector entdeckt
Seafile-Libraries, erzeugt pro Library ein RAGFlow-Dataset aus einem
`connector_template`, importiert Dateien, erkennt Änderungen, löscht entfernte
Dokumente sicher und läuft nach Neustarts weiter.

## Kernprinzipien

- Die Seafile API ist die Quelle der Wahrheit.
- Die RAGFlow API und optional OpenWebUI sind Zielsysteme.
- Seafile wird nie geändert, nur weil Zielartefakte in RAGFlow oder OpenWebUI
  fehlen, gelöscht wurden oder driften.
- Entfernte Seafile-Dateien und -Libraries werden in den Zielsystemen
  nachvollzogen; extern gelöschte Zielartefakte werden aus Seafile neu
  aufgebaut.
- PostgreSQL speichert den dauerhaften Sync-Zustand.
- Redis übernimmt Queueing, Retries und Backpressure.
- RAGFlow-Dataset-Einstellungen bleiben nach der Erstellung live. Das Template
  wird nur für neue Datasets genutzt.
- Der Runtime-Betrieb ist offline-fähig: keine Paket-Downloads, keine Telemetrie
  und keine externen Service-Abhängigkeiten außerhalb der konfigurierten
  Seafile- und RAGFlow-URLs.

## Offline-Deployment mit Portainer

Der einfachste Online-Start nutzt das veröffentlichte GHCR-Image:

```bash
docker pull ghcr.io/adrianweidig/seafile-ragflow-connector:latest
```

Für Offline-Umgebungen kann dasselbe Image vorab exportiert und auf dem
Zielhost importiert werden:

```bash
docker save ghcr.io/adrianweidig/seafile-ragflow-connector:latest \
  -o images/seafile-ragflow-connector_latest.tar
docker load -i images/seafile-ragflow-connector_latest.tar
```

Portainer-Start:

1. Bei Offline-Betrieb benötigte Images auf dem Docker-Host importieren.
2. In Portainer einen neuen Stack erstellen.
3. `deploy/portainer/docker-compose.yml` einfügen oder dieses Repo als Git-Stack
   verwenden.
4. `deploy/portainer/stack.env.example` in Portainer als Environment importieren.
5. Alle `change-me` Werte ersetzen und `SEAFILE_BASE_URL` sowie
   `RAGFLOW_BASE_URL` auf aus dem Connector-Container erreichbare URLs setzen.
6. Stack starten und die Logs von Controller, Worker und Reconciler prüfen.

Seafile und RAGFlow werden nicht durch diesen Stack bereitgestellt. Sie bleiben
externe Systeme, erreichbar über LAN, Reverse Proxy, veröffentlichte Host-Ports
oder ein gemeinsames Docker-Netzwerk. Für bestehende Docker-Stacks kann
`CONNECTOR_DOCKER_NETWORK_EXTERNAL=true` mit dem vorhandenen Netzwerknamen
gesetzt werden. Die Compose-Datei referenziert keine lokale `env_file`;
Portainer-Environment-Variablen reichen aus.

## Repository-Struktur

| Pfad | Zweck |
| --- | --- |
| `.github/workflows/` | GitHub Actions für Tests und GHCR-Image-Publishing |
| `deploy/docker/` | Dockerfile und Container-Entrypoint für das Connector-Image |
| `deploy/portainer/` | Portainer-fähige Compose-Datei und importierbare Beispiel-Env |
| `deploy/compose/` | Direkt nutzbare Compose-Varianten für Host/LAN, Shared Network und OpenWebUI |
| `deploy/swarm/` | Docker-Swarm-Alternative mit Stackfile und Env-Vorlage |
| `docs/` | Architektur, Konfiguration, Betrieb und RAGFlow-Template-Verhalten |
| `migrations/` | Alembic-Migrationen für PostgreSQL/SQLite-Testdatenbanken |
| `src/seafile_ragflow_connector/` | Anwendungscode für CLI, Sync, Clients, Dashboard, Jobs und OpenWebUI |
| `tests/` | Unit-, Integrations- und Support-Tests mit lokalen Fakes/Fixtures |

Jeder dieser Ordner enthält eine kurze README, die den Inhalt und den
üblichen Einstiegspunkt beschreibt.

## Dashboard

Der Connector enthält ein lesendes HTTP-Dashboard für Administratoren,
Auditoren und Entwickler. Es zeigt Connector-Zustand, Sync-Historie,
Änderungen, Quellen/Ziele, gefilterte Logs und technische Diagnosewerte. Es
erzwingt bewusst keine Authentifizierung; der Zugriff wird über
Netzwerkexposition gesteuert. Wer die Oberfläche nicht erreichbar machen will,
aktiviert sie nicht oder veröffentlicht den Port nicht. Die Oberfläche nutzt
keine CDN- oder Internet-Assets, bietet einen Dark-/Light-Modus und enthält
einen auswählbaren Auto-Refresh für 5 Sekunden, 10 Sekunden oder 1 Minute. Ein
System-Health-Bereich prüft Dashboard, Datenbank, Redis, Seafile, RAGFlow und
Sync-Job-Zustand. Der Excel-Audit-Export enthält mehrere Tabellenblätter.
Exportiert werden nur Status-, Sync-, Änderungs-, Log- und Diagnosemetadaten;
Datei-Inhalte aus Seafile oder RAGFlow werden nicht heruntergeladen.
Schreibaktionen werden nicht angeboten.

Da das Projekt bisher keine Weboberfläche hatte, ist das Dashboard standardmäßig
deaktiviert:

```env
CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_HOST=0.0.0.0
CONNECTOR_DASHBOARD_PORT=8080
```

Im Portainer-Stack läuft das Dashboard im `connector-controller`. Die
Beispielkonfiguration veröffentlicht es lokal am Docker-Host unter
`127.0.0.1:18080`, wenn es aktiviert ist.

## Optionale OpenWebUI-Anbindung

Die OpenWebUI-Anbindung ist standardmäßig vollständig deaktiviert. Wenn sie per
Environment aktiviert wird, synchronisiert der Connector pro RAGFlow-Dataset
einen RAGFlow-Chat-Assistant sowie je ein OpenWebUI-Tool und eine Pipe. Die
Pipe erscheint in OpenWebUI als auswählbares Custom-Model. Tool und Pipe
enthalten keine RAGFlow- oder Admin-Secrets, sondern rufen den geschützten
Connector-Proxy auf.

```env
OPENWEBUI_INTEGRATION_ENABLED=true
OPENWEBUI_BASE_URL=http://openwebui:8080
OPENWEBUI_ADMIN_API_KEY=change-me
OPENWEBUI_SYNC_MODE=dry-run
OPENWEBUI_PROXY_INTERNAL_BASE_URL=http://connector-controller:8080
OPENWEBUI_PROXY_PUBLIC_BASE_URL=http://localhost:18080
OPENWEBUI_PROXY_SHARED_SECRET=change-me
```

`OPENWEBUI_SYNC_MODE` unterstützt `disabled`, `dry-run`, `sync` und `repair`.
Für den ersten Betrieb sollte `dry-run` genutzt werden. Quellen werden primär
als OpenWebUI-Citations mit Preview-URL bereitgestellt; wenn RAGFlow keinen
stabilen öffentlichen Deep Link hat, kann `OPENWEBUI_SOURCE_PREVIEW_MODE` auf
`connector_viewer` gesetzt werden.

## Entwicklungschecks

```bash
python -m compileall src tests migrations
PYTHONPATH=src python -m unittest discover -s tests/unit
```

Vollständige Entwicklungsumgebungen können zusätzlich ausführen:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
```

## Dokumentation

- [Architektur](docs/architecture.md)
- [Konfiguration](docs/configuration.md)
- [Betrieb, Offline-Deployment und WSL-/Docker-Prüfung](docs/operations.md)
- [RAGFlow-Template-Verhalten](docs/ragflow-template.md)
