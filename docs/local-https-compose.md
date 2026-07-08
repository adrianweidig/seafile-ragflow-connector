# Lokaler WSL-Docker-Betrieb mit `connector.top.secret` und `search.top.secret`

Diese Anleitung beschreibt den produktionsnahen lokalen Betrieb des Connectors
auf einem Windows-PC mit Docker in WSL. Der Connector läuft per Docker Compose,
PostgreSQL und Redis bleiben in persistenten Docker-Volumes, und ein lokaler
Nginx-Edge stellt das Dashboard unter `https://connector.top.secret` und die
Wissenssuche unter `https://search.top.secret/search` bereit.

Seafile, RAGFlow und optional OpenWebUI bleiben bestehende Zielsysteme. Für
einen lokalen Gesamttest können sie im selben Docker-Netz laufen; der Connector
spricht sie dann über Service-Namen wie `http://seafile` und
`http://ragflow:9380` an.

## Dateien

| Datei | Zweck |
| --- | --- |
| `deploy/compose/shared-network.compose.yml` | Connector, PostgreSQL und Redis in einem bestehenden Docker-Netz. |
| `deploy/compose/external-services.compose.yml` | Connector, PostgreSQL und Redis mit extern erreichbarem Seafile/RAGFlow. |
| `deploy/compose/local-mocks.compose.yml` | Lokale HTTPS-Mocks für wiederholbare Smoke- und Update-Tests ohne externe Secrets. |
| `deploy/compose/connector-top-secret.compose.yml` | Overlay für lokalen HTTPS-Edge, aktiviertes Dashboard und Search-Service. |
| `deploy/compose/nginx/connector-top-secret.conf` | Nginx-Konfiguration für `connector.top.secret`. |
| `deploy/compose/nginx/search-top-secret.conf` | Nginx-Konfiguration für `search.top.secret`. |
| `deploy/tls-lab/generate-certs.ps1` | Erzeugt lokale Testzertifikate, inklusive `connector.top.secret` und `search.top.secret`. |

## Lokale Zertifikate erzeugen

Die Testzertifikate sind nur für lokale Entwicklung gedacht und werden nicht
eingecheckt:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/tls-lab/generate-certs.ps1
```

Danach liegen unter `deploy/tls-lab/certs/` unter anderem:

- `top-secret-root-ca.pem`
- `top-secret-root-ca.crl`
- `connector.top.secret.cert.pem`
- `connector.top.secret.key.pem`
- `search.top.secret.cert.pem`
- `search.top.secret.key.pem`

Der Edge erwartet diese Dateien im per `CONNECTOR_CERTS_HOST_DIR` gemounteten
Verzeichnis.
Bei den Compose-Dateien unter `deploy/compose/` werden relative Hostpfade aus
Sicht dieses Ordners aufgelöst. Für die vom Repo erzeugten Testzertifikate ist
deshalb `CONNECTOR_CERTS_HOST_DIR=../tls-lab/certs` der portable relative Wert.
Der Nginx-Edge liefert zusätzlich
`http://connector.top.secret/top-secret-root-ca.crl` und
`http://search.top.secret/top-secret-root-ca.crl` aus. Dadurch kann Windows
SChannel die lokale Test-Chain ohne `--ssl-no-revoke` prüfen.

## Windows-Hosts und Zertifikatsvertrauen

Die Windows-Hosts-Datei muss den lokalen Namen auf den Windows-Loopback zeigen:

```text
127.0.0.1 connector.top.secret
127.0.0.1 search.top.secret
```

Wenn der Eintrag fehlt, kann er in einer administrativen PowerShell ergänzt
werden:

```powershell
Add-Content -Path "$env:SystemRoot\System32\drivers\etc\hosts" -Value @"
127.0.0.1 connector.top.secret
127.0.0.1 search.top.secret
"@
```

Für Browser ohne Zertifikatswarnung muss die lokale Root-CA auf dem Windows-PC
als vertrauenswürdige Stammzertifizierungsstelle importiert werden. Das ist nur
für diese lokale Test-CA gedacht:

```powershell
Import-Certificate `
  -FilePath .\deploy\tls-lab\certs\top-secret-root-ca.pem `
  -CertStoreLocation Cert:\CurrentUser\Root
```

Alternativ kann für reine Diagnose mit `curl --cacert` geprüft werden, ohne den
Windows-Trust-Store zu verändern.

## Beispiel-`connector.env`

Für einen vollständig lokalen Smoke-Test mit HTTPS-Mocks:

```env
COMPOSE_PROJECT_NAME=seafile-ragflow-connector-local
CONNECTOR_IMAGE=seafile-ragflow-connector:local
CONNECTOR_IMAGE_PULL_POLICY=never
CONNECTOR_CERTS_HOST_DIR=../tls-lab/certs
CONNECTOR_CA_BUNDLE=/certs/top-secret-root-ca.pem
SSL_CERT_FILE=/certs/top-secret-root-ca.pem
REQUESTS_CA_BUNDLE=/certs/top-secret-root-ca.pem

CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080
CONNECTOR_DASHBOARD_AUTH_USERNAME=admin
CONNECTOR_DASHBOARD_AUTH_PASSWORD=change-me-dashboard-password
CONNECTOR_HTTPS_HTTP_BIND=127.0.0.1:80
CONNECTOR_HTTPS_HTTPS_BIND=127.0.0.1:443
AUTHZ_API_SHARED_SECRET=local-smoke-authz-secret
SEARCH_AUTHZ_SHARED_SECRET=local-smoke-authz-secret
SEARCH_SERVICE_PUBLISHED_PORT=127.0.0.1:18090

SEAFILE_BASE_URL=https://seafile.top.secret:8443
SEAFILE_ADMIN_TOKEN=local-smoke-token
SEAFILE_SYNC_USER_TOKEN=local-smoke-token
SEAFILE_CA_BUNDLE=/certs/top-secret-root-ca.pem
RAGFLOW_BASE_URL=https://rag.top.secret:8443
RAGFLOW_API_KEY=local-smoke-token
RAGFLOW_CA_BUNDLE=/certs/top-secret-root-ca.pem
RAGFLOW_TEMPLATE_DATASET_NAME=connector_template
SEARCH_RAGFLOW_BASE_URL=https://rag.top.secret:8443
SEARCH_RAGFLOW_API_KEY=local-smoke-token
SEARCH_RAGFLOW_CA_BUNDLE=/certs/top-secret-root-ca.pem
POSTGRES_PASSWORD=change-me-local-only

OPENWEBUI_INTEGRATION_ENABLED=false
OPENWEBUI_SYNC_MODE=disabled
CONNECTOR_STARTUP_CHECK=live
```

Für ein bestehendes gemeinsames Docker-Netz mit echten lokalen Diensten:

```env
COMPOSE_PROJECT_NAME=seafile-ragflow-connector-local
CONNECTOR_IMAGE=seafile-ragflow-connector:local
CONNECTOR_IMAGE_PULL_POLICY=never
CONNECTOR_DOCKER_NETWORK_NAME=ki_infra_seu_test
CONNECTOR_CERTS_HOST_DIR=../tls-lab/certs

CONNECTOR_DASHBOARD_ENABLED=true
CONNECTOR_DASHBOARD_PUBLISHED_PORT=127.0.0.1:18080
CONNECTOR_DASHBOARD_AUTH_USERNAME=admin
CONNECTOR_DASHBOARD_AUTH_PASSWORD=change-me-dashboard-password
CONNECTOR_HTTPS_HTTP_BIND=127.0.0.1:80
CONNECTOR_HTTPS_HTTPS_BIND=127.0.0.1:443
AUTHZ_API_SHARED_SECRET=change-me-authz-shared-secret
SEARCH_AUTHZ_SHARED_SECRET=change-me-authz-shared-secret
SEARCH_SERVICE_PUBLISHED_PORT=127.0.0.1:18090

SEAFILE_BASE_URL=http://seafile
SEAFILE_ADMIN_TOKEN=change-me
SEAFILE_SYNC_USER_TOKEN=change-me
RAGFLOW_BASE_URL=http://ragflow:9380
RAGFLOW_API_KEY=change-me
RAGFLOW_TEMPLATE_DATASET_NAME=connector_template
SEARCH_RAGFLOW_BASE_URL=http://ragflow:9380
SEARCH_RAGFLOW_API_KEY=change-me
POSTGRES_PASSWORD=change-me-local-only

OPENWEBUI_INTEGRATION_ENABLED=false
OPENWEBUI_SYNC_MODE=disabled
CONNECTOR_STARTUP_CHECK=live
```

`change-me`-Werte müssen durch lokale Testtokens ersetzt werden. Echte Tokens,
Passwörter und API-Keys gehören nur in die nicht getrackte `connector.env` oder
in Portainer-/Docker-Secrets.

## Build, Start und Healthcheck

```powershell
wsl docker build `
  -t seafile-ragflow-connector:local `
  -f deploy/docker/Dockerfile .

wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  config --quiet

wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  up -d
```

Prüfen:

```powershell
wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  ps

wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  exec connector-controller connector check-live

curl.exe --cacert .\deploy\tls-lab\certs\top-secret-root-ca.pem `
  https://connector.top.secret/api/health

curl.exe --cacert .\deploy\tls-lab\certs\top-secret-root-ca.pem `
  https://search.top.secret/search
```

Ohne `--cacert` muss der letzte Befehl erst funktionieren, nachdem die Root-CA
in Windows vertraut ist.

## Image-Update testen

Der Update-Test darf PostgreSQL-, Redis- und Cache-Volumes nicht löschen. Der
Updatepfad ersetzt nur die Connector-Container:

```powershell
wsl docker build `
  -t seafile-ragflow-connector:local-next `
  -f deploy/docker/Dockerfile .
```

Danach in `connector.env` setzen:

```env
CONNECTOR_IMAGE=seafile-ragflow-connector:local-next
CONNECTOR_IMAGE_PULL_POLICY=never
```

Update ausführen:

```powershell
wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  up -d --no-deps connector-controller connector-worker connector-reconciler

wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  up -d --no-deps connector-search

wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  restart connector-https-edge

curl.exe --cacert .\deploy\tls-lab\certs\top-secret-root-ca.pem `
  https://connector.top.secret/api/health

curl.exe --cacert .\deploy\tls-lab\certs\top-secret-root-ca.pem `
  https://search.top.secret/search
```

Der Edge-Restart ist bewusst Teil des lokalen Update-Runbooks, weil Nginx die
Docker-DNS-Auflösung des neu erstellten Controller-Containers sonst weiter
cachen kann.

Rollback erfolgt durch Zurücksetzen von `CONNECTOR_IMAGE` auf das vorherige
Tag und denselben `up -d --no-deps ...`-Befehl. Die persistenten Volumes bleiben
unverändert.

## Stoppen ohne Datenverlust

```powershell
wsl docker compose --env-file connector.env `
  -f deploy/compose/external-services.compose.yml `
  -f deploy/compose/local-mocks.compose.yml `
  -f deploy/compose/search.compose.yml `
  -f deploy/compose/connector-top-secret.compose.yml `
  down
```

Kein `down -v` verwenden, solange Connector-State, Redis-AOF oder Cache-Daten
erhalten bleiben sollen.
