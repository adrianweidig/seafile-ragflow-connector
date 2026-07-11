# Environment-Variablen

Die zentrale Schnittstelle ist `connector.env.example`. Für den Minimalbetrieb
gilt: nur Pflichtwerte setzen, optionale Blöcke leer lassen. Leere optionale
Werte bedeuten, dass der Code die internen Defaults nutzt.

## Minimalpflicht

Für Seafile -> RAGFlow mit Postgres und Redis aus dem Docker-Stack sind nur
diese Werte fachlich Pflicht:

| Variable | Pflicht | Wann | Hinweis |
| --- | --- | --- | --- |
| `SEAFILE_BASE_URL` | ja | immer | Aus dem Connector-Container erreichbare Seafile-URL. |
| `SEAFILE_ADMIN_TOKEN` | ja | immer | Admin-API-Token für Library-Discovery. |
| `SEAFILE_SYNC_USER_TOKEN` | ja | immer | API-Token für Dateilisten und Downloads. |
| `RAGFLOW_BASE_URL` | ja | immer | Aus dem Connector-Container erreichbare RAGFlow-API. |
| `RAGFLOW_API_KEY` | ja | immer | API-Key des RAGFlow-Zielusers. |
| `POSTGRES_PASSWORD` | ja | wenn keine `DATABASE_URL` gesetzt ist | Passwort der Stack-Datenbank. |
| `DATABASE_URL` | alternativ | wenn externe DB genutzt wird | Ersetzt `POSTGRES_*` für die Anwendung. |

`REDIS_URL` ist nur Pflicht, wenn kein Stack-Redis genutzt werden soll. In den
Compose-Dateien wird Redis standardmäßig als `connector-redis` bereitgestellt.

## Allgemeine optionale Werte

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | optional | Compose-Projektname. |
| `TZ` | optional | Zeitzone im Container. |
| `APP_ENV` | optional | Laufzeitumgebung, Default `production`. |
| `CONNECTOR_LANGUAGE` | optional | Sprache für menschenlesbare Ausgaben. Unterstützt: `de`, `en`, `es`, `fr`, `it`, `pt`, `nl`, `pl`, `tr`, `uk`, `zh`, `ja`, `ar`; leer oder unbekannt fällt auf Deutsch zurück. |
| `LOG_LEVEL`, `LOG_FORMAT` | optional | Log-Level und JSON-/Console-Ausgabe. |
| `DRY_RUN` | optional | Erzwingt für OpenWebUI den effektiven Modus `dry-run`. |
| `CONNECTOR_IMAGE`, `POSTGRES_IMAGE`, `REDIS_IMAGE` | optional | Image-Tags überschreiben, z. B. Offline-Registry. |
| `CONNECTOR_IMAGE_PULL_POLICY`, `POSTGRES_IMAGE_PULL_POLICY`, `REDIS_IMAGE_PULL_POLICY` | optional | Pull-Verhalten steuern. |

## Authz-API und ACL-Snapshot

Die Authz-API läuft im Connector-Core. Sie wird von Search-Service und
OpenWebUI-Pipe vor RAGFlow-Abfragen genutzt.

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `AUTHZ_API_ENABLED` | optional | Aktiviert die interne Authz-API; Default `true`. |
| `AUTHZ_API_SHARED_SECRET` | ja, wenn Authz genutzt wird | Bearer-Secret für technische Komponenten. |
| `AUTHZ_API_ALLOW_NETWORKS` | optional | CSV aus CIDR-Netzen, die zusätzlich zum Bearer-Secret zugelassen sind. |
| `AUTHZ_API_FAIL_CLOSED` | optional | Default `true`; unbekannte oder zu alte ACLs führen zu `deny`. |
| `AUTHZ_API_MAX_ACL_AGE_SECONDS` | optional | Maximales Alter eines ACL-Snapshots, Default `7200`. |
| `SEARCH_ACL_SYNC_ENABLED` | optional | Periodischer ACL-Snapshot im Controller, Default `true`. |
| `SEARCH_ACL_SYNC_INTERVAL_SECONDS` | optional | Snapshot-Intervall, Default `1800`. |
| `SEARCH_ACL_INCLUDE_SUBFOLDER_PERMISSIONS` | optional | Muss produktiv `false` bleiben; Unterordnerrechte werden nicht ausgewertet. |
| `SEARCH_ACL_INCLUDE_SHARE_LINKS` | optional | Muss produktiv `false` bleiben; Share-Links erzeugen keine personenbezogene Berechtigung. |

## Search-Service

Der Search-Service ist ein separater Container mit `connector search-server`.
Er benötigt keinen Seafile-Admin- oder Sync-Token.

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `SEARCH_SERVICE_ENABLED` | optional | Aktiviert den Search-Server; Default `true`. |
| `SEARCH_SERVICE_HOST`, `SEARCH_SERVICE_PORT` | optional | Bind-Adresse und Container-Port. |
| `SEARCH_SERVICE_PUBLISHED_PORT` | optional | Host-Portbindung in Compose/Portainer, z. B. `127.0.0.1:18090`. |
| `SEARCH_AUTH_MODE` | optional | Aktuell `trusted_header`. |
| `SEARCH_TRUSTED_USERNAME_HEADER` | optional | Header für den Login-/Usernamen. |
| `SEARCH_TRUSTED_EMAIL_HEADER` | optional | Header für die Nutzer-E-Mail; primärer ACL-Match-Key. |
| `SEARCH_TRUSTED_DISPLAY_NAME_HEADER` | optional | Header für den Anzeigenamen in der GUI. |
| `SEARCH_AUTHZ_BASE_URL` | ja | Interne URL zum Connector-Core, z. B. `http://connector-controller:8080`. |
| `SEARCH_AUTHZ_SHARED_SECRET` | ja | Muss zum Authz-Secret im Core passen. |
| `SEARCH_RAGFLOW_BASE_URL` | ja | RAGFlow-URL aus Sicht des Search-Containers. |
| `SEARCH_RAGFLOW_API_KEY` | ja | RAGFlow-API-Key für erlaubte Abfragen. |
| `SEARCH_RAGFLOW_VERIFY_SSL`, `SEARCH_RAGFLOW_CA_BUNDLE` | optional | TLS-Prüfung und optionales CA-Bundle für Search -> RAGFlow. |
| `SEARCH_ANSWER_GENERATION_MODE` | optional | `ragflow_chat`, `retrieval_summary` oder `disabled`; Default `ragflow_chat`. |
| `RAGFLOW_SEARCH_ANSWER_CHAT_NAME` | optional | Name des RAGFlow-Chats für Antwortgenerierung; Default `connector_search_answer`. |
| `SEARCH_ANSWER_LLM_BASE_URL` | optional | OpenAI-kompatible Basis-URL für Search-Antwortsynthese, z. B. `http://litellm:4000/v1`; leer deaktiviert diesen bevorzugten Pfad. |
| `SEARCH_ANSWER_LLM_MODEL` | optional | Modellname für den OpenAI-kompatiblen Search-Antwortpfad; nur zusammen mit `SEARCH_ANSWER_LLM_BASE_URL` aktiv. |
| `SEARCH_ANSWER_LLM_API_KEY` | optional | Bearer-Token für den OpenAI-kompatiblen Search-Antwortpfad; leer sendet keinen Authorization-Header. |
| `SEARCH_ANSWER_LLM_TIMEOUT_SECONDS` | optional | Timeout für den OpenAI-kompatiblen Search-Antwortpfad; Default `60`. |
| `SEARCH_ANSWER_LLM_MAX_TOKENS` | optional | Maximale Antwort-Tokens für den OpenAI-kompatiblen Search-Antwortpfad; Default `900`. |
| `SEARCH_ANSWER_LLM_TEMPERATURE` | optional | Temperatur für den OpenAI-kompatiblen Search-Antwortpfad; Default `0.2`, erlaubt `0` bis `2`. |
| `RAGFLOW_SEARCH_TEMPLATE_ENABLED`, `RAGFLOW_SEARCH_TEMPLATE_NAME` | optional | Aktiviert die Template-Auflösung; Default-Name ist `search_template`. |
| `SEARCH_RAGFLOW_TEMPLATE_SOURCE_ORDER` | optional | Reihenfolge der Template-Quellen. Default `search_app,chat,builtin`. |
| `SEARCH_RAGFLOW_CANDIDATE_TOP_K` | optional | Override für RAGFlows internen Kandidatenpool; leer nutzt Template oder Built-in `1024`. |
| `SEARCH_RAGFLOW_TOP_N` | optional | Override für Quellen-/Kontextanzahl; leer nutzt Template oder Built-in `8`. |
| `SEARCH_RAGFLOW_SIMILARITY_THRESHOLD`, `SEARCH_RAGFLOW_VECTOR_SIMILARITY_WEIGHT` | optional | Overrides für RAGFlow Hybrid Search; Werte zwischen `0` und `1`. |
| `SEARCH_RAGFLOW_RERANK_ID` | optional | Optionaler Reranker aus RAGFlow; bei ungültigem Modell wird einmal ohne Reranker wiederholt. |
| `SEARCH_RAGFLOW_KEYWORD`, `SEARCH_RAGFLOW_HIGHLIGHT` | optional | Overrides für Keyword-Matching und Highlighting. |
| `SEARCH_RAGFLOW_CROSS_LANGUAGES` | optional | CSV-Liste für Cross-Language Retrieval. |
| `SEARCH_RAGFLOW_USE_KG`, `SEARCH_RAGFLOW_TOC_ENHANCE` | optional | Overrides für Knowledge Graph und PageIndex/TOC Enhance; nur aktivieren, wenn die Datasets entsprechend vorbereitet sind. |
| `SEARCH_SEAFILE_PUBLIC_BASE_URL`, `SEARCH_SEAFILE_FILE_URL_TEMPLATE` | optional | Browserseitige Seafile-Links für "Quelle öffnen"; kein Seafile-Token. |
| `SEARCH_DEFAULT_TOP_K`, `SEARCH_MAX_TOP_K` | optional | Trefferzahl-Defaults und Obergrenze. |
| `SEARCH_MAX_SELECTED_PROFILES` | optional | Maximale Anzahl gleichzeitig ausgewählter Bibliotheken. |
| `SEARCH_ENABLE_CHAT_MODE`, `SEARCH_ENABLE_RETRIEVAL_MODE` | optional | UI- und API-Modi einzeln aktivieren. |
| `SEARCH_SOURCE_PREVIEW_ENABLED` | optional | Aktiviert signierte Evidence-Viewer-Links pro Treffer; Default `true`. |
| `SEARCH_SOURCE_HOVER_ENABLED` | optional | Reservierter UX-Schalter für Hover-/Fokus-Vorschauen; Default `true`. |
| `SEARCH_TEXT_FRAGMENT_LINKS_ENABLED` | optional | Erzeugt best-effort Browser-Textfragment-Links, wenn kein Seitenanker vorhanden ist; Default `true`. |
| `SEARCH_DOCUMENT_VIEWER_ENABLED` | optional | Aktiviert den authz-geprüften Dokumentproxy für den nativen Browserviewer; Default `true`. |
| `SEARCH_DOCUMENT_VIEWER_MAX_MB` | optional | Größenlimit für ausgelieferte Viewer-Dokumente; Default `100`. |
| `SEARCH_DOCUMENT_VIEWER_TIMEOUT_SECONDS`, `SEARCH_DOCUMENT_VIEWER_MAX_CONCURRENCY` | optional | Deadline und parallele Downloadgrenze des Dokumentviewers; Defaults `30` Sekunden und `4`. |
| `SEARCH_PDF_RENDER_MAX_CONCURRENCY`, `SEARCH_PDF_RENDER_MAX_MB` | optional | Begrenzung paralleler PDF-Renderings und maximaler gerenderter PNG-Größe; Defaults `2` und `25` MiB. |
| `SEARCH_RESULT_SNIPPET_CONTEXT_CHARS` | optional | Maximale Snippet-Länge in Search-Antworten und Preview-Tokens; Default `420`. |
| `SEARCH_ANSWER_MAX_SOURCES` | optional | Maximale Anzahl Quellenchips im Antwortmodus; Default `8`. |
| `SEARCH_SOURCE_PREVIEW_SECRET` | optional | Separates Signatur-Secret für Search-Preview-Tokens; fällt auf `SEARCH_AUTHZ_SHARED_SECRET` zurück. |

## OpenWebUI-Pflichtwerte

OpenWebUI ist optional. Solange `OPENWEBUI_INTEGRATION_ENABLED=false` oder
`OPENWEBUI_SYNC_MODE=disabled` gilt, sind keine OpenWebUI-Secrets Pflicht.

| Variable | Pflicht | Wann |
| --- | --- | --- |
| `OPENWEBUI_BASE_URL` | ja | nur bei aktivem `sync` oder `repair`; Default reicht oft im Docker-Netz. |
| `OPENWEBUI_ADMIN_API_KEY` | ja | bei `OPENWEBUI_SYNC_MODE=sync` oder `repair`. |
| `OPENWEBUI_PROXY_SHARED_SECRET` | ja | wenn Tools oder Pipes synchronisiert werden. |
| `OPENWEBUI_PROXY_INTERNAL_BASE_URL` oder `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | ja | wenn Tools oder Pipes synchronisiert werden. |
| `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | ja | zusätzlich bei `OPENWEBUI_SOURCE_PREVIEW_MODE=connector_viewer`. |

`OPENWEBUI_SYNC_MODE=dry-run` prüft ohne Schreibzugriff und verlangt keinen
Proxy-Secret und keine Preview-URL.

## OpenWebUI optionale Werte

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `OPENWEBUI_INTEGRATION_ENABLED` | optional | Aktiviert OpenWebUI überhaupt; Default für Minimalbetrieb ist `false`. |
| `OPENWEBUI_SYNC_ON_STARTUP` | optional | Sync beim Controller-Start ausführen. |
| `OPENWEBUI_SYNC_MODE` | optional | `disabled`, `dry-run`, `sync` oder `repair`. |
| `OPENWEBUI_CREATE_TOOLS`, `OPENWEBUI_CREATE_PIPES` | optional | Tool-/Pipe-Erzeugung getrennt steuern. |
| `OPENWEBUI_REQUEST_TIMEOUT_SECONDS` | optional | Timeout für OpenWebUI- und Proxy-Aufrufe. Default `180` unterstützt lange RAG-Antworten; für latenzkritische Proxy-/Edge-Flows eher `30` bis `60` Sekunden wählen und Reverse-Proxy-Timeouts angleichen. |
| `OPENWEBUI_VERIFY_SSL`, `OPENWEBUI_CA_BUNDLE` | optional | TLS für Connector -> OpenWebUI Admin API. |
| `OPENWEBUI_FUNCTION_NAMESPACE` | optional | Präfix für erzeugte Tool-/Pipe-IDs. |
| `OPENWEBUI_SOURCE_PREVIEW_MODE` | optional | `ragflow_link`, `connector_viewer`, `citation_only` oder `disabled`; `connector_viewer` ist für klickbare Citations mit Direktlink zur Fundstelle empfohlen. |
| `OPENWEBUI_PIPE_ANSWER_SYNTHESIS_ENABLED` | optional | Aktiviert einen OpenAI-kompatiblen Modell-Fallback, falls RAGFlow nur Retrieval-Treffer zurückgibt. |
| `OPENWEBUI_PIPE_ANSWER_LLM_BASE_URL` | optional | Base-URL des Fallback-Modells, z. B. `http://litellm:4000/v1`. |
| `OPENWEBUI_PIPE_ANSWER_LLM_MODEL` | optional | Modellname für die Antwortsynthese. |
| `OPENWEBUI_PIPE_ANSWER_LLM_API_KEY` | optional | Runtime-Secret für den Fallback; nicht in Repository-Dateien speichern. |
| `OPENWEBUI_SYNC_INTERVAL_SECONDS` | optional | Periodischer OpenWebUI-Sync im Controller. Default `1800` Sekunden, also 30 Minuten. Werte unter 60 Sekunden werden abgelehnt. |
| `OPENWEBUI_DATASET_ALLOWLIST` | optional | CSV aus Repo-IDs oder Dataset-IDs für stufenweisen Rollout. |
| `OPENWEBUI_AUTHZ_ENABLED` | optional | Aktiviert die zentrale ACL-Prüfung vor RAGFlow-Abfragen; Default `true`. |
| `OPENWEBUI_AUTHZ_BASE_URL` | optional | Interne Authz-Basis-URL; fällt auf die Connector-Proxy-Basis-URL zurück. |
| `OPENWEBUI_AUTHZ_SHARED_SECRET` | optional | Sollte dem `AUTHZ_API_SHARED_SECRET` entsprechen. |
| `OPENWEBUI_AUTHZ_FAIL_CLOSED` | optional | Default `true`; bei Authz-Fehlern wird RAGFlow nicht abgefragt. |

## TLS/CA

| Variable | Pflicht | Wann |
| --- | --- | --- |
| `CONNECTOR_CERTS_HOST_DIR` | optional | wenn CA-Dateien per Compose nach `/certs` gemountet werden. |
| `CONNECTOR_ENTERPRISE_CA_HOST_FILE` | optional | absoluter Host-Pfad zur Unternehmens-Root-CA/Chain für `deploy/compose/enterprise-ca.compose.yml`. |
| `CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE` | optional | Containerpfad des Enterprise-CA-Mounts, Default `/certs/company-root-ca.pem`. |
| `CONNECTOR_CA_BUNDLE` | optional | gemeinsamer CA-Fallback für Seafile, RAGFlow und OpenWebUI. |
| `CONNECTOR_SYSTEM_CA_BUNDLE` | optional | System-Trust-Bundle nach `update-ca-certificates`, Default `/etc/ssl/certs/ca-certificates.crt`. |
| `SEAFILE_VERIFY_SSL`, `RAGFLOW_VERIFY_SSL`, `OPENWEBUI_VERIFY_SSL` | optional | Default ist `true`; `false` nur für Debug. |
| `SEAFILE_CA_BUNDLE`, `RAGFLOW_CA_BUNDLE`, `OPENWEBUI_CA_BUNDLE` | optional | nur bei interner CA oder unterschiedlicher PKI je Dienst. |
| `OPENWEBUI_PROXY_VERIFY_SSL`, `CONNECTOR_PROXY_VERIFY_SSL` | optional | Default ist `true`; betrifft Pipe -> Connector Proxy. |
| `OPENWEBUI_PROXY_CA_BUNDLE`, `CONNECTOR_PROXY_CA_BUNDLE` | optional | nur wenn OpenWebUI dem Connector-Proxy-Zertifikat sonst nicht vertraut. |
| `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` | optional | globale Fallbacks für Bibliotheken außerhalb der streckenspezifischen HTTPX-Konfiguration. |
| `RAGFLOW_CLIENT_CERT_FILE`, `RAGFLOW_CLIENT_KEY_FILE` | optional | vorbereitet für mTLS zu RAGFlow; Pfade werden validiert, aber noch nicht als HTTPX-Client-Zertifikat verwendet. |
| `SEAFILE_CLIENT_CERT_FILE`, `SEAFILE_CLIENT_KEY_FILE` | optional | vorbereitet für mTLS zu Seafile; Pfade werden validiert, aber noch nicht als HTTPX-Client-Zertifikat verwendet. |
| `CONNECTOR_PROXY_CLIENT_CERT_FILE`, `CONNECTOR_PROXY_CLIENT_KEY_FILE` | optional | vorbereitet für mTLS von OpenWebUI zum Connector-Proxy; Pfade werden validiert, aber noch nicht als HTTPX-Client-Zertifikat verwendet. |

Ein gesetzter CA- oder mTLS-Dateipfad muss im jeweiligen Container existieren
und eine Datei sein. Ein leerer Pfad ist gültig und nutzt den Standard-Trust.
Der Container führt `update-ca-certificates` bei jedem Start aus. Ist
`CONNECTOR_CA_BUNDLE` leer, bleibt das unschädlich und nutzt nur die
installierten System-CAs.

## Übliche optionale Betriebswerte

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `SEAFILE_INTERNAL_URL`, `RAGFLOW_INTERNAL_URL` | optional | abweichende interne URL für Container-zu-Container-Traffic. |
| `SEAFILE_SYNC_USER_EMAIL` | optional | Dokumentativer Sync-User-Hinweis; Token ist maßgeblich. |
| `SEAFILE_SKIP_ENCRYPTED_LIBRARIES`, `SEAFILE_SKIP_VIRTUAL_REPOS` | optional | Discovery-Filter für Seafile-Libraries. |
| `SEAFILE_PUBLIC_BASE_URL` | optional | browserseitige Seafile-Basis-URL für OpenWebUI-Original-Links; fällt auf `SEAFILE_BASE_URL` zurück. |
| `SEAFILE_FILE_URL_TEMPLATE` | optional | Override für abweichende Seafile-Webrouten; sonst wird der Original-Link automatisch aus Basis-URL, Repo-ID und Pfad erzeugt. |
| `SEAFILE_REWRITE_DOWNLOAD_URLS`, `SEAFILE_DOWNLOAD_REWRITE_FROM`, `SEAFILE_DOWNLOAD_REWRITE_TO` | optional | Rewrite von Seafile-Download-URLs, z. B. von `127.0.0.1` auf Docker-DNS. Das Rewrite-Ziel wird als vertrauenswürdige Download-Origin behandelt. |
| `SEAFILE_DOWNLOAD_ALLOWED_ORIGINS` | optional | Kommaseparierte zusätzliche Origins (`https://host[:port]`), an die der Sync-Authorization-Header gesendet werden darf. Standardmäßig sind nur die Seafile-Basis-Origin und ein explizites Rewrite-Ziel erlaubt. |
| `RAGFLOW_TEMPLATE_DATASET_NAME` | optional | Default ist `connector_template`. |
| `RAGFLOW_TEMPLATE_AUTO_CREATE` | optional | Default `true`; fehlende Dataset-Templates werden beim Provisioning automatisch angelegt. |
| `RAGFLOW_TEMPLATE_REQUIRED` | optional | Default `true`; Healthcheck warnt nur noch, wenn Auto-Create deaktiviert ist und das Template fehlt. |
| `RAGFLOW_TEMPLATE_CHAT_NAME` | optional | Default `connector_template_chat`; Template-Chat für die OpenWebUI/RAGFlow-Chat-Defaults. |
| `RAGFLOW_SEARCH_TEMPLATE_ENABLED` | optional | Default `true`; aktiviert `search_template` als Suchqualitäts-Vorlage. |
| `RAGFLOW_SEARCH_TEMPLATE_NAME` | optional | Default `search_template`; Name der RAGFlow Search App oder des Chat-Fallbacks. |
| `RAGFLOW_SEARCH_TEMPLATE_AUTO_CREATE` | optional | Default `true`; der Controller legt die Search App mit Built-in-Defaults an, wenn RAGFlow die API unterstützt. |
| `RAGFLOW_SEARCH_TEMPLATE_REQUIRED` | optional | Default `false`; bei `true` schlägt die Template-Auflösung fehl, wenn keine passende Vorlage existiert. |
| `RAGFLOW_SEARCH_TEMPLATE_REFRESH_SECONDS` | optional | Default `300` Sekunden; Intervall für die Search-Template-Prüfung im Controller. Werte unter 60 Sekunden werden abgelehnt. |
| `RAGFLOW_SEARCH_ANSWER_CHAT_AUTO_CREATE` | optional | Default `true`; der Controller legt den benannten Answer-Chat für `SEARCH_ANSWER_GENERATION_MODE=ragflow_chat` an, wenn er fehlt. |
| `SEARCH_ANSWER_LLM_*` | optional | Dieselben optionalen OpenAI-kompatiblen Search-Antwortsettings werden an Controller- und Search-Services durchgereicht; Secrets bleiben reine Runtime-Env-Werte. |
| `RAGFLOW_TEMPLATE_REFRESH_SECONDS` | optional | Intervall für Aktualisierung der Dataset-Einstellungen. Default `1800` Sekunden, also 30 Minuten. Werte unter 60 Sekunden werden abgelehnt. |
| `RAGFLOW_PUBLIC_BASE_URL`, `RAGFLOW_DOCUMENT_URL_TEMPLATE` | optional | öffentliche RAGFlow-Links in Quellen. |
| `CONNECTOR_DASHBOARD_ENABLED` | optional | Dashboard starten; für OpenWebUI-Proxy nötig. |
| `CONNECTOR_DASHBOARD_HOST`, `CONNECTOR_DASHBOARD_PORT` | optional | Bind-Adresse und Port im Container. |
| `CONNECTOR_DASHBOARD_PUBLISHED_PORT` | optional | Host-Portbindung in Compose. |
| `CONNECTOR_DASHBOARD_MAX_LOG_ENTRIES`, `CONNECTOR_DASHBOARD_MAX_EVENT_ENTRIES`, `CONNECTOR_DASHBOARD_MAX_SYNC_RUNS`, `CONNECTOR_DASHBOARD_LOG_PAGE_SIZE`, `CONNECTOR_DASHBOARD_MAX_FIELD_LENGTH` | optional | Speicher- und Anzeigegrenzen des Dashboards. |
| `CONNECTOR_DASHBOARD_AUTH_USERNAME`, `CONNECTOR_DASHBOARD_AUTH_PASSWORD` | optional | HTTP Basic Auth für Dashboard-UI, Status-API und Workflow-Steuerung; beide Werte zusammen setzen. |
| `CONNECTOR_DOCKER_NETWORK_EXTERNAL`, `CONNECTOR_DOCKER_NETWORK_NAME` | optional | eigenes Netz per Default; bei vorhandenem externem Netz den realen Netzwerknamen setzen. |
| `CONNECTOR_SWARM_NETWORK_NAME` | optional | Overlay-Netzname für Swarm. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT` | optional | Defaults reichen im Stack. |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | optional | Defaults reichen im Stack. |

## Tuning und Policy

Diese Variablen sind nicht für den ersten Start erforderlich:

| Gruppe | Variablen |
| --- | --- |
| Datei-Policy | `ALLOW_UNKNOWN_TEXT_FILES`, `ALLOW_EXTENSIONS`, `DENY_EXTENSIONS`, `TEXT_EXTENSIONS`, `BINARY_DIRECT_EXTENSIONS`, `DEFAULT_TEXT_INGESTION_STRATEGY`, `PRESERVE_ORIGINAL_FILENAME_IN_METADATA`, `MAX_FILE_SIZE_MB`, `EXCLUDE_REGEX` |
| Dataset-Policy | `DATASET_SETTINGS_SOURCE`, `RAGFLOW_REFRESH_DATASET_SETTINGS`, `REPARSE_ON_DATASET_SETTINGS_CHANGE`, `RAGFLOW_VALIDATE_CREATED_DATASET` |
| Scheduling | `DISCOVERY_INTERVAL_SECONDS`, `DELTA_SYNC_INTERVAL_SECONDS`, `RECONCILE_INTERVAL_SECONDS`, `FULL_SYNC_ON_MISSING_COMMIT` |
| Delete-/Repair-Policy | `DELETE_RAGFLOW_DOCS_ON_SEAFILE_DELETE`, `DELETE_DATASET_WHEN_LIBRARY_DELETED`, `ARCHIVE_DATASET_WHEN_LIBRARY_DELETED` |
| Durchsatz | `MAX_CONCURRENT_LIBRARIES`, `UPLOAD_WORKERS`, `PARSE_WORKERS`, `RAGFLOW_UPLOAD_BATCH_SIZE`, `RAGFLOW_PARSE_BATCH_SIZE`, `RAGFLOW_MAX_INFLIGHT_DOCUMENTS` |
| Retry/Retention | `JOB_MAX_ATTEMPTS`, `JOB_RETRY_BASE_SECONDS`, `JOB_RETRY_MAX_SECONDS`, `JOB_HISTORY_RETENTION_DAYS` |
| Runtime | `CACHE_DIR`, `TEMP_DIR`, `ALLOW_OUTBOUND_INTERNET`, `DISABLE_TELEMETRY` |
| Startup | `CONNECTOR_AUTO_INIT_DB`, `CONNECTOR_STARTUP_CHECK`, `CONNECTOR_STARTUP_MAX_WAIT_SECONDS`, `CONNECTOR_STARTUP_SLEEP_SECONDS`, `CONNECTOR_BOOTSTRAP_CHECK_LIVE`, `CONNECTOR_FALLBACK_CACHE_DIR`, `CONNECTOR_FALLBACK_TEMP_DIR` |

Die Controller-Automationen `DISCOVERY_INTERVAL_SECONDS` und
`DELTA_SYNC_INTERVAL_SECONDS` sowie der Reconciler
`RECONCILE_INTERVAL_SECONDS` verwenden als sicheren Standard ebenfalls
`1800` Sekunden. Der aktive Intervall wird beim Start von Controller und
Reconciler geloggt. Manuelle Läufe sind unabhängig davon über
`connector sync-once`, `connector check-live`, `connector authz-sync-once` und
`connector openwebui-sync-once` möglich.

Für produktive Starts ist die kleinste robuste Konfiguration meistens besser:
erst Minimalpflicht setzen, `connector check-config` ausführen, dann gezielt
TLS, Dashboard, OpenWebUI oder Tuning ergänzen.
Der Default `CONNECTOR_STARTUP_CHECK=infra` prüft beim Start nur DB und Redis.
Seafile/RAGFlow werden über Dashboard-Health oder `connector check-live`
geprüft, damit die Installation nicht wegen externer TLS-, Auth- oder
Parserprobleme hängen bleibt.
