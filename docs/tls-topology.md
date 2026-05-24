# TLS-Topologie

Dieses Projekt nutzt mehrere getrennte HTTPS-Strecken. Jede Strecke hat eine
eigene Trust-Entscheidung; ein funktionierendes Zertifikat im Browser bedeutet
nicht automatisch, dass HTTPX im Container dieselbe CA kennt.

| Strecke | Client | Ziel | Validierung | Relevante Variablen |
| --- | --- | --- | --- | --- |
| OpenWebUI Pipe -> Connector Proxy | OpenWebUI-Container oder Pipe-Runtime | `OPENWEBUI_PROXY_INTERNAL_BASE_URL` oder `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | HTTPX in der Pipe | `OPENWEBUI_PROXY_VERIFY_SSL`, `OPENWEBUI_PROXY_CA_BUNDLE`; Aliase: `CONNECTOR_PROXY_VERIFY_SSL`, `CONNECTOR_PROXY_CA_BUNDLE` |
| Connector Proxy -> RAGFlow | `connector-controller` | `RAGFLOW_INTERNAL_URL` oder `RAGFLOW_BASE_URL` | HTTPX im Connector | `RAGFLOW_VERIFY_SSL`, `RAGFLOW_CA_BUNDLE`, optional `CONNECTOR_CA_BUNDLE` |
| Connector Proxy -> Seafile | `connector-controller` und Sync-Clients | `SEAFILE_INTERNAL_URL` oder `SEAFILE_BASE_URL` | HTTPX im Connector | `SEAFILE_VERIFY_SSL`, `SEAFILE_CA_BUNDLE`, optional `CONNECTOR_CA_BUNDLE` |
| Browser -> Preview-Seite | Nutzerbrowser | `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | Browser-Trust-Store | öffentlich vertrautes Zertifikat oder intern ausgerollte CA |
| Preview -> Originaldatei | Browser über Link oder Reverse Proxy | Wert aus `SEAFILE_FILE_URL_TEMPLATE` | Browser oder vorgeschalteter Proxy | `SEAFILE_FILE_URL_TEMPLATE`, Reverse-Proxy-Zertifikat |
| Docker Host -> Registry | Docker Engine | GHCR oder interne Registry | Host-/Docker-Trust-Store | Corporate Proxy, MITM-CA, Registry-Konfiguration |

## CA-Zuständigkeit

- Für RAGFlow und Seafile muss die CA im Connector-Container existieren. Der
  Standardpfad im TLS-Beispiel ist `/certs/internal-ca.pem`.
- Für OpenWebUI Pipe -> Connector Proxy muss dieselbe oder eine passende CA im
  OpenWebUI-Container existieren. Der Pfad in `OPENWEBUI_PROXY_CA_BUNDLE` wird
  aus Sicht des OpenWebUI-Containers ausgewertet, nicht aus Sicht des
  Connector-Containers.
- Für Browser-Preview-Links entscheidet ausschließlich der Browser. Wenn der
  Connector-Proxy intern signiert ist, muss die interne CA auf den
  Benutzergeräten vertraut sein oder ein öffentlich vertrauenswürdiger Reverse
  Proxy davor stehen.
- Für Docker Pulls entscheidet Docker Engine auf dem Host, nicht die Python-App.

## HTTPX-Strecken

HTTPX prüft Zertifikate auf diesen Pfaden:

- `RAGFLOW_VERIFY_SSL` und `RAGFLOW_CA_BUNDLE`: RAGFlow-API, Chat Completion,
  Retrieval und TLS-Healthcheck.
- `SEAFILE_VERIFY_SSL` und `SEAFILE_CA_BUNDLE`: Seafile Admin API, Sync API,
  Download-URLs und TLS-Healthcheck.
- `OPENWEBUI_VERIFY_SSL` und `OPENWEBUI_CA_BUNDLE`: optionale OpenWebUI Admin
  API für Tool-/Pipe-Sync.
- `OPENWEBUI_PROXY_VERIFY_SSL` und `OPENWEBUI_PROXY_CA_BUNDLE`: generierte
  OpenWebUI Tools und Pipes beim Aufruf des Connector-Proxys.

Ein leerer CA-Bundle-Pfad bedeutet: HTTPX nutzt den Standard-Trust-Store der
Python-Umgebung. Ein gesetzter Pfad muss existieren und eine Datei sein.

## Hostnamen

Die konkreten Hostnamen kommen zur Laufzeit aus den Base-URL-Variablen. Das
Server-Zertifikat muss den Hostnamen enthalten, der tatsächlich in der URL
verwendet wird, zum Beispiel `ragflow.example.local`, `seafile.example.local`
oder `connector-controller` bei internen Docker-DNS-Namen.
