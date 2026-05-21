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

## Schnellstart fuer externe Umgebungen

Der Connector wird als eigener Docker-Stack betrieben. Seafile, RAGFlow und
optional OpenWebUI bleiben bestehende externe Systeme. Die einzige
Konfigurationsschnittstelle fuer Betreiber ist die Datei
[`connector.env.example`](connector.env.example). Kopiere sie zu
`connector.env`, ersetze die Platzhalter und starte danach den Stack.

### 1. Voraussetzungen pruefen

- Docker mit Docker Compose Plugin oder Portainer.
- Ein erreichbarer Seafile-Server mit Admin-API-Token.
- Ein erreichbarer RAGFlow-Server mit API-Key.
- In RAGFlow existiert ein Template-Dataset, standardmaessig
  `connector_template`. Neue Library-Datasets werden daraus erzeugt.
- Optional: eine erreichbare OpenWebUI-Instanz mit Admin-API-Key, wenn Tools
  und Pipes automatisch synchronisiert werden sollen.

### 2. Zentrale Konfiguration anlegen

```bash
cp connector.env.example connector.env
```

Bearbeite danach `connector.env`. Fuer einen normalen Start muessen nur die
folgenden Werte gesetzt werden:

| Variable | Zweck |
| --- | --- |
| `SEAFILE_BASE_URL` | Aus dem Connector-Container erreichbare Seafile-URL, z. B. `http://host.docker.internal:18081` oder `https://seafile.example.local`. |
| `SEAFILE_ADMIN_TOKEN` | Seafile Admin-API-Token fuer Library-Discovery. |
| `SEAFILE_SYNC_USER_TOKEN` | Seafile API-Token fuer Downloads der zu synchronisierenden Dateien. |
| `RAGFLOW_BASE_URL` | Aus dem Connector-Container erreichbare RAGFlow-API-URL, z. B. `http://host.docker.internal:19380` oder `http://ragflow:9380`. |
| `RAGFLOW_API_KEY` | RAGFlow API-Key des Ziel-Users. |
| `POSTGRES_PASSWORD` | Passwort fuer die vom Stack bereitgestellte Connector-Datenbank. |
| `OPENWEBUI_BASE_URL` | Nur bei OpenWebUI-Anbindung: aus dem Connector erreichbare OpenWebUI-URL. |
| `OPENWEBUI_ADMIN_API_KEY` | Nur bei OpenWebUI-Anbindung: Admin-API-Key fuer Tool-/Pipe-Sync. |
| `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | Browser-URL zum Connector-Dashboard/Proxy, z. B. `http://localhost:18080`. |
| `OPENWEBUI_PROXY_INTERNAL_BASE_URL` | URL, die OpenWebUI serverseitig zum Connector erreicht. |
| `OPENWEBUI_PROXY_SHARED_SECRET` | Eigenes langes Zufallssecret fuer den geschuetzten Connector-Proxy. |

Wenn OpenWebUI nicht angebunden werden soll, setze:

```env
OPENWEBUI_INTEGRATION_ENABLED=false
OPENWEBUI_SYNC_MODE=disabled
OPENWEBUI_ADMIN_API_KEY=
OPENWEBUI_PROXY_SHARED_SECRET=
```

### 3. Netzwerkvariante waehlen

Host/LAN/Reverse Proxy ist der einfachste Fall. Behalte:

```env
CONNECTOR_DOCKER_NETWORK_EXTERNAL=false
SEAFILE_BASE_URL=http://host.docker.internal:18081
RAGFLOW_BASE_URL=http://host.docker.internal:19380
OPENWEBUI_BASE_URL=http://host.docker.internal:3000
```

Wenn Seafile, RAGFlow und OpenWebUI bereits in einem gemeinsamen Docker-Netz
laufen, nutze stattdessen:

```env
CONNECTOR_DOCKER_NETWORK_EXTERNAL=true
CONNECTOR_DOCKER_NETWORK_NAME=<bestehendes-docker-netz>
SEAFILE_BASE_URL=http://seafile
RAGFLOW_BASE_URL=http://ragflow:9380
OPENWEBUI_BASE_URL=http://openwebui:8080
OPENWEBUI_PROXY_INTERNAL_BASE_URL=http://connector-controller:8080
```

### 4. Start mit Docker Compose

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet
```

Wenn die Konfiguration gueltig ist:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  up -d
```

Logs ansehen:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  logs -f connector-controller connector-worker connector-reconciler
```

Healthcheck:

```bash
curl http://127.0.0.1:18080/api/health
```

Das Dashboard ist bei Default-Portbindung lokal erreichbar:

```text
http://127.0.0.1:18080
```

### 5. Start mit Portainer

1. In Portainer einen neuen Stack erstellen.
2. `deploy/portainer/docker-compose.yml` als Web editor Inhalt einfuegen oder
   dieses Repository als Git-Stack verwenden.
3. Den Inhalt von `connector.env.example` im Stack-Bereich `Environment
   variables` importieren.
4. Alle `change-me` Werte und die Base-URLs ersetzen.
5. Stack deployen.
6. Logs von `connector-controller`, `connector-worker` und
   `connector-reconciler` pruefen.
7. Dashboard-Health unter `http://<docker-host>:18080/api/health` pruefen,
   wenn der Dashboard-Port entsprechend veroeffentlicht wurde.

### 6. Offline-Installation

Der Online-Start nutzt das veroeffentlichte GHCR-Image:

```bash
docker pull ghcr.io/adrianweidig/seafile-ragflow-connector:latest
```

Fuer Offline-Umgebungen koennen die benoetigten Images vorab exportiert und auf
dem Zielhost importiert werden:

```bash
docker save ghcr.io/adrianweidig/seafile-ragflow-connector:latest \
  -o images/seafile-ragflow-connector_latest.tar
docker save postgres:16 -o images/postgres_16.tar
docker save redis:7 -o images/redis_7.tar

docker load -i images/seafile-ragflow-connector_latest.tar
docker load -i images/postgres_16.tar
docker load -i images/redis_7.tar
```

Wenn interne Registry- oder lokale Image-Namen genutzt werden, trage sie in
`connector.env` ein:

```env
CONNECTOR_IMAGE=seafile-ragflow-connector:latest
POSTGRES_IMAGE=postgres:16
REDIS_IMAGE=redis:7
```

### 7. Betrieb pruefen

Nach dem Start sollten diese Punkte stimmen:

- Dashboard-Health meldet fuer Dashboard, Datenbank, Redis, Seafile und RAGFlow
  `ok`.
- In RAGFlow entsteht pro Seafile-Library ein Dataset aus dem Template.
- Dateien werden in RAGFlow hochgeladen und geparst.
- Wenn OpenWebUI aktiviert ist, erscheinen pro Dataset ein Tool und eine Pipe
  beziehungsweise ein auswählbares Custom Model.
- Wird eine Seafile-Library geloescht, entfernt der Connector die zugehoerigen
  eigenen RAGFlow- und OpenWebUI-Artefakte.

Die Compose-Datei referenziert keine lokale `env_file`. Docker Compose bekommt
die Werte ueber `--env-file connector.env`; Portainer bekommt dieselben Werte
ueber den Environment-Variablen-Import.

## Repository-Struktur

| Pfad | Zweck |
| --- | --- |
| `.github/workflows/` | GitHub Actions für Tests und GHCR-Image-Publishing |
| `deploy/docker/` | Dockerfile und Container-Entrypoint für das Connector-Image |
| `deploy/portainer/` | Portainer-fähige Compose-Datei für die zentrale `connector.env.example` |
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
OPENWEBUI_SYNC_MODE=sync
OPENWEBUI_PROXY_INTERNAL_BASE_URL=http://connector-controller:8080
OPENWEBUI_PROXY_PUBLIC_BASE_URL=http://localhost:18080
OPENWEBUI_PROXY_SHARED_SECRET=change-me
```

`OPENWEBUI_SYNC_MODE` unterstützt `disabled`, `dry-run`, `sync` und `repair`.
Die bereitgestellten Testvorlagen sind auf `sync` gestellt, damit Chats, Tools
und Pipes direkt erzeugt werden. Für eine reine Vorprüfung kann jederzeit
`dry-run` gesetzt werden. Quellen werden primär
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
