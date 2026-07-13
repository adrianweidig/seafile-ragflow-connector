# Betrieb und lokale Prüfung

Dieses Dokument bündelt Offline-Deployment, Portainer-Betrieb, Recovery,
Troubleshooting, Release und die lokale WSL-/Docker-Prüfung.
Für die erste Administrator-Abnahme nach einem neuen Deploy steht zusätzlich
die [Admin-Erststart-Checkliste](admin-first-start-checklist.md) bereit.

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
Die Connector-Env-Blöcke in Compose, Portainer und Swarm werden im Verify-Lauf
gegen `connector.env.example` geprüft, damit neue Runtime-Variablen nicht in
einzelnen Deployment-Pfaden fehlen.

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
   `RAGFLOW_API_KEY`, `AUTHZ_API_SHARED_SECRET` und für das gewählte State-Profil
   entweder `POSTGRES_PASSWORD` oder gemeinsam `DATABASE_URL` und `REDIS_URL`.
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
Nach dem Deploy sollte die
[Admin-Erststart-Checkliste](admin-first-start-checklist.md) einmal vollständig
durchlaufen werden, bevor größere Libraries oder Endnutzer freigegeben werden.

Es gibt zwei unterstützte Netzwerkvarianten:

- `CONNECTOR_DOCKER_NETWORK_EXTERNAL=false`: Der Connector erzeugt ein eigenes
  Docker-Netz. Seafile/RAGFlow müssen über LAN, Reverse Proxy oder
  `host.docker.internal:<port>` erreichbar sein.
- `CONNECTOR_DOCKER_NETWORK_EXTERNAL=true`: Der Connector wird an ein bereits
  existierendes Docker-Netz gehängt. `CONNECTOR_DOCKER_NETWORK_NAME` hat einen
  lesbaren Default (`seafile-ragflow-connector-net`), muss in bestehenden
  Stacks aber auf das reale Seafile/RAGFlow-Netz zeigen. Dann können z. B.
  `SEAFILE_BASE_URL=http://seafile` und
  `RAGFLOW_BASE_URL=http://ragflow:9380` genutzt werden.

## Direkter Docker-Compose-Start

Für Betreiber, die nicht über Portainer deployen, ist der schnellste direkte
Start im Unternehmensnetz der Compose-Assistent:

```bash
bash scripts/configure-enterprise-compose.sh
bash output/enterprise-compose/check-config.sh
bash output/enterprise-compose/up.sh
bash output/enterprise-compose/check-live.sh
```

Er fragt HTTPS-URLs, optionale interne CA, Secrets und den OpenWebUI-Modus ab
und erzeugt eine nicht committete `connector.env` sowie Startskripte mit der
passenden Compose-Dateikombination. Unbekannte optionale Werte bleiben leer
oder bekommen robuste Defaults; der Start prüft standardmäßig nur DB/Redis,
damit Dashboard und Logs auch bei externen TLS-, Auth- oder Parserproblemen
erreichbar sind. Für Portainer schreibt der Assistent zusätzlich
`output/enterprise-compose/portainer-compose.yml` und
`output/enterprise-compose/portainer.env`; diese beiden Dateien sind das
Copy-&-Paste-Paar für den Portainer-Stack.
Die darin erzeugten `check-config.sh`, `up.sh` und `check-live.sh` entsprechen
der kurzen Abnahmefolge aus der
[Admin-Erststart-Checkliste](admin-first-start-checklist.md).

Manuell bleibt die zentrale Konfigurationsdatei der Einstieg:

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
| Unternehmensnetz mit eigener Root-CA | zusätzlich `deploy/compose/enterprise-ca.compose.yml` |
| Lokaler HTTPS-Edge für Windows/WSL unter `connector.top.secret` und `search.top.secret` | zusätzlich `deploy/compose/connector-top-secret.compose.yml` |

Beispiel:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/external-services.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/search.compose.yml \
  up -d
```

Für einen reproduzierbaren lokalen Mock-Smoke-Check ohne echte Seafile- oder
RAGFlow-Instanz kann der Verify-Runner Docker explizit nutzen:

```bash
python scripts/verify.py --skip-compose --with-mock-smoke
```

Der Check erzeugt lokale TLS-Lab-Zertifikate, startet
`deploy/compose/local-mocks.compose.yml`, baut ein lokales Connector-Test-Image
aus dem aktuellen Checkout, führt `connector check-live --json` im Controller
aus und prüft `/health/tls` mit Dashboard Basic Auth. Ohne Docker wird dieser
Check nicht im Standardlauf ausgeführt.

Für das Shared-Network- und OpenWebUI-Szenario muss das konfigurierte
`CONNECTOR_DOCKER_NETWORK_NAME` bei `docker compose up` bereits existieren.
Ohne gesetzten Wert verwenden die Compose-Dateien den Default
`seafile-ragflow-connector-net`; in Bestandsumgebungen ist meist der reale
Netzname des vorhandenen Seafile/RAGFlow/OpenWebUI-Stacks einzutragen. Die
OpenWebUI-Variante bleibt standardmäßig im Minimalmodus, solange
`OPENWEBUI_INTEGRATION_ENABLED=false` oder `OPENWEBUI_SYNC_MODE=disabled`
gesetzt ist. Für echte Tool-/Pipe-Synchronisation müssen die OpenWebUI-Keys
und Proxy-Werte ergänzt werden.

Für den lokalen Windows-/WSL-Zugriff über `https://connector.top.secret` und
`https://search.top.secret/search` kann das Overlay
`deploy/compose/connector-top-secret.compose.yml` ergänzt werden. Es aktiviert
das Dashboard im Controller, hält den Search-Service erreichbar und startet
einen Nginx-Edge mit lokalen Zertifikaten aus `CONNECTOR_CERTS_HOST_DIR`. Die vollständige
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

## Datenbank-Upgrade auf Revision 0006

Revision `0006_sync_consistency_state` ergänzt aufbauend auf der atomischen
Job-Deduplizierung aus `0005` commit-gepinnte Snapshots und Cursor, Sync-Runs,
Repo-Leases mit Fence-Token, Dokumentversionen und die Cleanup-Outbox. Vor einem
produktiven Upgrade zuerst ein PostgreSQL-Backup erstellen. Danach Controller
und Reconciler als Job-Produzenten stoppen und die Worker vorhandene Jobs
abarbeiten lassen:

```bash
docker compose --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  stop connector-controller connector-reconciler

docker compose --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  exec -T connector-postgres sh -s <<'SH'
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At <<'SQL'
SELECT count(*)
FROM sync_jobs
WHERE status IN ('queued', 'retrying', 'running');
SQL
SH
```

Erst wenn die Abfrage `0` liefert, auch den Worker stoppen, das neue Image
bereitstellen und `connector init-db` beziehungsweise den normalen Stackstart
ausführen. Bestehende Jobs erhalten beim Upgrade eindeutige
`legacy:<id>`-Schlüssel und werden nicht nachträglich zusammengeführt. Neue
Jobs werden anschließend atomar über ihren semantischen Schlüssel
dedupliziert. Snapshot- und Versionszustand wird durch neue Läufe schrittweise
gefüllt; bestehende Datei-/Dokumentbindungen bleiben erhalten. Controller,
Worker und Reconciler müssen gemeinsam auf denselben Image-Stand aktualisiert
werden. Ein Rollback erfolgt bevorzugt durch Wiederherstellung des zuvor
erstellten Backups.

### Dashboard im Betrieb

Das Dashboard läuft im Controller-Prozess, wenn
`CONNECTOR_DASHBOARD_ENABLED=true` gesetzt ist. Standardmäßig bleibt es aus. Die
Compose-Datei enthält ein Portmapping für den Controller:

```env
CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_HOST=0.0.0.0
CONNECTOR_DASHBOARD_PORT=8080
CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080
CONNECTOR_DASHBOARD_AUTH_USERNAME=admin
CONNECTOR_DASHBOARD_AUTH_PASSWORD=change-me-dashboard-password
```

Damit ist die Oberfläche auf dem Docker-Host unter `http://127.0.0.1:18080`
erreichbar. Für LAN-Zugriff kann `CONNECTOR_DASHBOARD_PUBLISHED_PORT=18080`
gesetzt werden. Soll die Oberfläche nicht erreichbar sein, bleibt
`CONNECTOR_DASHBOARD_ENABLED=false` gesetzt oder das Portmapping wird in
Portainer entfernt.

Die Oberfläche schützt UI, Status-API und Workflow-Steuerung per HTTP Basic
Auth, sobald `CONNECTOR_DASHBOARD_AUTH_USERNAME` und
`CONNECTOR_DASHBOARD_AUTH_PASSWORD` gesetzt sind. Sie zeigt keine Secrets, lädt
keine CDN-Assets nach und löscht keine Seafile-Bibliotheken. Im Tab
**Prüfablauf** können die mit dem aktuellen Seafile-API-Key sichtbaren
Bibliotheken ausgewählt und für RAGFlow-Dataset-/Dokument-Sync sowie optionalen
OpenWebUI-Chat-/Tool-/Pipe-Sync gestartet werden. Im OpenWebUI-Tab können
connector-eigene Pipes, RAGFlow-Chats und RAGFlow-Datasets gezielt entfernt
werden, damit ein Folgesync sie sauber neu anlegen kann. Der Dark-/Light-Modus
und die Auto-Refresh-Auswahl laufen rein im Browser. Wählbar sind aus, 5
Sekunden, 10 Sekunden und 1 Minute.
Der Health-Bereich prüft Dashboard, Datenbank, Redis, Seafile-Admin-API,
RAGFlow-API und Sync-Job-Zustand. Für Seafile, RAGFlow und OpenWebUI zeigt er
zusätzlich den aktuell gewählten Transport (`https` oder `http`), die effektive
Endpoint-URL und ob HTTP nur als Fallback nach einem HTTPS-Fehler genutzt wird.
Der Button `Audit Excel` exportiert eine
`.xlsx`-Datei mit mehreren Tabellenblättern für Übersicht, Sync-Läufe,
Änderungen, Logs, Quellen, Ziele und Diagnose. Dieser Export enthält nur
Dashboard- und Auditmetadaten, keine synchronisierten Dateiinhalte. Logs,
Änderungsereignisse und Sync-Historie werden begrenzt, damit weder Datenbank
noch API-Antworten unbegrenzt wachsen.

Für Orchestratoren sind die Proben getrennt: `/livez` bestätigt nur den
laufenden HTTP-Prozess, `/readyz` prüft mit kurzen Timeouts Datenbank, Redis,
Seafile, RAGFlow und die Aktualität vorhandener Authz-Snapshots. Das
Readiness-Ergebnis wird fünf Sekunden gecacht. `/metrics` liefert das echte
Prometheus-Textformat; `/api/metrics` bleibt die Dashboard-JSON-Ansicht.
Metriklabels enthalten keine Repository-IDs, Dateipfade oder Nutzer-E-Mails.
Die Docker-/Swarm-Healthchecks des Controllers verwenden `/livez`, damit ein
vorübergehender Ausfall externer Dienste Dashboard und Diagnosezugriff nicht
als Prozessausfall markiert. Deployment-Gates, die echte Einsatzbereitschaft
verlangen, prüfen zusätzlich `/readyz`.

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

Der GitHub-Actions-Workflow `release-artifact` erzeugt bei Pushes auf `master`
oder `main` ein Repository-ZIP, `release-notes.md` und `SHA256SUMS` als
Actions-Artefakt. Dieses Artefakt ist der reproduzierbare Code-Stand für ein
Offline-Bundle; Docker-Images und deren Export bleiben separate
Maintainer-Schritte.

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

Für eine vollständige Prüfung der Originaldokument-Links reicht normalerweise
eine aus dem Browser erreichbare `SEAFILE_PUBLIC_BASE_URL`. Wenn sie leer ist,
nutzt der Connector `SEAFILE_BASE_URL`:

```env
SEAFILE_PUBLIC_BASE_URL=http://localhost:18081
```

Nur bei abweichenden Reverse-Proxy- oder Seafile-Webrouten ist ein expliziter
Template-Override nötig:

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
python -m compileall src tests migrations scripts
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
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker build --check -f deploy/docker/Dockerfile .'
```

Erwartung: `Check complete, no warnings found.`

### 4. Image lokal bauen

```powershell
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker build -t ghcr.io/adrianweidig/seafile-ragflow-connector:local-test -f deploy/docker/Dockerfile .'
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
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker run --rm --env-file connector.env ghcr.io/adrianweidig/seafile-ragflow-connector:local-test check-config'
```

Erwartung: `check-config` gibt zentrale Werte aus und beendet sich mit Exit-Code 0.
Es ist keine Verbindung zu Seafile oder RAGFlow notwendig.

### 6. Compose-Syntax prüfen

```powershell
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml config --quiet'
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
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env up -d connector-postgres connector-redis'
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env ps'
wsl bash -lc 'cd /mnt/e/Codex_Workspace/repos/seafile-ragflow-connector && docker compose -f deploy/portainer/docker-compose.yml --env-file connector.env down'
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
- Automationen und Skripte: `connector check-config`, `connector doctor`,
  `connector check-live`, `connector sync-once`, `connector library status`,
  `connector jobs list`, `connector cleanup list`, `connector cleanup-orphans` und
  `connector openwebui-sync-once` unterstützen `--json`. Ohne dieses Flag bleibt
  die bisherige menschenlesbare Ausgabe erhalten.
- `connector library sync --wait` und `connector library reconcile --execute
  --wait` liefern bei Timeout, Abbruch oder endgültig fehlgeschlagenem Job
  Exitcode `1`; Konfigurationsfehler liefern Exitcode `2`. Dadurch können
  Automationen nicht mit einem falsch-grünen Ergebnis weiterlaufen.
- Template nicht gefunden: `RAGFLOW_TEMPLATE_AUTO_CREATE=true` nutzen oder
  `RAGFLOW_TEMPLATE_DATASET_NAME`, `RAGFLOW_API_KEY` und RAGFlow-User prüfen.
- `unable to get local issuer certificate`: Root- und Intermediate-CA als PEM
  in ein Host-Verzeichnis legen, dieses per `CONNECTOR_CERTS_HOST_DIR` nach
  `/certs` mounten und `CONNECTOR_CA_BUNDLE=/certs/<datei>.pem` setzen. Wenn
  nur ein einzelner Dienst betroffen ist, stattdessen `SEAFILE_CA_BUNDLE`,
  `RAGFLOW_CA_BUNDLE` oder `OPENWEBUI_CA_BUNDLE` setzen. `*_VERIFY_SSL=false`
  nur kurzfristig zur Diagnose verwenden.
- RAGFlow meldet Parser-/Offline-Ressourcenfehler, z. B. fehlende NLP-/NLTK-
  Daten: Connector und Dashboard bleiben mit `CONNECTOR_STARTUP_CHECK=infra`
  erreichbar. Die Ursache liegt im bestehenden RAGFlow-Server; nach Korrektur
  können Jobs erneut laufen oder per `connector sync-once` angestoßen werden.
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
- Sync-Jobs zeigen tote Jobs: Wenn die Systemchecks ansonsten gesund sind,
  bedeutet das Wartungsbedarf aus alten fehlgeschlagenen Jobs, nicht zwingend
  einen aktuell defekten Connector. Im Health-Eintrag `Sync-Jobs` können tote
  Jobs über `Tote Jobs bereinigen` auf `cancelled` gesetzt werden; die
  Audit-Historie bleibt erhalten.
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
  werden nur connector-eigene RAGFlow-Datasets mit `RAG_`- oder Legacy-`seafile__`-Präfix,
  connector-eigene RAGFlow-Chats sowie OpenWebUI-Tools/Functions mit
  Connector-Marker gelöscht; anschließend werden aktuelle Seafile-Libraries
  wieder synchronisiert.
- Audit-Excel leer: prüfen, ob bereits Sync-Läufe, Änderungsereignisse oder
  Logs existieren. Frische Umgebungen exportieren leere Tabellenblätter mit
  Kopfzeilen.
