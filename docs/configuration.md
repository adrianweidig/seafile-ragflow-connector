# Konfiguration

Die Konfiguration erfolgt über Environment-Variablen. Secrets müssen über
Portainer-Environment-Management oder Docker Secrets bereitgestellt werden und
dürfen nicht committed werden.

## Datei-Policy

- `ALLOW_EXTENSIONS`: optionale Allowlist. Leer bedeutet, dass die Endung keine
  harte Zulassungsvoraussetzung ist.
- `DENY_EXTENSIONS`: Endungen, die immer übersprungen werden.
- `TEXT_EXTENSIONS`: Endungen, die als Text-/Code-Hinweise gelten.
- `ALLOW_UNKNOWN_TEXT_FILES`: unbekannte Endungen akzeptieren, wenn der Inhalt Text ist.
- `DEFAULT_TEXT_INGESTION_STRATEGY`: Standard ist `text_projection`.

## Dataset-Einstellungen

- `DATASET_SETTINGS_SOURCE=ragflow_current`: aktuelle Einstellungen des
  Ziel-Datasets verwenden.
- `RAGFLOW_REFRESH_DATASET_SETTINGS=true`: vor Upload-/Parse-Batches aktualisieren.
- `REPARSE_ON_DATASET_SETTINGS_CHANGE=false`: bestehende Dokumente nach einer
  Admin-Änderung nicht stillschweigend vollständig neu verarbeiten.

## Dashboard

Das Dashboard ist eine rein lesende Weboberfläche für Status, Sync-Historie,
Änderungen, Logs, Quellen/Ziele und technische Diagnose. Da das Projekt vorher
keine Weboberfläche hatte, ist sie standardmäßig deaktiviert. Das UI wird
vollständig aus dem Connector ausgeliefert und lädt keine CDN- oder
Internet-Assets nach. Der Theme-Wechsel zwischen Dark und Light wird lokal im
Browser gespeichert. Der Auto-Refresh ist im Dashboard zwischen aus, 5
Sekunden, 10 Sekunden und 1 Minute wählbar und wird ebenfalls lokal im Browser
gespeichert.

```env
CONNECTOR_DASHBOARD_ENABLED=false
CONNECTOR_DASHBOARD_HOST=0.0.0.0
CONNECTOR_DASHBOARD_PORT=8080
CONNECTOR_DASHBOARD_MAX_LOG_ENTRIES=5000
CONNECTOR_DASHBOARD_MAX_EVENT_ENTRIES=10000
CONNECTOR_DASHBOARD_MAX_SYNC_RUNS=1000
CONNECTOR_DASHBOARD_LOG_PAGE_SIZE=100
CONNECTOR_DASHBOARD_MAX_FIELD_LENGTH=4000
```

- `CONNECTOR_DASHBOARD_ENABLED`: aktiviert den HTTP-Server im Controller oder
  im expliziten `connector dashboard` Prozess.
- `CONNECTOR_DASHBOARD_HOST` und `CONNECTOR_DASHBOARD_PORT`: Bind-Adresse im
  Container oder lokalen Prozess.
- `CONNECTOR_DASHBOARD_MAX_LOG_ENTRIES`: harte Obergrenze persistierter
  Dashboard-Logs.
- `CONNECTOR_DASHBOARD_MAX_EVENT_ENTRIES`: harte Obergrenze persistierter
  Änderungsereignisse.
- `CONNECTOR_DASHBOARD_MAX_SYNC_RUNS`: harte Obergrenze gespeicherter
  Synchronisationsläufe.
- `CONNECTOR_DASHBOARD_LOG_PAGE_SIZE`: Default-Seitengröße für Log-,
  Änderungs- und History-Endpunkte. API-Antworten werden zusätzlich hart
  begrenzt.
- `CONNECTOR_DASHBOARD_MAX_FIELD_LENGTH`: maximale Länge für gespeicherte
  Meldungen, Pfade und Debug-Felder.

Sensible Felder wie Tokens, API-Keys, Passwörter und Secrets werden maskiert.
Das Dashboard bietet keine Downloads von synchronisierten Dateien, keine
Schreibaktionen und keine destruktiven Steuerungsfunktionen. Der einzige
Download ist der Audit-Export unter `/api/audit.xlsx`. Diese Excel-Datei enthält
mehrere Tabellenblätter für Übersicht, Sync-Läufe, Änderungen, Logs, Quellen,
Ziele und Diagnose. Sie basiert auf den begrenzten Dashboard-Historien und
enthält keine Seafile-/RAGFlow-Dateiinhalte.

Der Health-Endpunkt `/api/health` liefert begrenzte Statusdaten für Dashboard,
Datenbank, Redis, Seafile-Admin-API, RAGFlow-API und Sync-Job-Zustand. Externe
Checks nutzen kurze Timeouts, damit ein nicht erreichbarer Dienst die
Weboberfläche nicht blockiert. Da keine Authentifizierung eingebaut ist, muss
der Zugriff über Netzwerkregeln, Reverse Proxy, Portainer-Portmapping oder nicht
veröffentlichte Ports kontrolliert werden.
