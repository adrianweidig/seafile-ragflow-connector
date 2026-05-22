# Konfiguration

Die Konfiguration erfolgt über Environment-Variablen. Für Installationen ist
`connector.env.example` im Repo-Root die zentrale Schnittstelle: Datei zu
`connector.env` kopieren, `change-me` Werte und Base-URLs ersetzen und dieselbe
Datei mit Docker Compose oder Portainer verwenden. Secrets müssen über
Portainer-Environment-Management, Docker Secrets oder eine lokale nicht
committed Env-Datei bereitgestellt werden.

## TLS und interne Zertifizierungsstellen

Wenn ein Zielsystem mit `unable to get local issuer certificate` fehlschlägt,
vertraut der Connector dem ausstellenden Root- oder Intermediate-Zertifikat
nicht. Die saubere Lösung ist ein PEM-CA-Bundle statt `VERIFY_SSL=false`.

```env
CONNECTOR_CERTS_HOST_DIR=./certs
CONNECTOR_CA_BUNDLE=/certs/company-root-ca.pem
SEAFILE_VERIFY_SSL=true
SEAFILE_CA_BUNDLE=
RAGFLOW_VERIFY_SSL=true
RAGFLOW_CA_BUNDLE=
OPENWEBUI_VERIFY_SSL=true
OPENWEBUI_CA_BUNDLE=
```

- `CONNECTOR_CERTS_HOST_DIR`: Host-Verzeichnis, das in Compose/Portainer
  read-only nach `/certs` gemountet wird.
- `CONNECTOR_CA_BUNDLE`: gemeinsames PEM-Bundle für Seafile, RAGFlow und
  OpenWebUI. Es muss im Container existieren.
- `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE`, `OPENWEBUI_CA_BUNDLE`: optionale
  service-spezifische Overrides, falls die Systeme unterschiedlichen CAs
  vertrauen müssen.
- `SEAFILE_VERIFY_SSL=false`, `RAGFLOW_VERIFY_SSL=false` oder
  `OPENWEBUI_VERIFY_SSL=false`: nur als kurzfristiger Diagnose-Notfall,
  weil damit Zertifikatsprüfung für den jeweiligen Dienst abgeschaltet wird.

Für die von OpenWebUI ausgeführten Tools und Pipes gibt es zusätzlich:

```env
OPENWEBUI_PROXY_VERIFY_SSL=true
OPENWEBUI_PROXY_CA_BUNDLE=
```

Diese Werte betreffen den HTTP-Aufruf von OpenWebUI zum Connector-Proxy. Wenn
`OPENWEBUI_PROXY_INTERNAL_BASE_URL` auf eine HTTPS-URL mit interner CA zeigt,
muss `OPENWEBUI_PROXY_CA_BUNDLE` ein Pfad sein, der im OpenWebUI-Container
existiert; der Connector schreibt den Wert als Valve in Tool und Pipe.

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

## Delete-Policy

Seafile ist immer die Quelle der Wahrheit. Der Connector löscht oder verändert
keine Seafile-Daten, nur weil Zielartefakte in RAGFlow oder OpenWebUI fehlen
oder gelöscht wurden.

```env
DELETE_RAGFLOW_DOCS_ON_SEAFILE_DELETE=true
DELETE_DATASET_WHEN_LIBRARY_DELETED=true
ARCHIVE_DATASET_WHEN_LIBRARY_DELETED=false
```

- `DELETE_RAGFLOW_DOCS_ON_SEAFILE_DELETE=true`: entfernt RAGFlow-Dokumente,
  wenn die zugehörige Datei in Seafile nicht mehr existiert.
- `DELETE_DATASET_WHEN_LIBRARY_DELETED=true`: entfernt das vom Connector
  erzeugte RAGFlow-Dataset, wenn die Seafile-Library nicht mehr existiert.
- Externe Löschungen in RAGFlow werden repariert: fehlt ein Dataset, wird es
  beim nächsten Sync aus dem Template neu erzeugt; fehlen Dokumente, werden sie
  aus Seafile erneut hochgeladen.
- Externe Löschungen in OpenWebUI werden durch den OpenWebUI-Sync repariert:
  fehlende eigene Tools und Pipes werden neu erzeugt, statt Seafile zu ändern.

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

## OpenWebUI

Die OpenWebUI-Integration ist optional und bleibt deaktiviert, solange
`OPENWEBUI_INTEGRATION_ENABLED=false` ist. In diesem Zustand werden keine
OpenWebUI-Clients aufgebaut, keine Jobs geplant und keine OpenWebUI-Artefakte
geschrieben.

```env
OPENWEBUI_INTEGRATION_ENABLED=false
OPENWEBUI_BASE_URL=http://localhost:3000
OPENWEBUI_ADMIN_API_KEY=
OPENWEBUI_SYNC_ON_STARTUP=true
OPENWEBUI_SYNC_MODE=sync
OPENWEBUI_CREATE_TOOLS=true
OPENWEBUI_CREATE_PIPES=true
OPENWEBUI_REQUEST_TIMEOUT_SECONDS=180
OPENWEBUI_VERIFY_SSL=true
OPENWEBUI_CA_BUNDLE=
OPENWEBUI_FUNCTION_NAMESPACE=ragflow
OPENWEBUI_SOURCE_PREVIEW_MODE=ragflow_link
OPENWEBUI_PROXY_PUBLIC_BASE_URL=
OPENWEBUI_PROXY_INTERNAL_BASE_URL=
OPENWEBUI_PROXY_SHARED_SECRET=
OPENWEBUI_PROXY_VERIFY_SSL=true
OPENWEBUI_PROXY_CA_BUNDLE=
OPENWEBUI_SYNC_INTERVAL_SECONDS=300
OPENWEBUI_DATASET_ALLOWLIST=
SEAFILE_FILE_URL_TEMPLATE=
RAGFLOW_PUBLIC_BASE_URL=
RAGFLOW_DOCUMENT_URL_TEMPLATE=
```

- `OPENWEBUI_SYNC_MODE=disabled`: keine OpenWebUI-Synchronisation.
- `OPENWEBUI_SYNC_MODE=dry-run`: prüft Datasets und geplante Artefakte, schreibt
  aber nicht nach RAGFlow oder OpenWebUI.
- `OPENWEBUI_SYNC_MODE=sync`: erzeugt oder aktualisiert fehlende Chats, Tools
  und Pipes idempotent.
- `OPENWEBUI_SYNC_MODE=repair`: repariert fehlende oder driftende eigene
  Artefakte, ohne fremde Artefakte zu löschen.
- `OPENWEBUI_ADMIN_API_KEY`: nur für `sync` und `repair` erforderlich. Der Wert
  wird maskiert und nicht in generierte Tools oder Pipes geschrieben.
- `OPENWEBUI_PROXY_SHARED_SECRET`: schützt den Connector-Proxy, den die
  OpenWebUI-Functions aufrufen. Es wird als Valve gesetzt, nicht als
  Python-Literal im generierten Code.
- `OPENWEBUI_PROXY_INTERNAL_BASE_URL`: URL, die OpenWebUI serverseitig zum
  Connector erreicht. Wenn leer, wird `OPENWEBUI_PROXY_PUBLIC_BASE_URL`
  verwendet.
- `OPENWEBUI_SOURCE_PREVIEW_MODE`: `ragflow_link`, `connector_viewer`,
  `citation_only` oder `disabled`.
- `OPENWEBUI_DATASET_ALLOWLIST`: optionale CSV aus Repo-IDs oder
  RAGFlow-Dataset-IDs für stufenweisen Rollout.
- `SEAFILE_FILE_URL_TEMPLATE`: optionales Template für einen Browser-Link zum
  Originaldokument in der Quellenpreview. Verfügbare Platzhalter sind
  `{repo_id}`, `{repo_id_quoted}`, `{path}`, `{path_quoted}`, `{path_query}`,
  `{page}`, `{page_fragment}`, `{document_id}` und `{chunk_id}`. Für PDFs kann
  ein Template z. B. `{page_fragment}` anhängen, um `#page=7` zu erzeugen.

Im Modus `connector_viewer` erzeugt der Connector signierte Quellenlinks auf
`/api/openwebui/sources/preview`. Diese Links enthalten die von RAGFlow
gelieferte Chunk-Referenz inklusive Seite, Position und Textauszug und bleiben
für gespeicherte OpenWebUI-Chatverläufe dauerhaft gültig, solange
`OPENWEBUI_PROXY_SHARED_SECRET` unverändert bleibt. Die Preview nutzt nur
lokales HTML/CSS und keine CDN-Assets. Wenn `SEAFILE_FILE_URL_TEMPLATE` gesetzt
ist, zeigt die Preview zusätzlich einen Button zum Originaldokument. Wenn
RAGFlow selbst stabile öffentliche Dokument-/Chunk-Links liefert oder
`RAGFLOW_DOCUMENT_URL_TEMPLATE` gesetzt ist, kann `ragflow_link` stattdessen
direkt auf RAGFlow zeigen.

Wenn OpenWebUI aktiviert ist, benötigt der Connector-Controller einen
erreichbaren HTTP-Port für Proxy-Routen wie `/api/openwebui/proxy/chat` und
`/api/openwebui/proxy/query`. Die generierten OpenWebUI-Tools und Pipes greifen
nur auf ihr fest zugeordnetes Dataset zu.

Wenn eine Seafile-Library gelöscht wurde, löscht der OpenWebUI-Sync die
zugehörigen eigenen Tools, Pipes und RAGFlow-Chats. Fehlen eigene OpenWebUI-
Artefakte durch externe Änderungen, werden sie in `sync` und `repair` neu
erzeugt. Fremde Artefakte mit kollidierender ID werden nicht gelöscht oder
überschrieben, sondern als `manual_required` angezeigt.
