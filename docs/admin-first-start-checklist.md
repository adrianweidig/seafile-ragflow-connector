# Admin-Erststart-Checkliste

🌐 Sprachen: **Deutsch** | [English](en/admin-first-start-checklist.md)

Diese Checkliste bündelt die ersten Schritte nach einer neuen Installation. Sie
ersetzt nicht die Detaildokumentation, sondern gibt Administratoren eine kurze
Abnahmefolge für Portainer, Docker Compose und erste Nutzerfreigaben.

## Vor dem Deploy

- Docker Compose Plugin oder Portainer ist auf dem Zielhost verfügbar.
- Seafile und RAGFlow laufen bereits außerhalb des Connector-Stacks.
- Die aus dem Connector-Container erreichbaren URLs sind bekannt. In einem
  gemeinsamen Docker-Netz können das interne Namen wie `http://seafile` und
  `http://ragflow:9380` sein; über LAN oder Reverse Proxy sind es die dort
  erreichbaren URLs.
- Seafile-Admin-Token, Seafile-Download-Token, RAGFlow-API-Key und bei
  aktivierter OpenWebUI-Anbindung ein OpenWebUI-Admin-Key liegen bereit.
- Die Netzwerkvariante ist entschieden:
  `CONNECTOR_DOCKER_NETWORK_EXTERNAL=false` für ein eigenes Connector-Netz oder
  `CONNECTOR_DOCKER_NETWORK_EXTERNAL=true` für ein vorhandenes gemeinsames
  Docker-Netz.
- Interne Root- oder Intermediate-CAs liegen als PEM-Dateien auf dem Docker-Host
  bereit, falls Seafile, RAGFlow oder OpenWebUI private Zertifikatsketten
  nutzen.
- Echte Secrets bleiben außerhalb des Git-Arbeitsbaums. `connector.env`,
  `stack.env`, Portainer-Exporte und TLS-Lab-Ausgaben werden nicht committet.

## Konfiguration vorbereiten

Für direkte Docker-Compose-Installationen ist der Assistent der schnellste Weg:

```bash
bash scripts/configure-enterprise-compose.sh
bash output/enterprise-compose/check-config.sh
```

Er erzeugt eine lokale `connector.env`, die passende Compose-Kombination,
Startskripte und zusätzlich `output/enterprise-compose/portainer-compose.yml`
mit `output/enterprise-compose/portainer.env` für Portainer.

Manuell reicht als Einstieg:

```bash
cp connector.env.example connector.env
```

Danach mindestens diese Werte setzen:

| Variable | Zweck |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile-URL aus Sicht des Connector-Containers |
| `SEAFILE_ADMIN_TOKEN` | Admin-API-Token für Library-Discovery |
| `SEAFILE_SYNC_USER_TOKEN` | API-Token für Datei-Downloads |
| `RAGFLOW_BASE_URL` | RAGFlow-API-URL aus Sicht des Connector-Containers |
| `RAGFLOW_API_KEY` | API-Key des RAGFlow-Zielusers |
| `POSTGRES_PASSWORD` oder `DATABASE_URL` | Datenbankzugang für den Connector-State |

OpenWebUI-, TLS-, Tuning- und Dashboard-Werte erst ergänzen, wenn sie für den
gewählten Betriebsmodus wirklich gebraucht werden.

## Vor dem ersten Start prüfen

Für die generierte Compose-Konfiguration:

```bash
bash output/enterprise-compose/check-config.sh
```

Für die zentrale Portainer-/Compose-Datei:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  config --quiet
```

Wenn kein generiertes `check-live.sh` genutzt wird, läuft der Live-Check im
Compose-Stack explizit im Controller-Container:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  run --rm connector-controller connector check-live
```

Wenn `CONNECTOR_DASHBOARD_ENABLED=true` gesetzt wird, sollte auch ein
Dashboard-Passwort gesetzt sein. Für lokalen Zugriff ist
`CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080` der sichere Default; für
LAN-Zugriff muss der Port bewusst breiter veröffentlicht und durch Netzwerk-
oder Reverse-Proxy-Regeln geschützt werden.

## Starten

Direkt mit den generierten Skripten:

```bash
bash output/enterprise-compose/up.sh
```

Oder manuell:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  up -d
```

In Portainer wird `deploy/portainer/docker-compose.yml` oder die generierte
`portainer-compose.yml` als Stack-Inhalt genutzt; die Werte aus
`connector.env.example` beziehungsweise `portainer.env` kommen in den
Environment-Bereich des Stacks.

## Erfolgskriterien nach dem Start

Nach einigen Minuten sollte der Stack diese Punkte erfüllen:

- `connector-postgres`, `connector-redis`, `connector-controller`,
  `connector-worker` und `connector-reconciler` laufen.
- Die Logs von Controller, Worker und Reconciler enthalten keine fehlenden
  Pflichtvariablen und keine dauerhaften Authentifizierungsfehler.
- `bash output/enterprise-compose/check-live.sh` oder der direkte
  `docker compose run --rm connector-controller connector check-live` beendet
  sich erfolgreich.
- Das Dashboard ist erreichbar, wenn es aktiviert wurde.
- `/api/health` meldet Dashboard, Datenbank, Redis, Seafile und RAGFlow als
  `ok` oder zeigt einen konkreten, behebbaren externen Fehler.
- In RAGFlow entsteht für jede relevante Seafile-Library ein Dataset aus dem
  Template oder das Template wird bei aktivierter Auto-Create-Option erzeugt.
- Erste Dateien werden hochgeladen und Parse-Statuswerte sind im Dashboard oder
  in RAGFlow sichtbar.
- Bei aktivierter OpenWebUI-Anbindung erscheinen Chat, Tool, Pipe oder Custom
  Model erst nach einem echten Sync- oder Repair-Lauf.

## Nutzerfreigabe

Vor der Freigabe für Endnutzer sollten zusätzlich diese Punkte stimmen:

- Das Dashboard ist nur für Administratoren erreichbar und per Basic Auth oder
  vorgelagertem Zugriffsschutz geschützt.
- Die sichtbare Sprache passt zur Zielgruppe. Deutsch ist Default; Englisch und
  weitere Dashboard-Sprachen können über die UI oder `CONNECTOR_LANGUAGE`
  genutzt werden.
- OpenWebUI zeigt sprechende Custom-Model-Namen und Quellenlinks, wenn die
  Anbindung aktiviert ist.
- Der Audit-Excel-Export lädt nur Metadaten und keine synchronisierten
  Dateiinhalte herunter.
- Ein kleiner Testdatensatz wurde erfolgreich synchronisiert, bevor große
  Libraries freigegeben werden.

## Wenn etwas nicht grün wird

| Symptom | Erste Prüfung |
| --- | --- |
| `docker` oder `docker compose` fehlt | Docker-Installation, PATH und bei Windows/WSL den verwendeten Kontext prüfen |
| Compose-Config schlägt fehl | `connector.env` auf fehlende Pflichtwerte, Tippfehler und unzulässige Ports prüfen |
| Seafile oder RAGFlow nicht erreichbar | Interne Container-URL gegen Host-/Browser-URL abgleichen |
| Zertifikatsfehler | CA-Bundle per `CONNECTOR_CA_BUNDLE`, `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE` oder `OPENWEBUI_CA_BUNDLE` setzen |
| Dashboard nicht erreichbar | `CONNECTOR_DASHBOARD_ENABLED`, Portmapping, Bind-Adresse und Portkonflikte prüfen |
| Dashboard-Health ist `degraded` | Detailzeile im Health-Bereich öffnen und zuerst DB, Redis, Token und Ziel-URLs korrigieren |
| Keine Datasets entstehen | Seafile-Admin-Rechte, RAGFlow-Template und `RAGFLOW_TEMPLATE_AUTO_CREATE` prüfen |
| OpenWebUI-Artefakte fehlen | `OPENWEBUI_INTEGRATION_ENABLED`, `OPENWEBUI_SYNC_MODE` und Proxy-Erreichbarkeit aus dem OpenWebUI-Container prüfen |

`*_VERIFY_SSL=false` ist nur eine kurzfristige Diagnosehilfe. Für produktive
Umgebungen sollte die Zertifikatskette stattdessen über CA-Bundles repariert
werden.

## Danach

Für den ersten produktionsnahen Lauf zuerst klein beginnen:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/portainer/docker-compose.yml \
  run --rm connector-controller connector sync-once
```

Bei einem generierten Enterprise-Compose-Setup dieselben Compose-Dateien wie in
`output/enterprise-compose/up.sh` verwenden. In Portainer wird derselbe Befehl
als einmaliger Controller-Task oder über eine Shell im Controller-Container
ausgeführt.

Danach Dashboard, RAGFlow-Datasets, OpenWebUI-Artefakte und Audit-Export
prüfen. Erst wenn dieser Lauf stabil ist, größere Libraries oder automatische
Zeitpläne freigeben.

Der Standard für periodische Controller-, Reconciler-, Template-Refresh- und
OpenWebUI-Sync-Läufe beträgt 30 Minuten (`1800` Sekunden). Die Intervalle sind
über `DISCOVERY_INTERVAL_SECONDS`, `DELTA_SYNC_INTERVAL_SECONDS`,
`RECONCILE_INTERVAL_SECONDS`, `RAGFLOW_TEMPLATE_REFRESH_SECONDS` und
`OPENWEBUI_SYNC_INTERVAL_SECONDS` konfigurierbar; Werte unter 60 Sekunden
werden abgelehnt. Manuelle Checks und Syncs bleiben unabhängig davon möglich.
