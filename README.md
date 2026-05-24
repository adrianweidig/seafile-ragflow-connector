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

## Schnellstart für externe Umgebungen

Der Connector wird als eigener Docker-Stack betrieben. Seafile, RAGFlow und
optional OpenWebUI bleiben bestehende externe Systeme. Die einzige
Konfigurationsschnittstelle für Betreiber ist die Datei
[`connector.env.example`](connector.env.example). Kopiere sie zu
`connector.env`, setze nur die Pflichtwerte für deinen Betriebsmodus und starte
danach den Stack.

### 1. Voraussetzungen prüfen

- Docker mit Docker Compose Plugin oder Portainer.
- Ein erreichbarer Seafile-Server mit Admin-API-Token.
- Ein erreichbarer RAGFlow-Server mit API-Key.
- In RAGFlow existiert ein Template-Dataset, standardmäßig
  `connector_template`. Neue Library-Datasets werden daraus erzeugt.
- Optional: eine erreichbare OpenWebUI-Instanz mit Admin-API-Key, wenn Tools
  und Pipes automatisch synchronisiert werden sollen.

### 2. Zentrale Konfiguration anlegen

```bash
cp connector.env.example connector.env
```

Bearbeite danach `connector.env`. Für den Minimalbetrieb Seafile -> RAGFlow
müssen nur die folgenden Werte gesetzt werden:

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `SEAFILE_BASE_URL` | ja | Aus dem Connector-Container erreichbare Seafile-URL, z. B. `http://host.docker.internal:18081` oder `https://seafile.example.local`. |
| `SEAFILE_ADMIN_TOKEN` | ja | Seafile Admin-API-Token für Library-Discovery. |
| `SEAFILE_SYNC_USER_TOKEN` | ja | Seafile API-Token für Downloads der zu synchronisierenden Dateien. |
| `RAGFLOW_BASE_URL` | ja | Aus dem Connector-Container erreichbare RAGFlow-API-URL, z. B. `http://host.docker.internal:19380` oder `http://ragflow:9380`. |
| `RAGFLOW_API_KEY` | ja | RAGFlow API-Key des Ziel-Users. |
| `POSTGRES_PASSWORD` | ja | Passwort für die vom Stack bereitgestellte Connector-Datenbank. |

`DATABASE_URL` kann `POSTGRES_PASSWORD` ersetzen, wenn eine externe Datenbank
genutzt wird. Alle anderen Werte sind optional oder modusabhängig; die
vollständige Liste steht in [`docs/environment.md`](docs/environment.md).

OpenWebUI ist standardmäßig nicht erforderlich:

```env
OPENWEBUI_INTEGRATION_ENABLED=false
OPENWEBUI_SYNC_MODE=disabled
OPENWEBUI_ADMIN_API_KEY=
OPENWEBUI_PROXY_SHARED_SECRET=
```

Wenn deine produktive Umgebung interne oder selbstsignierte Zertifikate nutzt
und der Connector `unable to get local issuer certificate` meldet, lege die
Root-/Intermediate-CA als PEM-Datei auf dem Docker-Host ab und setze z. B.:

```env
CONNECTOR_CERTS_HOST_DIR=/opt/seafile-ragflow-connector/certs
CONNECTOR_CA_BUNDLE=/certs/company-root-ca.pem
SEAFILE_VERIFY_SSL=true
RAGFLOW_VERIFY_SSL=true
OPENWEBUI_VERIFY_SSL=true
```

`CONNECTOR_CA_BUNDLE` gilt für Seafile, RAGFlow und OpenWebUI. Falls nur ein
Dienst betroffen ist, kann stattdessen `SEAFILE_CA_BUNDLE`,
`RAGFLOW_CA_BUNDLE` oder `OPENWEBUI_CA_BUNDLE` gesetzt werden.
`*_VERIFY_SSL=false` ist nur als kurzfristige Diagnose gedacht.
Für lokale Root-CA-, Leaf-Zertifikat-, Hostname- und Ablaufdatumstests gibt es
ein HTTPS-Lab unter [`deploy/tls-lab`](deploy/tls-lab/README.md).

### 3. Netzwerkvariante wählen

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

Wenn die Konfiguration gültig ist:

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

1. In Portainer unter `Images` das Connector-Image importieren oder sicherstellen,
   dass der Docker-Host es pullen kann.
2. Wenn der Docker-Host `postgres:16` und `redis:7` nicht pullen kann, diese
   Images ebenfalls in Portainer importieren.
3. In Portainer einen neuen Stack erstellen.
4. `deploy/portainer/docker-compose.yml` als Web editor Inhalt einfuegen oder
   dieses Repository als Git-Stack verwenden.
5. Den Inhalt von `connector.env.example` im Stack-Bereich `Environment
   variables` importieren.
6. Nur die Pflichtwerte aus dem Minimalblock ersetzen; OpenWebUI-Werte nur
   setzen, wenn die Anbindung aktiviert wird.
7. `CONNECTOR_IMAGE`, `POSTGRES_IMAGE` und `REDIS_IMAGE` müssen exakt den
   Image-Namen entsprechen, die Portainer unter `Images` anzeigt. Wenn alle
   Images lokal vorhanden sind und nicht gepullt werden sollen, setze:

   ```env
   CONNECTOR_IMAGE_PULL_POLICY=never
   POSTGRES_IMAGE_PULL_POLICY=never
   REDIS_IMAGE_PULL_POLICY=never
   ```

8. Stack deployen.
9. Logs von `connector-controller`, `connector-worker` und
   `connector-reconciler` prüfen.
10. Dashboard-Health unter `http://<docker-host>:18080/api/health` prüfen,
    wenn der Dashboard-Port entsprechend veröffentlicht wurde.

Wichtig für Portainer-Image-Uploads: Der Stack startet genau das Image, dessen
Name in `CONNECTOR_IMAGE` steht. Wenn das hochgeladene Image z. B. als
`seafile-ragflow-connector:latest` angezeigt wird, muss `CONNECTOR_IMAGE` auch
genau diesen Wert haben. Wenn es als
`ghcr.io/adrianweidig/seafile-ragflow-connector:latest` angezeigt wird, kann
der Defaultwert bleiben.

### 6. Offline-Installation

Der Online-Start nutzt das veröffentlichte GHCR-Image:

```bash
docker pull ghcr.io/adrianweidig/seafile-ragflow-connector:latest
```

Für Offline-Umgebungen können die benötigten Images vorab exportiert und auf
dem Zielhost importiert werden:

```bash
docker save \
  ghcr.io/adrianweidig/seafile-ragflow-connector:latest \
  postgres:16 \
  redis:7 \
  -o images/seafile-ragflow-portainer-images.tar

docker load -i images/seafile-ragflow-portainer-images.tar
```

Die gleiche Tar-Datei kann in Portainer unter `Images` importiert werden.

Wenn interne Registry- oder lokale Image-Namen genutzt werden, trage sie in
`connector.env` ein:

```env
CONNECTOR_IMAGE=seafile-ragflow-connector:latest
POSTGRES_IMAGE=postgres:16
REDIS_IMAGE=redis:7
```

### 7. Betrieb prüfen

Nach dem Start sollten diese Punkte stimmen:

- Dashboard-Health meldet für Dashboard, Datenbank, Redis, Seafile und RAGFlow
  `ok`.
- In RAGFlow entsteht pro Seafile-Library ein Dataset aus dem Template.
- Dateien werden in RAGFlow hochgeladen und geparst.
- Wenn OpenWebUI aktiviert ist, erscheinen pro Dataset ein Tool und eine Pipe
  beziehungsweise ein auswählbares Custom Model.
- Wird eine Seafile-Library gelöscht, entfernt der Connector die zugehörigen
  eigenen RAGFlow- und OpenWebUI-Artefakte.

Die Compose-Datei referenziert keine lokale `env_file`. Docker Compose bekommt
die Werte über `--env-file connector.env`; Portainer bekommt dieselben Werte
über den Environment-Variablen-Import.

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
Für `sync` und `repair` sind `OPENWEBUI_ADMIN_API_KEY`,
`OPENWEBUI_PROXY_SHARED_SECRET` und eine Proxy-Base-URL erforderlich, wenn
Tools oder Pipes erzeugt werden. Für eine reine Vorprüfung kann `dry-run`
gesetzt werden; dann sind Proxy-Secret und Preview-URL nicht erforderlich.
Quellen werden primär
als OpenWebUI-Citations mit Preview-URL bereitgestellt; wenn RAGFlow keinen
stabilen öffentlichen Deep Link hat, kann `OPENWEBUI_SOURCE_PREVIEW_MODE` auf
`connector_viewer` gesetzt werden.

## Entwicklungschecks

```bash
uv sync --locked --all-extras
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

Für wiederholbare lokale Prüfungen gibt es einen zentralen Verify-Runner:

```bash
python scripts/verify.py --skip-compose
```

Wenn Docker Compose auf dem Host verfügbar ist, prüft der Runner zusätzlich die
Portainer-Compose-Konfiguration. Erzwingen lässt sich diese Prüfung mit:

```bash
python scripts/verify.py --with-compose
```

## Hinweise für Codex und andere Agenten

Projektbezogene Arbeitsregeln stehen in [`AGENTS.md`](AGENTS.md). Wichtig sind
vor allem: vor Änderungen den Git-Zustand prüfen, bestehende Änderungen
bewahren, keine Secrets ausgeben oder persistieren, keine produktiven Dienste
ohne Auftrag mutieren und Löschungen nur nach Referenzprüfung durchführen.

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz. Details stehen in [`LICENSE`](LICENSE);
bei kommerziell oder rechtlich kritischer Nutzung sollte die Lizenzentscheidung
menschlich geprüft werden.

## Dokumentation

- [Architektur](docs/architecture.md)
- [Konfiguration](docs/configuration.md)
- [Environment-Variablen](docs/environment.md)
- [Test- und Ausführungsmodell](docs/testing.md)
- [Betrieb, Offline-Deployment und WSL-/Docker-Prüfung](docs/operations.md)
- [RAGFlow-Template-Verhalten](docs/ragflow-template.md)
- [TLS-Zertifikate](docs/tls-certificates.md)
- [TLS-Topologie](docs/tls-topology.md)
- [Docker-Compose mit TLS](docs/docker-compose-tls.md)
- [SSL-/TLS-Troubleshooting](docs/troubleshooting-ssl.md)
