# Betrieb und lokale Prüfung

Dieses Dokument bündelt Offline-Deployment, Portainer-Betrieb, Recovery,
Troubleshooting, Release und die lokale WSL-/Docker-Prüfung.

## Portainer-Deployment

Der produktive Stack liegt unter `deploy/portainer/docker-compose.yml`. Die
einheitliche Beispielkonfiguration liegt im Repo-Root unter
`connector.env.example`.

Standardmäßig zieht der Stack das Connector-Image aus GHCR:

```bash
docker pull ghcr.io/adrianweidig/seafile-ragflow-connector:latest
```

Für reproduzierbare produktive Rollouts kann `CONNECTOR_IMAGE` in Portainer auf
einen Release- oder SHA-Tag gesetzt werden. Für Offline-Betrieb kann dasselbe
Image vorab exportiert und auf dem Zielhost geladen werden.

Die Compose-Datei referenziert keine lokale `env_file`. In Portainer reicht es,
die Compose-Datei einzufügen oder das Repo als Git-Stack zu nutzen und die Werte
aus `connector.env.example` im Bereich `Environment variables` zu importieren.

1. Bei Offline-Betrieb benötigte Images auf dem Docker-Host importieren,
   beispielsweise:
   `docker load -i images/seafile-ragflow-portainer-images.tar`
2. Wenn der Docker-Host `postgres:16` und `redis:7` nicht pullen kann, auch
   diese Images importieren.
3. In Portainer einen neuen Stack erstellen.
4. Inhalt von `deploy/portainer/docker-compose.yml` einfügen.
5. `connector.env.example` in Portainer importieren.
6. Die Minimalpflichtwerte ersetzen: `SEAFILE_BASE_URL`,
   `SEAFILE_ADMIN_TOKEN`, `SEAFILE_SYNC_USER_TOKEN`, `RAGFLOW_BASE_URL`,
   `RAGFLOW_API_KEY` und `POSTGRES_PASSWORD` oder alternativ `DATABASE_URL`.
7. `CONNECTOR_IMAGE`, `POSTGRES_IMAGE` und `REDIS_IMAGE` müssen exakt den
   Image-Namen entsprechen, die Portainer unter `Images` anzeigt. Wenn nur
   lokale Images genutzt werden sollen, `CONNECTOR_IMAGE_PULL_POLICY=never`,
   `POSTGRES_IMAGE_PULL_POLICY=never` und `REDIS_IMAGE_PULL_POLICY=never`
   setzen.
8. `SEAFILE_BASE_URL` und `RAGFLOW_BASE_URL` auf die aus dem
   Connector-Container erreichbaren URLs setzen.
9. Stack starten und die Logs von `connector-controller`, `connector-worker` und
   `connector-reconciler` prüfen.

Der Stack stellt Seafile und RAGFlow nicht bereit. Beide Systeme bleiben extern
und müssen über die konfigurierten URLs erreichbar sein.

Es gibt zwei unterstützte Netzwerkvarianten:

- `CONNECTOR_DOCKER_NETWORK_EXTERNAL=false`: Der Connector erzeugt ein eigenes
  Docker-Netz. Seafile/RAGFlow müssen über LAN, Reverse Proxy oder
  `host.docker.internal:<port>` erreichbar sein.
- `CONNECTOR_DOCKER_NETWORK_EXTERNAL=true`: Der Connector wird an ein bereits
  existierendes Docker-Netz gehängt. Dann kann `CONNECTOR_DOCKER_NETWORK_NAME`
  z. B. auf das bestehende Seafile/RAGFlow-Netz gesetzt werden und
  `SEAFILE_BASE_URL=http://seafile`, `RAGFLOW_BASE_URL=http://ragflow:9380`
  nutzen.

## Direkter Docker-Compose-Start

Für Betreiber, die nicht über Portainer deployen, ist der einfachste direkte
Start ebenfalls die zentrale Konfigurationsdatei:

```bash
cp connector.env.example connector.env
```

Danach `connector.env` bearbeiten, die Minimalpflichtwerte ersetzen und den
Stack starten. OpenWebUI-, TLS- und Tuning-Werte nur setzen, wenn sie für den
gewählten Betriebsmodus gebraucht werden:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet

docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  up -d
```

Unter `deploy/compose` liegen zusätzlich spezialisierte Compose-Varianten. Sie
können ebenfalls mit `--env-file connector.env` gestartet werden:

| Anwendungsfall | Compose-Datei |
| --- | --- |
| Seafile/RAGFlow über Host, LAN oder Reverse Proxy | `deploy/compose/external-services.compose.yml` |
| Lokaler Smoke-Test mit Seafile-/RAGFlow-HTTPS-Mocks | zusätzlich `deploy/compose/local-mocks.compose.yml` |
| Seafile/RAGFlow im bestehenden Docker-Netz | `deploy/compose/shared-network.compose.yml` |
| Seafile/RAGFlow/OpenWebUI im gemeinsamen Docker-Netz | `deploy/compose/openwebui.compose.yml` |
| Lokaler HTTPS-Edge für Windows/WSL unter `connector.top.secret` | zusätzlich `deploy/compose/connector-top-secret.compose.yml` |

Beispiel:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/external-services.compose.yml \
  up -d
```

Für das Shared-Network- und OpenWebUI-Szenario muss
`CONNECTOR_DOCKER_NETWORK_NAME` auf ein bereits existierendes Docker-Netz
zeigen. Die OpenWebUI-Variante aktiviert das Dashboard, weil die generierten
Tools/Pipes den Connector-Proxy unter `/api/openwebui/proxy/*` erreichen
müssen.

Für den lokalen Windows-/WSL-Zugriff über `https://connector.top.secret` kann
das Overlay `deploy/compose/connector-top-secret.compose.yml` ergänzt werden.
Es aktiviert das lesende Dashboard im Controller und startet einen Nginx-Edge
mit lokalem Zertifikat aus `CONNECTOR_CERTS_HOST_DIR`. Die vollständige
Runbook-Anleitung einschließlich Windows-Hosts-Eintrag, Root-CA-Import,
Update-Test und Rollback steht in `docs/local-https-compose.md`.

## Docker Swarm

Die Swarm-Alternative liegt unter `deploy/swarm`. Sie nutzt ein eigenes
Overlay-Netz und bringt PostgreSQL/Redis als Swarm-Services mit. Seafile,
RAGFlow und optional OpenWebUI bleiben externe Systeme, die aus den
Connector-Tasks erreichbar sein müssen.

```bash
cd deploy/swarm
cp ../../connector.env.example stack.env
set -a
. ./stack.env
set +a
docker stack deploy -c docker-stack.yml seafile-ragflow-connector
```

Wichtig: `docker stack deploy` liest keine Env-Datei wie `docker compose
--env-file`. Die Variablen müssen vor dem Deploy in die Shell exportiert
werden. Außerdem veröffentlicht Swarm Dashboard-Ports über das Routing-Mesh;
`CONNECTOR_DASHBOARD_PUBLISHED_PORT` ist dort nur eine Portnummer. Wenn die
zentrale Vorlage noch `127.0.0.1:18080` enthält, muss der Wert für Swarm auf
`18080` geändert werden.

### Dashboard im Betrieb

Das Dashboard läuft im Controller-Prozess, wenn
`CONNECTOR_DASHBOARD_ENABLED=true` gesetzt ist. Standardmäßig bleibt es aus. Die
Compose-Datei enthält ein Portmapping für den Controller:

```env
CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_HOST=0.0.0.0
CONNECTOR_DASHBOARD_PORT=8080
CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080
```

Damit ist die Oberfläche auf dem Docker-Host unter `http://127.0.0.1:18080`
erreichbar. Für LAN-Zugriff kann `CONNECTOR_DASHBOARD_PUBLISHED_PORT=18080`
gesetzt werden. Soll die Oberfläche nicht erreichbar sein, bleibt
`CONNECTOR_DASHBOARD_ENABLED=false` gesetzt oder das Portmapping wird in
Portainer entfernt.

Die Oberfläche ist absichtlich unauthentifiziert und ausschließlich lesend. Sie
zeigt keine Secrets, lädt keine CDN-Assets nach und führt keine
Sync-Schreibaktionen aus. Der Dark-/Light-Modus und die Auto-Refresh-Auswahl
laufen rein im Browser. Wählbar sind aus, 5 Sekunden, 10 Sekunden und 1 Minute.
Der Health-Bereich prüft Dashboard, Datenbank, Redis, Seafile-Admin-API,
RAGFlow-API und Sync-Job-Zustand. Der Button `Audit Excel` exportiert eine
`.xlsx`-Datei mit mehreren Tabellenblättern für Übersicht, Sync-Läufe,
Änderungen, Logs, Quellen, Ziele und Diagnose. Dieser Export enthält nur
Dashboard- und Auditmetadaten, keine synchronisierten Dateiinhalte. Logs,
Änderungsereignisse und Sync-Historie werden begrenzt, damit weder Datenbank
noch API-Antworten unbegrenzt wachsen.

## Offline-Bundle

Ein produktives Release sollte enthalten:

```text
docker-compose.yml
connector.env.example
images/
  seafile-ragflow-portainer-images.tar
SHA256SUMS
```

In `connector.env` dann entweder die Image-Namen aus den importierten Tar-Dateien
verwenden oder die Images vor dem Export entsprechend taggen. Für vollständig
offline betriebene Docker-Hosts sollten die Pull-Policies auf `never` stehen:

```env
CONNECTOR_IMAGE_PULL_POLICY=never
POSTGRES_IMAGE_PULL_POLICY=never
REDIS_IMAGE_PULL_POLICY=never
```

Der Runtime-Container darf beim Start keine Pakete installieren und keine
Artefakte nachladen.

## Lokale WSL-/Docker-Prüfung

Die folgenden Kommandos prüfen schrittweise, ob Python-Logik, Dockerfile,
Container-CLI und Compose-Datei funktionieren.

### Sicherer Demo-Lifecycle

Für reproduzierbare Ende-zu-Ende-Tests gibt es drei kanonische
Beispielbibliotheken: `Connector Demo Wissen`, `Connector Demo Präsentationen`
und `Connector Demo Edge Cases`. Der Cleanup löscht nur klar benannte
Demo-Artefakte mit diesen Namen oder den historischen lokalen Präfixen
`RAG Demo Bibliothek`, `Offline Demo Bibliothek` und `Codex GIF Demo`.
Bibliotheken wie `Meine Bibliothek`, `testbibliothek` oder andere nicht
eindeutig zugeordnete Objekte werden nicht gelöscht.

Erst den Plan prüfen:

```powershell
wsl docker exec seafile-ragflow-connector-demo-connector-controller-1 connector demo-cleanup
```

Wenn die Zielobjekte eindeutig lokal und testbezogen sind:

```powershell
wsl docker exec seafile-ragflow-connector-demo-connector-controller-1 connector demo-cleanup --execute
```

Danach das reproduzierbare Testset erzeugen, in Seafile hochladen und den
Connector-Lauf einschließlich OpenWebUI-Sync ausführen:

```powershell
wsl docker exec seafile-ragflow-connector-demo-connector-controller-1 connector demo-bootstrap --execute --run-sync --wait-parse-seconds 240
```

Für eine vollständige Prüfung der Originaldokument-Links muss
`SEAFILE_FILE_URL_TEMPLATE` in der lokalen Testumgebung gesetzt sein, zum
Beispiel:

```env
SEAFILE_FILE_URL_TEMPLATE=http://localhost:18081/lib/{repo_id_quoted}/file{path_quoted}{page_fragment}
```

Das Testset enthält PDF, DOCX, TXT, Markdown, CSV, XLSX, PPTX,
PDF-Präsentationen, Tabelleninhalte, Umlaute, HTML-ähnliche Fragmente und
ähnliche Texte für Deduplizierung. Wenn der echte OpenWebUI-Browsercheck nicht
möglich ist, bleiben mindestens Proxy-Antworten, Preview-HTML,
Originaldokument-Links, PDF-Seitenanker und Quellenformat über die Unit-Tests
und API-Antworten prüfbar.

### 1. Python-Schnelltest auf Windows

```powershell
python -m compileall src tests migrations
$env:PYTHONPATH='src'; python -m unittest discover -s tests/unit
```

Erwartung: `compileall` läuft ohne Fehler und alle Unit-Tests melden `OK`.

### 2. WSL-Docker-Verfügbarkeit

```powershell
wsl docker --version
wsl docker compose version
```

Erwartung: Beide Kommandos geben eine Version aus.

### 3. Dockerfile statisch prüfen

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker build --check -f deploy/docker/Dockerfile .'
```

Erwartung: `Check complete, no warnings found.`

### 4. Image lokal bauen

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker build -t ghcr.io/adrianweidig/seafile-ragflow-connector:local-test -f deploy/docker/Dockerfile .'
```

Erwartung: Das Image wird erfolgreich gebaut. Zur Container-Laufzeit findet keine
Paketinstallation statt.

### 5. Container-CLI minimal prüfen

Für diesen Test eine lokale, nicht getrackte Env-Datei erzeugen:

```powershell
Copy-Item connector.env.example connector.env
```

Dann:

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker run --rm --env-file connector.env ghcr.io/adrianweidig/seafile-ragflow-connector:local-test check-config'
```

Erwartung: `check-config` gibt zentrale Werte aus und beendet sich mit Exit-Code 0.
Es ist keine Verbindung zu Seafile oder RAGFlow notwendig.

### 6. Compose-Syntax prüfen

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml config --quiet'
```

Erwartung: Exit-Code 0. Die Compose-Datei darf keine `env_file`-Abhängigkeit
enthalten.

### 7. GHCR-Pull prüfen

Nach einem erfolgreichen GitHub-Workflow muss das öffentliche Image ohne lokalen
Build ziehbar sein:

```powershell
wsl bash -lc 'docker pull ghcr.io/adrianweidig/seafile-ragflow-connector:latest'
```

Falls der Pull ohne Anmeldung fehlschlägt, ist meist die GHCR-Package-Sichtbarkeit
noch nicht öffentlich gesetzt oder der Publish-Workflow ist noch nicht
erfolgreich gelaufen.

### 8. Optionaler Infrastruktur-Smoke-Test

Nur ausführen, wenn `postgres:16` und `redis:7` lokal verfügbar sind oder Pulls
erlaubt sind:

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env up -d connector-postgres connector-redis'
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env ps'
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env down'
```

Erwartung: PostgreSQL und Redis starten, und der Stack lässt sich sauber stoppen.

## Recovery

- Worker-Crash: Jobs sind idempotent, Locks laufen ab und Jobs können erneut
  ausgeführt werden.
- Redis-Verlust: PostgreSQL bleibt die Recovery-Quelle für dauerhaften Job-State.
- Seafile-Ausfall: Es werden keine Delete-Entscheidungen getroffen; Download- und
  Discovery-Jobs gehen in den Retry.
- RAGFlow-Ausfall: Upload-, Delete-, Parse- und Status-Jobs werden mit Backoff
  wiederholt.

## Troubleshooting

- Keine Libraries: `SEAFILE_BASE_URL`, `SEAFILE_ADMIN_TOKEN` und Admin-Rechte für
  `/api/v2.1/admin/libraries/` prüfen.
- Template nicht gefunden: `RAGFLOW_TEMPLATE_DATASET_NAME`, `RAGFLOW_API_KEY` und
  RAGFlow-User prüfen.
- `unable to get local issuer certificate`: Root- und Intermediate-CA als PEM
  in ein Host-Verzeichnis legen, dieses per `CONNECTOR_CERTS_HOST_DIR` nach
  `/certs` mounten und `CONNECTOR_CA_BUNDLE=/certs/<datei>.pem` setzen. Wenn
  nur ein einzelner Dienst betroffen ist, stattdessen `SEAFILE_CA_BUNDLE`,
  `RAGFLOW_CA_BUNDLE` oder `OPENWEBUI_CA_BUNDLE` setzen. `*_VERIFY_SSL=false`
  nur kurzfristig zur Diagnose verwenden.
- Derselbe Zertifikatsfehler in OpenWebUI-Tool/Pipe: Der Aufruf läuft im
  OpenWebUI-Container. Dann muss `OPENWEBUI_PROXY_CA_BUNDLE` auf einen Pfad
  zeigen, der dort existiert, und `OPENWEBUI_SYNC_MODE=repair` den Tool/Pipe-
  Valve-Wert aktualisieren.
- Spezialendungen werden übersprungen: `DENY_EXTENSIONS`,
  `ALLOW_UNKNOWN_TEXT_FILES`, `TEXT_EXTENSIONS` und Klassifikationslogs prüfen.
- Dataset-Einstellungen geändert: Der Connector überschreibt bestehende
  Einstellungen nicht; neue Upload-/Parse-Operationen nutzen die aktuellen
  RAGFlow-Einstellungen.
- Dashboard bleibt leer: prüfen, ob der Controller läuft und bereits
  Sync-Läufe, Jobs oder Logs erzeugt wurden. Frische Umgebungen zeigen leere
  Zustände statt Fehler.
- Dashboard-Port belegt: `CONNECTOR_DASHBOARD_PUBLISHED_PORT` oder
  `CONNECTOR_DASHBOARD_PORT` ändern und den Controller neu starten. Ein
  Bind-Fehler wird als `dashboard.bind_failed` geloggt.
- Dashboard nicht erreichbar: `CONNECTOR_DASHBOARD_ENABLED`, Host-/Portbindung
  und das Portmapping in Portainer prüfen.
- Dashboard-Health zeigt `degraded`: Details im Health-Bereich öffnen und
  Datenbank, Redis, Seafile-Admin-Token, RAGFlow-API-Key sowie Template-Dataset
  prüfen. Einzelne externe Checks haben kurze Timeouts und blockieren die UI
  nicht dauerhaft.
- OpenWebUI-Anbindung prüfen: Die manuell testbaren Vorlagen nutzen
  `OPENWEBUI_SYNC_MODE=sync`, damit Chats, Tools und Pipes wirklich erzeugt
  werden. Für eine reine Vorprüfung `OPENWEBUI_SYNC_MODE=dry-run` setzen und
  `connector openwebui-sync-once --mode dry-run` ausführen. Danach im Dashboard
  den Tab `OpenWebUI` und die Logs nach `openwebui.*` prüfen.
- OpenWebUI-Proxy nicht erreichbar: sicherstellen, dass
  `OPENWEBUI_PROXY_INTERNAL_BASE_URL` aus dem OpenWebUI-Container erreichbar ist
  und dass `OPENWEBUI_PROXY_SHARED_SECRET` gesetzt ist.
- Tool oder Pipe fehlt in OpenWebUI: `OPENWEBUI_SYNC_MODE=repair` nutzen. Falls
  die Admin-API der Zielversion keine stabilen Writes erlaubt, zeigt das
  Dashboard den Status `manual_required`.
- Seafile-Library gelöscht: der nächste Discovery-/Sync-Lauf markiert die
  Library lokal als `deleted`, löscht das RAGFlow-Dataset und der OpenWebUI-Sync
  entfernt eigene Chat-, Tool- und Pipe-Artefakte. Seafile selbst wird dabei nie
  geschrieben.
- RAGFlow-Dataset oder Dokumente extern gelöscht: `connector sync-once` baut das
  Dataset aus dem Template neu auf und lädt die weiterhin in Seafile vorhandenen
  Dateien erneut hoch.
- Alte connector-eigene Zielartefakte bereinigen: erst
  `connector cleanup-orphans` ausführen und den Plan prüfen. Mit
  `connector cleanup-orphans --execute --run-sync --wait-parse-seconds 240`
  werden nur connector-eigene RAGFlow-Datasets mit `seafile__`-Präfix,
  connector-eigene RAGFlow-Chats sowie OpenWebUI-Tools/Functions mit
  Connector-Marker gelöscht; anschließend werden aktuelle Seafile-Libraries
  wieder synchronisiert.
- Audit-Excel leer: prüfen, ob bereits Sync-Läufe, Änderungsereignisse oder
  Logs existieren. Frische Umgebungen exportieren leere Tabellenblätter mit
  Kopfzeilen.
