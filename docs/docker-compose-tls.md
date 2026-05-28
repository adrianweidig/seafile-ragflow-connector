# Docker Compose TLS/CA-Setup

Für Unternehmensnetze mit HTTPS, optional eigener Root-CA und Portainer-Ziel ist
der schnellste Weg der Frage-Antwort-Assistent:

```bash
bash scripts/configure-enterprise-compose.sh
```

Er erzeugt `connector.env`, wählt die passenden Compose-Dateien und schreibt
Startskripte nach `output/enterprise-compose/`. Zusätzlich entstehen
`portainer-compose.yml` und `portainer.env`, die direkt in Portainer eingefügt
beziehungsweise importiert werden können. Wenn ein CA-Pfad angegeben wird,
prüft der Assistent die CA-Datei auf PEM-Format, `CA:TRUE` und Key-Usage für
Zertifikatssignatur, damit ein Server-Leaf nicht versehentlich als Root-CA
verwendet wird. Wenn der Pfad noch unbekannt ist, bleibt der CA-Block leer und
der Stack nutzt zunächst den System-Trust-Store.

Für Automatisierung kann derselbe Pfad ohne Rückfragen genutzt werden:

```bash
ENTERPRISE_NONINTERACTIVE=true \
ENTERPRISE_ASSUME_YES=true \
ENTERPRISE_MODE=external \
ENTERPRISE_WITH_OPENWEBUI=true \
ENTERPRISE_CA_HOST_FILE=/etc/pki/company-root-ca.pem \
ENTERPRISE_SEAFILE_BASE_URL=https://seafile.intern \
ENTERPRISE_RAGFLOW_BASE_URL=https://ragflow-api.intern \
ENTERPRISE_OPENWEBUI_BASE_URL=https://openwebui.intern \
ENTERPRISE_CONNECTOR_PUBLIC_BASE_URL=https://connector.intern \
bash scripts/configure-enterprise-compose.sh
```

Secrets wie `SEAFILE_ADMIN_TOKEN`, `SEAFILE_SYNC_USER_TOKEN`,
`RAGFLOW_API_KEY` und `OPENWEBUI_ADMIN_API_KEY` werden dabei als
Prozessumgebung oder interaktiv abgefragt und nicht in Skripte eingebettet.
`ENTERPRISE_CA_HOST_FILE` und `OPENWEBUI_ADMIN_API_KEY` dürfen leer bleiben:
ohne CA wird kein CA-Overlay verwendet, ohne OpenWebUI-Key bleibt der
OpenWebUI-Sync deaktiviert, bis der Admin den Key in der `.env` nachträgt.

Das bevorzugte Enterprise-Overlay bei eigener CA ist:

```bash
docker compose --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/enterprise-ca.compose.yml \
  config --quiet
```

Der tatsächliche Start erfolgt mit dem generierten `up.sh` oder analog mit
`up -d`.

Der Wizard setzt standardmäßig `CONNECTOR_STARTUP_CHECK=infra` und
`CONNECTOR_BOOTSTRAP_CHECK_LIVE=false`. Dadurch startet die Installation auch,
wenn externe Dienste oder RAGFlow-Parserressourcen zunächst nicht vollständig
bereit sind; `check-live.sh` prüft danach bewusst Seafile und RAGFlow.

## CA-Bundle mounten

Lege die interne CA-Chain als PEM-Datei auf dem Docker-Host ab und mounte sie
read-only in die Connector-Container:

```env
CONNECTOR_ENTERPRISE_CA_HOST_FILE=/etc/pki/company-root-ca.pem
CONNECTOR_ENTERPRISE_CA_CONTAINER_FILE=/certs/company-root-ca.pem
CONNECTOR_CA_BUNDLE=/certs/company-root-ca.pem
RAGFLOW_CA_BUNDLE=/certs/company-root-ca.pem
SEAFILE_CA_BUNDLE=/certs/company-root-ca.pem
OPENWEBUI_CA_BUNDLE=/certs/company-root-ca.pem
```

Das Overlay setzt zusätzlich:

```env
CONNECTOR_SYSTEM_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

Diese globalen Variablen sind Fallbacks für Bibliotheken, die nicht explizit
über die Connector-Settings konfiguriert werden. Für die Connector-eigenen
HTTPX-Clients bleiben die streckenspezifischen Variablen maßgeblich.
Der Entrypoint kopiert eine gesetzte `CONNECTOR_CA_BUNDLE` vor dem Drop auf den
unprivilegierten Benutzer nach `/usr/local/share/ca-certificates/` und führt
bei jedem Start `update-ca-certificates` aus. Ohne eigenes CA-Bundle wird der
System-Trust-Store trotzdem aktualisiert.

## OpenWebUI Pipe

Für OpenWebUI Pipe -> Connector Proxy muss das CA-Bundle auch im
OpenWebUI-Container liegen. Der Valve-Wert ist ein Pfad aus Sicht dieses
Containers:

```env
OPENWEBUI_PROXY_VERIFY_SSL=true
OPENWEBUI_PROXY_CA_BUNDLE=/certs/company-root-ca.pem
```

Wenn der Connector-Proxy über einen öffentlich vertrauenswürdigen Reverse Proxy
erreichbar ist, kann `OPENWEBUI_PROXY_CA_BUNDLE` leer bleiben.

Wenn `OPENWEBUI_PROXY_INTERNAL_BASE_URL` auf eine interne HTTP-Adresse wie
`http://connector-controller:8080` zeigt, muss die Pipe für diese Strecke kein
CA-Bundle im OpenWebUI-Container sehen. Bei HTTPS muss dieselbe CA dort unter
dem im Valve gesetzten Pfad verfügbar sein.

## App-spezifischer Trust vs. System-Trust

- `RAGFLOW_CA_BUNDLE`, `SEAFILE_CA_BUNDLE`, `OPENWEBUI_CA_BUNDLE` und
  `OPENWEBUI_PROXY_CA_BUNDLE` steuern genau eine Strecke.
- `CONNECTOR_CA_BUNDLE` dient als gemeinsamer Fallback für Connector-interne
  Seafile-, RAGFlow- und OpenWebUI-Admin-Clients.
- `SSL_CERT_FILE` und `REQUESTS_CA_BUNDLE` zeigen im Enterprise-Pfad auf den
  aktualisierten System-Trust-Store.
- `update-ca-certificates` läuft bei jedem Containerstart; ein gesetztes
  `CONNECTOR_CA_BUNDLE` wird vorher in den System-Trust-Store kopiert.

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

## Manuelles Referenzoverlay

`deploy/compose/docker-compose.tls-example.yml` bleibt als schlankes
Referenzoverlay erhalten. Es nutzt `CONNECTOR_TLS_CA_HOST_FILE` und den
Containerpfad `/certs/internal-ca.pem`. Für neue Installationen ist
`enterprise-ca.compose.yml` robuster, weil es alle Connector-Strecken
einheitlich setzt und keinen stillen Default auf eine nicht vorhandene CA-Datei
verwendet.

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
