# Docker Compose TLS/CA-Setup

Das TLS-Beispiel ist als Compose-Overlay abgelegt:

```bash
docker compose --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/docker-compose.tls-example.yml \
  config --quiet
```

Der tatsächliche Start erfolgt analog mit `up -d`.

## CA-Bundle mounten

Lege die interne CA-Chain als PEM-Datei auf dem Docker-Host ab und mounte sie
read-only in die Connector-Container:

```env
CONNECTOR_TLS_CA_HOST_FILE=./deploy/certs/internal-ca.pem
RAGFLOW_CA_BUNDLE=/certs/internal-ca.pem
SEAFILE_CA_BUNDLE=/certs/internal-ca.pem
OPENWEBUI_CA_BUNDLE=/certs/internal-ca.pem
```

Das Overlay setzt zusätzlich:

```env
SSL_CERT_FILE=/certs/internal-ca.pem
REQUESTS_CA_BUNDLE=/certs/internal-ca.pem
```

Diese globalen Variablen sind Fallbacks für Bibliotheken, die nicht explizit
über die Connector-Settings konfiguriert werden. Für die Connector-eigenen
HTTPX-Clients bleiben die streckenspezifischen Variablen maßgeblich.

## OpenWebUI Pipe

Für OpenWebUI Pipe -> Connector Proxy muss das CA-Bundle auch im
OpenWebUI-Container liegen. Der Valve-Wert ist ein Pfad aus Sicht dieses
Containers:

```env
OPENWEBUI_PROXY_VERIFY_SSL=true
OPENWEBUI_PROXY_CA_BUNDLE=/certs/internal-ca.pem
```

Wenn der Connector-Proxy über einen öffentlich vertrauenswürdigen Reverse Proxy
erreichbar ist, kann `OPENWEBUI_PROXY_CA_BUNDLE` leer bleiben.

## App-spezifischer Trust vs. System-Trust

- `RAGFLOW_CA_BUNDLE`, `SEAFILE_CA_BUNDLE`, `OPENWEBUI_CA_BUNDLE` und
  `OPENWEBUI_PROXY_CA_BUNDLE` steuern genau eine Strecke.
- `CONNECTOR_CA_BUNDLE` dient als gemeinsamer Fallback für Connector-interne
  Seafile-, RAGFlow- und OpenWebUI-Admin-Clients.
- `SSL_CERT_FILE` und `REQUESTS_CA_BUNDLE` sind globale Fallbacks und ersetzen
  nicht die streckenspezifische Konfiguration.
- Ein systemweiter Trust-Store im Image ist möglich, erzeugt aber mehr
  Betriebszustand. Ein explizites read-only CA-Bundle ist reproduzierbarer.

## Docker Secrets und mTLS

CA-Zertifikate sind öffentliches Trust-Material und können read-only gemountet
werden. Private mTLS-Schlüssel sind sensibel und sollten als Docker Secrets
oder über geschützte Host-Pfade bereitgestellt werden. Beispielvariablen:

```env
RAGFLOW_CLIENT_CERT_FILE=/run/secrets/ragflow-client-cert.pem
RAGFLOW_CLIENT_KEY_FILE=/run/secrets/ragflow-client-key.pem
SEAFILE_CLIENT_CERT_FILE=/run/secrets/seafile-client-cert.pem
SEAFILE_CLIENT_KEY_FILE=/run/secrets/seafile-client-key.pem
```

Die Anwendung validiert gesetzte Pfade, loggt aber keine Schlüsselpfade als
Secret-Inhalt und gibt keine Schlüsselwerte aus.

## Corporate Proxy oder MITM-CA

Wenn ein Unternehmensproxy TLS aufbricht, muss dessen Root-CA in das CA-Bundle,
das für die betroffene Strecke verwendet wird. Für Docker Pulls ist zusätzlich
die Docker-Engine-Konfiguration auf dem Host relevant; Container-Variablen wie
`SSL_CERT_FILE` helfen dort nicht.

## Lokales TLS-Lab

Für Tests ohne echte Seafile-/RAGFlow-Systeme gibt es ein isoliertes Compose-Lab:

```bash
sh deploy/tls-lab/generate-certs.sh
docker compose -f deploy/tls-lab/docker-compose.yml up --build -d
docker compose -f deploy/tls-lab/docker-compose.yml run --rm tls-probe
```

Alle Mock-Ziele laufen über HTTPS und eigene `.top.secret`-Domains. Das Lab
zeigt auch, dass ein CA-signiertes Server-Leaf im Connector-Container nicht als
CA-Ersatz reicht. Die Root-CA oder vollständige CA-Chain bleibt der richtige
Betriebswert für `*_CA_BUNDLE`.

## Produktionshinweise

`VERIFY_SSL=false` ist nur für Debug oder kurze Diagnose vorgesehen. Es gibt
keinen automatischen Fallback auf unsichere TLS-Prüfung. Ein fehlendes oder
falsches CA-Bundle schlägt sichtbar fehl, damit Zertifikatsprobleme nicht
verdeckt werden.
