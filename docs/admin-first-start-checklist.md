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
| `POSTGRES_PASSWORD` oder gemeinsam `DATABASE_URL` und `REDIS_URL` | Gebündelter beziehungsweise externer Connector-State |

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

Für die interaktive Administrationsoberfläche müssen
`CONNECTOR_DASHBOARD_ENABLED=true` und
`CONNECTOR_DASHBOARD_CONTROL_ENABLED=true` sowie nicht leere Werte für
`CONNECTOR_DASHBOARD_AUTH_USERNAME` und
`CONNECTOR_DASHBOARD_AUTH_PASSWORD` gesetzt sein. Soll das Dashboard nur lesen,
bleibt der Control-Schalter `false`. Für lokalen Zugriff ist
`CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080` der sichere Default; für
LAN-Zugriff muss der Port bewusst breiter veröffentlicht und durch Netzwerk-
oder Reverse-Proxy-Regeln sowie HTTPS geschützt werden. In Produktion muss das
Passwort zufällig erzeugt sein; bekannte Beispielpasswörter werden abgewiesen.

## Isolierten Erststart vorbereiten

Vor dem allerersten Stack-Start in der Betreiber-Env setzen:

```env
CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_CONTROL_ENABLED=true
CONNECTOR_AUTOMATION_INITIAL_STATE=stopped
```

Dieser Wert wird ausschließlich beim erstmaligen Erzeugen des globalen
Steuerzustands angewendet. `stopped` legt ihn atomar als deaktiviert und
queue-pausiert an, bevor Controller-Scheduler oder Worker Arbeit aufnehmen
können. Ein bereits persistierter Operatorzustand wird niemals überschrieben.
Der rückwärtskompatible Default `running` erlaubt dagegen sofortige automatische
Zyklen und eignet sich nicht für einen garantiert isolierten Erststart. Bei
Upgrades vorhandene Jobs deshalb vor dem Versionswechsel kontrolliert leeren;
der Initialwert storniert keine Altjobs.
Die oben beschriebenen echten, nicht leeren Basic-Auth-Werte müssen ebenfalls
vor dem Start gesetzt sein; andernfalls fehlt der sichere UI-Aktivierungspfad.

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

## Unmittelbar nach dem Start konfigurieren

Im Controller-Dashboard muss der globale Zustand jetzt `stopped` sein. Dann
**Bibliotheken prüfen** ausführen, alle Nicht-Testbibliotheken deaktivieren oder
pausieren und genau eine kleine Testbibliothek aktiv lassen. Global
**Fortsetzen** hebt ausschließlich die Queue-Pause auf; die Automatik bleibt
`deactivated`, sodass der ausgewählte manuelle Lauf isoliert gestartet werden
kann. Global **Start** erst wählen, wenn automatische Planung für alle
verbleibenden ausführbaren Bibliotheken erwünscht ist. Ist der erste sichtbare
Zustand nicht `stopped`, wurde der Initialwert zu spät gesetzt oder es existiert
bereits ein persistierter Zustand; dann zuerst kontrolliert stoppen und
vorhandene Jobs klären, bevor Isolation angenommen wird.

## Erfolgskriterien nach dem Start

Zuerst sollte die Infrastruktur diese Punkte erfüllen:

- Beim Profil `bundled-state` laufen `connector-postgres` und
  `connector-redis`; bei `external-state` sind beide absichtlich nicht
  gestartet und die externen URLs sind erreichbar.
- `connector-controller`, `connector-worker` und `connector-reconciler` laufen;
  im Standardprofil zusätzlich `connector-search`, in Core-only bewusst nicht.
- Die Logs von Controller, Worker und Reconciler enthalten keine fehlenden
  Pflichtvariablen und keine dauerhaften Authentifizierungsfehler.
- `bash output/enterprise-compose/check-live.sh` oder der direkte
  `docker compose run --rm connector-controller connector check-live` beendet
  sich erfolgreich.
- Das Dashboard ist erreichbar, wenn es aktiviert wurde.
- Die Browserroute endet am Dashboard des `connector-controller`, nicht an
  einem separaten `connector dashboard` Prozess. Nur die Controller-Variante
  zeigt den interaktiven Bereich **Administration**.
- `/api/health` meldet Dashboard, Datenbank, Redis, Seafile und RAGFlow als
  `ok` oder zeigt einen konkreten, behebbaren externen Fehler.
- Für jede danach bewusst freigegebene Seafile-Library entsteht in RAGFlow ein
  Dataset aus dem Template oder das Template wird bei aktivierter
  Auto-Create-Option erzeugt.
- Nach dem explizit gestarteten Lauf der Testbibliothek werden erste Dateien
  hochgeladen und Parse-Statuswerte sind im Dashboard oder in RAGFlow sichtbar.
- Die Bibliothekstabelle zeigt Operatorstatus und Parsing-Zähler
  `tracked`/`done`/`pending`/`failed`; ein gestarteter Lauf zeigt Phase und
  Fortschritt dauerhaft über einen Browser-Refresh hinweg.
- Bei aktivierter OpenWebUI-Anbindung erscheinen Chat, Tool, Pipe oder Custom
  Model erst nach einem echten Sync- oder Repair-Lauf.

## Nutzerfreigabe

Vor der Freigabe für Endnutzer sollten zusätzlich diese Punkte stimmen:

- Das Dashboard ist nur für Administratoren erreichbar und per Basic Auth oder
  vorgelagertem Zugriffsschutz geschützt.
- Schreibende Requests akzeptieren nur JSON mit
  `X-Connector-Admin-Action: 1`; der Browser setzt den Header automatisch.
  Globaler Stop sowie Stop/Cancel eines Laufs verlangen eine sichtbare
  `STOP`-Bestätigung.
- Die sichtbare Sprache passt zur Zielgruppe. Deutsch ist Default; Englisch und
  weitere Dashboard-Sprachen können über die UI oder `CONNECTOR_LANGUAGE`
  genutzt werden.
- OpenWebUI zeigt sprechende Custom-Model-Namen und Quellenlinks, wenn die
  Anbindung aktiviert ist.
- Der Audit-Excel-Export lädt nur Metadaten und keine synchronisierten
  Dateiinhalte herunter.
- Ein kleiner Testdatensatz wurde erfolgreich synchronisiert, bevor große
  Libraries freigegeben werden.
- An einer kleinen Testbibliothek wurden Delta, Pause, Fortsetzen und Stop/Retry
  geprüft. Stop/Pause betreffen Connector-Arbeit, niemals Portainer-Container.

## Wenn etwas nicht grün wird

| Symptom | Erste Prüfung |
| --- | --- |
| `docker` oder `docker compose` fehlt | Docker-Installation, PATH und bei Windows/WSL den verwendeten Kontext prüfen |
| Compose-Config schlägt fehl | `connector.env` auf fehlende Pflichtwerte, Tippfehler und unzulässige Ports prüfen |
| Seafile oder RAGFlow nicht erreichbar | Interne Container-URL gegen Host-/Browser-URL abgleichen |
| Zertifikatsfehler | CA-Bundle per `CONNECTOR_CA_BUNDLE`, `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE` oder `OPENWEBUI_CA_BUNDLE` setzen |
| Dashboard nicht erreichbar | `CONNECTOR_DASHBOARD_ENABLED`, Portmapping, Bind-Adresse und Portkonflikte prüfen |
| Administration fehlt oder Mutation wird abgewiesen | Controller-Route, `CONNECTOR_DASHBOARD_CONTROL_ENABLED`, vollständige Basic Auth, HTTPS-Proxy sowie JSON-/Admin-Header prüfen |
| Dashboard-Health ist `degraded` | Detailzeile im Health-Bereich öffnen und zuerst DB, Redis, Token und Ziel-URLs korrigieren |
| Keine Datasets entstehen | Seafile-Admin-Rechte, RAGFlow-Template und `RAGFLOW_TEMPLATE_AUTO_CREATE` prüfen |
| OpenWebUI-Artefakte fehlen | `OPENWEBUI_INTEGRATION_ENABLED`, `OPENWEBUI_SYNC_MODE` und Proxy-Erreichbarkeit aus dem OpenWebUI-Container prüfen |

`*_VERIFY_SSL=false` ist nur eine kurzfristige Diagnosehilfe. Für produktive
Umgebungen sollte die Zertifikatskette stattdessen über CA-Bundles repariert
werden.

## CLI-Fallback

Den Delta-Lauf der isolierten Testbibliothek über **Auswahl starten** auslösen
und Phase, Datei- und Parsing-Zähler bis zum terminalen Zustand verfolgen.
Pause/Fortsetzen und Stop/Retry nur an diesem entbehrlichen Testlauf prüfen.
Globaler Stop lässt Controller und Dashboard laufen; Containersteuerung bleibt
in Portainer beziehungsweise Docker Compose.

Falls die Adminsteuerung bewusst deaktiviert bleibt, steht als CLI-Fallback zur
Verfügung:

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

Danach die persistente Änderungs-/Audit-Historie des Dashboards,
RAGFlow-Datasets, OpenWebUI-Artefakte und Audit-Export prüfen. Erst wenn dieser
Lauf stabil ist, größere Bibliotheken und automatische Zeitpläne über die
Administrationsoberfläche freigeben.

Der Standard für periodische Controller-, Reconciler-, Template-Refresh- und
OpenWebUI-Sync-Läufe beträgt 30 Minuten (`1800` Sekunden). Die Intervalle sind
über `DISCOVERY_INTERVAL_SECONDS`, `DELTA_SYNC_INTERVAL_SECONDS`,
`RECONCILE_INTERVAL_SECONDS`, `RAGFLOW_TEMPLATE_REFRESH_SECONDS` und
`OPENWEBUI_SYNC_INTERVAL_SECONDS` konfigurierbar; Werte unter 60 Sekunden
werden abgelehnt. Manuelle Checks und Syncs bleiben unabhängig davon möglich.
