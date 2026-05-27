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
| `OPENWEBUI_REQUEST_TIMEOUT_SECONDS` | optional | Timeout für OpenWebUI- und Proxy-Aufrufe. |
| `OPENWEBUI_VERIFY_SSL`, `OPENWEBUI_CA_BUNDLE` | optional | TLS für Connector -> OpenWebUI Admin API. |
| `OPENWEBUI_FUNCTION_NAMESPACE` | optional | Präfix für erzeugte Tool-/Pipe-IDs. |
| `OPENWEBUI_SOURCE_PREVIEW_MODE` | optional | `ragflow_link`, `connector_viewer`, `citation_only` oder `disabled`; `connector_viewer` ist für auditierbare Citations mit Direktlink zur Fundstelle empfohlen. |
| `OPENWEBUI_PIPE_ANSWER_SYNTHESIS_ENABLED` | optional | Aktiviert einen OpenAI-kompatiblen Modell-Fallback, falls RAGFlow nur Retrieval-Treffer zurückgibt. |
| `OPENWEBUI_PIPE_ANSWER_LLM_BASE_URL` | optional | Base-URL des Fallback-Modells, z. B. `http://litellm:4000/v1`. |
| `OPENWEBUI_PIPE_ANSWER_LLM_MODEL` | optional | Modellname für die Antwortsynthese. |
| `OPENWEBUI_PIPE_ANSWER_LLM_API_KEY` | optional | Runtime-Secret für den Fallback; nicht in Repository-Dateien speichern. |
| `OPENWEBUI_SYNC_INTERVAL_SECONDS` | optional | Periodischer OpenWebUI-Sync im Controller. |
| `OPENWEBUI_DATASET_ALLOWLIST` | optional | CSV aus Repo-IDs oder Dataset-IDs für stufenweisen Rollout. |

## TLS/CA

| Variable | Pflicht | Wann |
| --- | --- | --- |
| `CONNECTOR_CERTS_HOST_DIR` | optional | wenn CA-Dateien per Compose nach `/certs` gemountet werden. |
| `CONNECTOR_CA_BUNDLE` | optional | gemeinsamer CA-Fallback für Seafile, RAGFlow und OpenWebUI. |
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

## Übliche optionale Betriebswerte

| Variable | Pflicht | Zweck |
| --- | --- | --- |
| `SEAFILE_INTERNAL_URL`, `RAGFLOW_INTERNAL_URL` | optional | abweichende interne URL für Container-zu-Container-Traffic. |
| `SEAFILE_SYNC_USER_EMAIL` | optional | Dokumentativer Sync-User-Hinweis; Token ist maßgeblich. |
| `SEAFILE_SKIP_ENCRYPTED_LIBRARIES`, `SEAFILE_SKIP_VIRTUAL_REPOS` | optional | Discovery-Filter für Seafile-Libraries. |
| `SEAFILE_FILE_URL_TEMPLATE` | optional | Browser-Link zum Originaldokument in OpenWebUI-Quellen. |
| `SEAFILE_REWRITE_DOWNLOAD_URLS`, `SEAFILE_DOWNLOAD_REWRITE_FROM`, `SEAFILE_DOWNLOAD_REWRITE_TO` | optional | Rewrite von Seafile-Download-URLs, z. B. von `127.0.0.1` auf Docker-DNS. |
| `RAGFLOW_TEMPLATE_DATASET_NAME` | optional | Default ist `connector_template`. |
| `RAGFLOW_TEMPLATE_AUTO_CREATE` | optional | Default `true`; fehlende Dataset-Templates werden beim Provisioning automatisch angelegt. |
| `RAGFLOW_TEMPLATE_REQUIRED` | optional | Default `true`; Healthcheck warnt nur noch, wenn Auto-Create deaktiviert ist und das Template fehlt. |
| `RAGFLOW_TEMPLATE_CHAT_NAME` | optional | Default `connector_template_chat`; Template-Chat für die OpenWebUI/RAGFlow-Chat-Defaults. |
| `RAGFLOW_TEMPLATE_REFRESH_SECONDS` | optional | Intervall für Aktualisierung der Dataset-Einstellungen. |
| `RAGFLOW_PUBLIC_BASE_URL`, `RAGFLOW_DOCUMENT_URL_TEMPLATE` | optional | öffentliche RAGFlow-Links in Quellen. |
| `CONNECTOR_DASHBOARD_ENABLED` | optional | Dashboard starten; für OpenWebUI-Proxy nötig. |
| `CONNECTOR_DASHBOARD_HOST`, `CONNECTOR_DASHBOARD_PORT` | optional | Bind-Adresse und Port im Container. |
| `CONNECTOR_DASHBOARD_PUBLISHED_PORT` | optional | Host-Portbindung in Compose. |
| `CONNECTOR_DASHBOARD_MAX_LOG_ENTRIES`, `CONNECTOR_DASHBOARD_MAX_EVENT_ENTRIES`, `CONNECTOR_DASHBOARD_MAX_SYNC_RUNS`, `CONNECTOR_DASHBOARD_LOG_PAGE_SIZE`, `CONNECTOR_DASHBOARD_MAX_FIELD_LENGTH` | optional | Speicher- und Anzeigegrenzen des Dashboards. |
| `CONNECTOR_DASHBOARD_AUTH_USERNAME`, `CONNECTOR_DASHBOARD_AUTH_PASSWORD` | optional | HTTP Basic Auth für Dashboard-UI und lesende Dashboard-API; beide Werte zusammen setzen. |
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
| Retry | `JOB_MAX_ATTEMPTS`, `JOB_RETRY_BASE_SECONDS`, `JOB_RETRY_MAX_SECONDS` |
| Runtime | `CACHE_DIR`, `TEMP_DIR`, `ALLOW_OUTBOUND_INTERNET`, `DISABLE_TELEMETRY` |
| Startup | `CONNECTOR_AUTO_INIT_DB`, `CONNECTOR_STARTUP_CHECK`, `CONNECTOR_STARTUP_MAX_WAIT_SECONDS`, `CONNECTOR_STARTUP_SLEEP_SECONDS`, `CONNECTOR_BOOTSTRAP_CHECK_LIVE`, `CONNECTOR_FALLBACK_CACHE_DIR`, `CONNECTOR_FALLBACK_TEMP_DIR` |

Für produktive Starts ist die kleinste robuste Konfiguration meistens besser:
erst Minimalpflicht setzen, `connector check-config` ausführen, dann gezielt
TLS, Dashboard, OpenWebUI oder Tuning ergänzen.
