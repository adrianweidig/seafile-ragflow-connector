# Konfiguration

Die Konfiguration erfolgt über Environment-Variablen. Für Installationen ist
`connector.env.example` im Repo-Root die zentrale Schnittstelle: Datei zu
`connector.env` kopieren, nur die Pflichtwerte für den gewählten Betriebsmodus
setzen und dieselbe Datei mit Docker Compose oder Portainer verwenden. Die
vollständige Pflicht-/Optional-Liste steht in
[`environment.md`](environment.md).

Minimalpflicht für Seafile -> RAGFlow mit Stack-Postgres:

```env
SEAFILE_BASE_URL=
SEAFILE_ADMIN_TOKEN=
SEAFILE_SYNC_USER_TOKEN=
RAGFLOW_BASE_URL=
RAGFLOW_API_KEY=
POSTGRES_PASSWORD=
```

Alternativ ersetzt `DATABASE_URL` die `POSTGRES_*`-Anwendungswerte. OpenWebUI,
Dashboard, TLS-CA-Bundles, URL-Rewrites und Tuning sind optionale Erweiterungen.
Secrets müssen über Portainer-Environment-Management, Docker Secrets oder eine
lokale nicht committete Env-Datei bereitgestellt werden.

## Sprache und Locale

Deutsch ist die Standardsprache für menschenlesbare CLI-, Dashboard-,
OpenWebUI- und Dokumentationstexte. Englisch ist die wichtigste
Alternativsprache. Produktoberflächen und OpenWebUI-Artefakte sind zusätzlich
für `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `uk`, `zh`, `ja` und `ar`
integriert:

```env
CONNECTOR_LANGUAGE=de
```

Zulässig sind `de`, `en`, `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `uk`,
`zh`, `ja` und `ar`, auch in Locale-Formen wie `de_DE.UTF-8`,
`en_US.UTF-8` oder `pt_BR.UTF-8`. Wenn `CONNECTOR_LANGUAGE` leer oder
unbekannt ist, versucht der Connector eine System-/Umgebungs-Locale zu
erkennen und fällt bei unsicherer Erkennung stabil auf Deutsch zurück.
API-Feldnamen, Env-Namen, Statuscodes, IDs, Protokollwerte und Dateipfade
werden nicht übersetzt. Details stehen in [`i18n.md`](i18n.md).

## TLS und interne Zertifizierungsstellen

Wenn ein Zielsystem mit `unable to get local issuer certificate` fehlschlägt,
vertraut der Connector dem ausstellenden Root- oder Intermediate-Zertifikat
nicht. Die saubere Lösung ist ein PEM-CA-Bundle statt `VERIFY_SSL=false`.

```env
CONNECTOR_ENTERPRISE_CA_HOST_FILE=/opt/seafile-ragflow-connector/certs/company-root-ca.pem
CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE=/certs/company-root-ca.pem
CONNECTOR_CA_BUNDLE=/certs/company-root-ca.pem
SEAFILE_VERIFY_SSL=true
SEAFILE_CA_BUNDLE=
RAGFLOW_VERIFY_SSL=true
RAGFLOW_CA_BUNDLE=
OPENWEBUI_VERIFY_SSL=true
OPENWEBUI_CA_BUNDLE=
```

- `CONNECTOR_ENTERPRISE_CA_HOST_FILE`: absoluter Host-Pfad zur
  Unternehmens-Root-CA oder CA-Chain für das Enterprise-Compose-Overlay. Leer
  ist gültig; dann wird kein Enterprise-CA-Overlay benötigt und der Container
  nutzt die System-CAs.
- `CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE`: Containerpfad dieses Mounts,
  standardmäßig `/certs/company-root-ca.pem`.
- `CONNECTOR_CERTS_HOST_DIR`: Host-Verzeichnis, das in älteren
  Compose-/Portainer-Varianten read-only nach `/certs` gemountet wird.
- `CONNECTOR_CA_BUNDLE`: gemeinsames PEM-Bundle für Seafile, RAGFlow und
  OpenWebUI. Es muss im Container existieren.
- Der Entrypoint führt bei jedem Containerstart `update-ca-certificates` aus.
  Wenn `CONNECTOR_CA_BUNDLE` gesetzt ist, wird dieses Bundle vorher in den
  System-Trust-Store kopiert. Danach startet der Connector wieder als
  unprivilegierter Benutzer. Ohne eigenes Bundle bleibt der Schritt
  unschädlich und nutzt nur den vorhandenen System-Trust.
- `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE`, `OPENWEBUI_CA_BUNDLE`: optionale
  service-spezifische Overrides, falls die Systeme unterschiedlichen CAs
  vertrauen müssen.
- `SEAFILE_VERIFY_SSL=false`, `RAGFLOW_VERIFY_SSL=false` oder
  `OPENWEBUI_VERIFY_SSL=false`: nur als kurzfristiger Diagnose-Notfall,
  weil damit Zertifikatsprüfung für den jeweiligen Dienst abgeschaltet wird.

Der Connector bevorzugt verschlüsselte Service-Kommunikation automatisch:
Beim Runtime-Start wird für Seafile, RAGFlow und eine aktivierte OpenWebUI-
Integration zuerst `https://` mit derselben Host-/Port-Basis geprüft. Wenn
dabei kein HTTP-Response zustande kommt, wird `http://` als Fallback genutzt.
HTTP-Statuscodes wie 401 oder 500 beweisen dabei bereits den Transport und
lösen keinen HTTP-Fallback aus; Auth- oder API-Fehler bleiben danach im Health-
Status sichtbar. Der gewählte Transport steht im Dashboard-Health-Bereich und
in den Diagnosewerten unter `connector_transport_status`.

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

Das Dashboard ist eine Weboberfläche für Status, Sync-Historie, Änderungen,
Logs, Quellen/Ziele, technische Diagnose und kontrollierte Prüfläufe. Da das
Projekt vorher keine Weboberfläche hatte, ist sie standardmäßig deaktiviert. Im
laufenden `connector-controller` kann der Tab **Prüfablauf** die mit dem
Seafile-API-Key sichtbaren Bibliotheken anzeigen und ausgewählte Bibliotheken
für RAGFlow-Dataset-/Dokument-Sync sowie optional OpenWebUI-Chat-/Tool-/Pipe-
Sync starten. Der Standalone-Befehl `connector dashboard` bleibt ein
Status-Dashboard ohne Runtime-Controller und zeigt diese Steuerung als nicht
verfügbar. Das UI wird vollständig aus dem Connector ausgeliefert und lädt
keine CDN- oder Internet-Assets nach. Der Theme-Wechsel zwischen Dark und Light
wird lokal im Browser gespeichert. Der Auto-Refresh ist im Dashboard zwischen
aus, 5 Sekunden, 10 Sekunden und 1 Minute wählbar und wird ebenfalls lokal im
Browser gespeichert. Die Sprachwahl ist sichtbar im Dashboard, nutzt Deutsch
als Fallback und kann für englische Bedienung auf `English` gestellt werden.

```env
CONNECTOR_DASHBOARD_ENABLED=false
CONNECTOR_DASHBOARD_HOST=0.0.0.0
CONNECTOR_DASHBOARD_PORT=8080
CONNECTOR_DASHBOARD_MAX_LOG_ENTRIES=5000
CONNECTOR_DASHBOARD_MAX_EVENT_ENTRIES=10000
CONNECTOR_DASHBOARD_MAX_SYNC_RUNS=1000
CONNECTOR_DASHBOARD_LOG_PAGE_SIZE=100
CONNECTOR_DASHBOARD_MAX_FIELD_LENGTH=4000
CONNECTOR_DASHBOARD_AUTH_USERNAME=admin
CONNECTOR_DASHBOARD_AUTH_PASSWORD=change-me-dashboard-password
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
- `CONNECTOR_DASHBOARD_AUTH_USERNAME` und
  `CONNECTOR_DASHBOARD_AUTH_PASSWORD`: aktivieren HTTP Basic Auth für
  Dashboard-Oberfläche, Status-API und Workflow-Steuerung. Beide Werte müssen
  zusammen gesetzt werden. Die OpenWebUI-Proxy-POST-Endpunkte nutzen weiterhin
  das separate `OPENWEBUI_PROXY_SHARED_SECRET`.

Sensible Felder wie Tokens, API-Keys, Passwörter und Secrets werden maskiert.
Das Dashboard bietet keine Downloads von synchronisierten Dateien und keine
destruktiven Steuerungsfunktionen. Workflow-Aktionen starten nur explizit
ausgewählte Syncs für Bibliotheken, die der aktuelle Seafile-API-Key sieht. Der
einzige Download ist der Audit-Export unter `/api/audit.xlsx`. Diese Excel-Datei
enthält mehrere Tabellenblätter für Übersicht, Sync-Läufe, Änderungen, Logs,
Quellen, Ziele und Diagnose. Sie basiert auf den begrenzten Dashboard-Historien
und enthält keine Seafile-/RAGFlow-Dateiinhalte.

Der Health-Endpunkt `/api/health` liefert begrenzte Statusdaten für Dashboard,
Datenbank, Redis, Seafile-Admin-API, RAGFlow-API und Sync-Job-Zustand. Externe
Checks nutzen kurze Timeouts, damit ein nicht erreichbarer Dienst die
Weboberfläche nicht blockiert. Für lokal gebundene Testumgebungen können die
Auth-Werte leer bleiben; bei LAN- oder Reverse-Proxy-Zugriff sollten
Benutzername und Passwort gesetzt sein.

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
OPENWEBUI_SYNC_MODE=disabled
OPENWEBUI_CREATE_TOOLS=true
OPENWEBUI_CREATE_PIPES=true
OPENWEBUI_REQUEST_TIMEOUT_SECONDS=180
OPENWEBUI_VERIFY_SSL=true
OPENWEBUI_CA_BUNDLE=
OPENWEBUI_FUNCTION_NAMESPACE=ragflow
OPENWEBUI_SOURCE_PREVIEW_MODE=connector_viewer
OPENWEBUI_PROXY_PUBLIC_BASE_URL=
OPENWEBUI_PROXY_INTERNAL_BASE_URL=
OPENWEBUI_PROXY_SHARED_SECRET=
OPENWEBUI_PROXY_VERIFY_SSL=true
OPENWEBUI_PROXY_CA_BUNDLE=
OPENWEBUI_SYNC_INTERVAL_SECONDS=1800
OPENWEBUI_DATASET_ALLOWLIST=
SEAFILE_PUBLIC_BASE_URL=
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
  OpenWebUI-Functions aufrufen. Erforderlich ist er nur, wenn Tools oder Pipes
  in `sync` oder `repair` synchronisiert werden. Es wird als Valve gesetzt,
  nicht als Python-Literal im generierten Code.
- `OPENWEBUI_PROXY_INTERNAL_BASE_URL`: URL, die OpenWebUI serverseitig zum
  Connector erreicht. Erforderlich ist eine interne oder öffentliche Proxy-URL
  nur, wenn Tools oder Pipes in `sync` oder `repair` synchronisiert werden.
  Wenn leer, wird `OPENWEBUI_PROXY_PUBLIC_BASE_URL` verwendet.
- `OPENWEBUI_SYNC_INTERVAL_SECONDS`: periodischer OpenWebUI-Sync im Controller.
  Der Default ist `1800` Sekunden, also 30 Minuten. Werte unter 60 Sekunden
  werden abgelehnt; manuelle Läufe bleiben über `connector openwebui-sync-once`
  möglich.
- `OPENWEBUI_REQUEST_TIMEOUT_SECONDS`: Timeout für OpenWebUI-Admin-, Tool- und
  Proxy-Aufrufe. Der Repository-Default `180` eignet sich für lange
  RAG-Antworten und langsame Parserpfade. Für latenzkritische OpenWebUI-
  Proxy- oder Edge-Flows sind meist `30` bis `60` Sekunden sinnvoller; dann
  müssen Reverse-Proxy- und OpenWebUI-Timeouts dazu passen.
- `OPENWEBUI_SOURCE_PREVIEW_MODE`: `ragflow_link`, `connector_viewer`,
  `citation_only` oder `disabled`. Für auditierbare OpenWebUI-Antworten ist
  `connector_viewer` empfohlen, weil Citation-Chips und Markdown-Nachweistabelle
  dann auf denselben signierten Preview-Link zeigen.
- `OPENWEBUI_DATASET_ALLOWLIST`: optionale CSV aus Repo-IDs oder
  RAGFlow-Dataset-IDs für stufenweisen Rollout.
- `SEAFILE_PUBLIC_BASE_URL`: optionale browserseitige Seafile-Basis-URL für
  Original-Links in OpenWebUI-Quellen. Wenn leer, nutzt der Connector
  `SEAFILE_BASE_URL`.
- `SEAFILE_FILE_URL_TEMPLATE`: optionaler Override für den Browser-Link zum
  Originaldokument in der Quellenpreview. Wenn leer, erzeugt der Connector den
  Standardlink `{base}/lib/{repo_id}/file{path_quoted}{page_fragment}` aus
  `SEAFILE_PUBLIC_BASE_URL` oder `SEAFILE_BASE_URL`. Verfügbare Platzhalter sind
  `{repo_id}`, `{repo_id_quoted}`, `{path}`, `{path_quoted}`, `{path_query}`,
  `{page}`, `{page_fragment}`, `{document_id}` und `{chunk_id}`. Der Override
  ist nur für abweichende Reverse-Proxy- oder Seafile-Webrouten gedacht. Das
  Ergebnis muss eine für den Browser erreichbare absolute `http(s)`-URL zum
  Originalsystem sein. Connector-Preview- oder Proxy-URLs werden nicht als
  primärer Original-Link gerendert.

Im Modus `connector_viewer` erzeugt der Connector signierte Quellenlinks auf
`/api/openwebui/sources/preview`. Diese Links enthalten die von RAGFlow
gelieferte Chunk-Referenz inklusive bester bekannter Fundstelle wie Seite,
Abschnitt, Zeile, Position, `locator_quality` und Textauszug und bleiben für
gespeicherte OpenWebUI-Chatverläufe dauerhaft gültig, solange
`OPENWEBUI_PROXY_SHARED_SECRET` unverändert bleibt. Die Preview nutzt nur
lokales HTML/CSS und keine CDN-Assets. Wenn Repo-ID und Pfad bekannt sind,
zeigt die Preview zusätzlich einen priorisierten Button zum Originaldokument und
trennt diesen sichtbar von der Connector-Preview. OpenWebUI-Pipes erhalten
keine Seafile-Tokens, Admin-Secrets oder Auth-Daten; Quellenlinks werden
serverseitig vom Connector erzeugt und als `preview_url`/`original_url`
geliefert. Wenn
RAGFlow selbst stabile öffentliche Dokument-/Chunk-Links liefert oder
`RAGFLOW_DOCUMENT_URL_TEMPLATE` gesetzt ist, kann `ragflow_link` stattdessen
direkt auf RAGFlow zeigen.

Die generierte Pipe nutzt standardmäßig `SOURCE_MARKDOWN_MODE=audit`,
`APPEND_SOURCE_OVERVIEW=true` und eigene OpenWebUI-Citation-Events. Im
Modellpicker erscheint sie mit dem Anzeigenamen `Seafile · <Dataset>`, während
die technische Modell-ID stabil bleibt. In der Antwort markiert die Pipe
Quellen als `[S1]`, `[S2]` usw. und ergänzt eine Nachweistabelle mit Dokument,
Fundstelle, Relevanzlabel und Direktlink. Numerische Scores und technische IDs
bleiben im Normalbetrieb ausgeblendet; `SHOW_SOURCE_DEBUG=true` ist nur für
Admin-Debugging gedacht.

Wenn OpenWebUI aktiviert ist, benötigt der Connector-Controller einen
erreichbaren HTTP-Port für Proxy-Routen wie `/api/openwebui/proxy/chat` und
`/api/openwebui/proxy/query`. Die generierten OpenWebUI-Tools und Pipes greifen
nur auf ihr fest zugeordnetes Dataset zu.

Wenn eine Seafile-Library gelöscht wurde, löscht der OpenWebUI-Sync die
zugehörigen eigenen Tools, Pipes und RAGFlow-Chats. Fehlen eigene OpenWebUI-
Artefakte durch externe Änderungen, werden sie in `sync` und `repair` neu
erzeugt. Fremde Artefakte mit kollidierender ID werden nicht gelöscht oder
überschrieben, sondern als `manual_required` angezeigt.
