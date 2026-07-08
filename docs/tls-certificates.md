# TLS-Zertifikate und CA-Bundles

## Zertifikatstypen

- Server-Zertifikat: liegt auf Seafile, RAGFlow, OpenWebUI oder dem
  Connector-Reverse-Proxy. Es muss den genutzten Hostnamen im SAN enthalten.
- CA-Zertifikat: Root-CA oder Intermediate-CA, der Clients vertrauen. Dieses
  Zertifikat gehört in das CA-Bundle.
- Client-Zertifikat: optional für mTLS. Es identifiziert den Client gegenüber
  dem Server und wird zusammen mit einem privaten Schlüssel genutzt.

Für Trust-Bundles soll die interne CA oder die vollständige CA-Chain verwendet
werden, nicht das Leaf-Zertifikat des Servers. Leaf-Zertifikate werden häufiger
erneuert und sind nur für einen konkreten Host gültig; die CA-Chain bleibt die
stabilere Vertrauenswurzel.

Das lokale TLS-Lab unter `deploy/tls-lab` zeigt die technische Nuance:
Ein exakt passendes Server-Leaf kann in Python/OpenSSL als direkter Trust-Anker
funktionieren. Der produktionsnähere Connector-Container-Test akzeptiert das
CA-signierte Leaf jedoch nicht als CA-Ersatz. Für Deployments gilt deshalb:
Root-CA oder vollständige CA-Chain verwenden. Ein anderes Leaf-Zertifikat
derselben Umgebung ersetzt die CA ebenfalls nicht, und Zertifikatserneuerungen
würden sofort den Trust brechen.

## PEM-Bundle

Das erwartete Format ist PEM:

```text
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
```

Wenn eine Intermediate-CA verwendet wird, enthält das Bundle Root-CA und
Intermediate-CA. Der typische Containerpfad ist:

```text
/certs/internal-ca.pem
```

Im Repository liegt nur die Anleitung unter `deploy/certs/README.md`; echte
produktive Zertifikate und private Schlüssel gehören nicht ins Repository.

## Prüfung

CA-Datei prüfen:

```bash
openssl x509 -in deploy/certs/internal-ca.pem -noout -subject -issuer -dates
```

Server-Chain prüfen:

```bash
openssl s_client -connect ragflow.example.local:443 -servername ragflow.example.local -showcerts
openssl s_client -connect seafile.example.local:443 -servername seafile.example.local -showcerts
```

Die Beispielhostnamen sind durch die Hosts aus `RAGFLOW_BASE_URL`,
`SEAFILE_BASE_URL` oder `OPENWEBUI_PROXY_PUBLIC_BASE_URL` zu ersetzen.

## Lokales TLS-Lab

Für reproduzierbare Tests mit lokaler Root-CA und `.top.secret`-Domains:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/tls-lab/generate-certs.ps1
docker compose -f deploy/tls-lab/docker-compose.yml up --build -d
docker compose -f deploy/tls-lab/docker-compose.yml run --rm tls-probe
```

Das Lab erzeugt unter `deploy/tls-lab/certs` Testzertifikate für
`rag.top.secret`, `seafile.top.secret`, `connector.top.secret`,
`search.top.secret`,
`selfsigned-rag.top.secret`, `wronghost.top.secret` und
`expired-rag.top.secret`. Die Zertifikate sind reine Testartefakte.

## Hostname und SAN

HTTPX und Browser prüfen den Hostnamen aus der URL gegen das SAN-Feld des
Server-Zertifikats. Ein Zertifikat für `seafile.example.local` gilt nicht für
`seafile`, `localhost` oder eine IP-Adresse, außer diese Namen sind ebenfalls
im SAN enthalten.

## Erneuerung

Bei Zertifikatserneuerung muss in der Regel nur das Server-Zertifikat am
Zielsystem ersetzt werden. Das CA-Bundle im Connector oder OpenWebUI muss nur
dann aktualisiert werden, wenn sich Root- oder Intermediate-CA ändern.

Nach Änderungen:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml config --quiet
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml restart connector-controller connector-worker connector-reconciler
```

## mTLS

Die Konfiguration kennt vorbereitete Variablen für mTLS-Dateien:

```env
RAGFLOW_CLIENT_CERT_FILE=
RAGFLOW_CLIENT_KEY_FILE=
SEAFILE_CLIENT_CERT_FILE=
SEAFILE_CLIENT_KEY_FILE=
CONNECTOR_PROXY_CLIENT_CERT_FILE=
CONNECTOR_PROXY_CLIENT_KEY_FILE=
```

Diese Pfade werden validiert, wenn sie gesetzt sind. Die HTTPX-Clients nutzen
sie aktuell noch nicht automatisch als Client-Zertifikat, weil die vorhandenen
RAGFlow-/Seafile- und OpenWebUI-Proxy-Flüsse bisher kein mTLS-Profil erzwingen.
Private Key-Dateien dürfen nicht geloggt und nicht ins Repository geschrieben
werden; für produktive Deployments sind Docker Secrets oder geschützte
read-only Mounts vorzuziehen.
