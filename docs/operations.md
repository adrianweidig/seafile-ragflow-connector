# Betrieb und lokale Prüfung

Dieses Dokument bündelt Offline-Deployment, Portainer-Betrieb, Recovery,
Troubleshooting, Release und die lokale WSL-/Docker-Prüfung.

## Portainer-Deployment

Der produktive Stack liegt unter `deploy/portainer/docker-compose.yml`. Die
Beispielkonfiguration liegt unter `deploy/portainer/stack.env.example`.

1. Benötigte Images auf dem Docker-Host importieren:
   `docker load -i images/seafile-ragflow-connector_0.1.0.tar`
2. In Portainer einen neuen Stack erstellen.
3. Inhalt von `deploy/portainer/docker-compose.yml` einfügen.
4. `deploy/portainer/stack.env.example` als Vorlage für `stack.env` nutzen.
5. Stack starten und Controller-Logs prüfen.

Der Stack stellt Seafile und RAGFlow nicht bereit. Beide Systeme bleiben extern
und müssen über die konfigurierten URLs erreichbar sein.

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
wsl bash -lc 'cd /mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector && docker compose -f deploy/portainer/docker-compose.yml --env-file deploy/portainer/stack.env config --quiet'
```

Erwartung: Exit-Code 0, keine fehlenden `env_file`- oder Pfadfehler.

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

