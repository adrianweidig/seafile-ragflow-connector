# Betrieb und lokale Prüfung

Dieses Dokument bündelt Offline-Deployment, Portainer-Betrieb, Recovery,
Troubleshooting, Release und die lokale WSL-/Docker-Prüfung.

## Portainer-Deployment

Der produktive Stack liegt unter `deploy/portainer/docker-compose.yml`. Die
importierbare Beispielkonfiguration liegt unter
`deploy/portainer/stack.env.example`.

Die Compose-Datei referenziert keine lokale `env_file`. In Portainer reicht es,
die Compose-Datei einzufügen oder das Repo als Git-Stack zu nutzen und die Werte
aus `stack.env.example` im Bereich `Environment variables` zu importieren.

1. Benötigte Images auf dem Docker-Host importieren:
   `docker load -i images/seafile-ragflow-connector_0.1.0.tar`
2. In Portainer einen neuen Stack erstellen.
3. Inhalt von `deploy/portainer/docker-compose.yml` einfügen.
4. `deploy/portainer/stack.env.example` in Portainer importieren.
5. Alle `change-me` Werte ersetzen.
6. `SEAFILE_BASE_URL` und `RAGFLOW_BASE_URL` auf die aus dem
   Connector-Container erreichbaren URLs setzen.
7. Stack starten und die Logs von `connector-controller`, `connector-worker` und
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
stack.env.example
images/
  seafile-ragflow-connector_0.1.0.tar
  postgres_16.tar
  redis_7.tar
SHA256SUMS
```

Der Runtime-Container darf beim Start keine Pakete installieren und keine
Artefakte nachladen.

## Lokale WSL-/Docker-Prüfung

Die folgenden Kommandos prüfen schrittweise, ob Python-Logik, Dockerfile,
Container-CLI und Compose-Datei funktionieren.

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
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker build -t seafile-ragflow-connector:0.1.0 -f deploy/docker/Dockerfile .'
```

Erwartung: Das Image wird erfolgreich gebaut. Zur Container-Laufzeit findet keine
Paketinstallation statt.

### 5. Container-CLI minimal prüfen

Für diesen Test eine lokale, nicht getrackte Env-Datei erzeugen:

```powershell
Copy-Item deploy\portainer\stack.env.example deploy\portainer\stack.env
```

Dann:

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker run --rm --env-file deploy/portainer/stack.env seafile-ragflow-connector:0.1.0 check-config'
```

Erwartung: `check-config` gibt zentrale Werte aus und beendet sich mit Exit-Code 0.
Es ist keine Verbindung zu Seafile oder RAGFlow notwendig.

### 6. Compose-Syntax prüfen

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose --env-file deploy/portainer/stack.env -f deploy/portainer/docker-compose.yml config --quiet'
```

Erwartung: Exit-Code 0. Die Compose-Datei darf keine `env_file`-Abhängigkeit
enthalten.

### 7. Optionaler Infrastruktur-Smoke-Test

Nur ausführen, wenn `postgres:16` und `redis:7` lokal verfügbar sind oder Pulls
erlaubt sind:

```powershell
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file deploy/portainer/stack.env up -d connector-postgres connector-redis'
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file deploy/portainer/stack.env ps'
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file deploy/portainer/stack.env down'
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
- Audit-Excel leer: prüfen, ob bereits Sync-Läufe, Änderungsereignisse oder
  Logs existieren. Frische Umgebungen exportieren leere Tabellenblätter mit
  Kopfzeilen.
