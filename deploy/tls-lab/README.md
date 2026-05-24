# TLS-Lab für lokale CA- und Zertifikatstests

Dieses Lab erzeugt eine lokale Root-CA und HTTPS-Testziele mit den Domains:

- `rag.top.secret`
- `seafile.top.secret`
- `connector.top.secret`
- `selfsigned-rag.top.secret`
- `wronghost.top.secret`
- `expired-rag.top.secret`

Ziel ist, die produktiven Fehlerbilder reproduzierbar zu prüfen:

- Zugriff ohne CA-Bundle schlägt fehl.
- Zugriff mit Root-CA-Bundle funktioniert.
- Zugriff mit nur dem exakt passenden CA-signierten Server-Zertifikat als
  Trust-Bundle ist laufzeitabhängig und reicht im Connector-Container nicht als
  CA-Ersatz.
- Zugriff mit einem falschen Leaf-Zertifikat als Trust-Bundle schlägt fehl.
- Zugriff auf einen Hostnamen, der nicht im SAN des Zertifikats steht, schlägt
  als Hostname-Mismatch fehl.

Die Zertifikate sind reine lokale Testartefakte und werden in `certs/`
generiert. Dieser Ordner ist absichtlich in `.gitignore` eingetragen.

## Zertifikate erzeugen

Windows/PowerShell ohne OpenSSL:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/tls-lab/generate-certs.ps1
```

Linux/macOS:

```bash
sh deploy/tls-lab/generate-certs.sh
```

Beide Wrapper nutzen `generate_certs.py`. Dadurch ist kein lokales OpenSSL
erforderlich; in einer `uv`-Umgebung wird automatisch `uv run python` genutzt.

Erzeugte Dateien:

| Datei | Zweck |
| --- | --- |
| `certs/top-secret-root-ca.pem` | Root-CA-Bundle für `*_CA_BUNDLE`. |
| `certs/rag.top.secret.cert.pem` | Leaf-Zertifikat für RAGFlow-Mock. |
| `certs/rag.top.secret.key.pem` | Test-Private-Key für RAGFlow-Mock. |
| `certs/seafile.top.secret.cert.pem` | Leaf-Zertifikat für Seafile-Mock. |
| `certs/seafile.top.secret.key.pem` | Test-Private-Key für Seafile-Mock. |
| `certs/connector.top.secret.cert.pem` | Leaf-Zertifikat für Connector-Proxy-Mock. |
| `certs/connector.top.secret.key.pem` | Test-Private-Key für Connector-Proxy-Mock. |
| `certs/selfsigned-rag.top.secret.cert.pem` | Self-signed Server-Zertifikat für Vergleichstests. |
| `certs/wronghost.top.secret.cert.pem` | Zertifikat mit absichtlich falschem SAN. |
| `certs/expired-rag.top.secret.cert.pem` | Abgelaufenes CA-signiertes Server-Zertifikat. |

## Compose-Lab starten

```bash
docker compose -f deploy/tls-lab/docker-compose.yml up --build -d
docker compose -f deploy/tls-lab/docker-compose.yml run --rm tls-probe
```

Die Compose-Netzwerk-Aliase lösen die `.top.secret`-Domains innerhalb des Labs
auf. Für Browser-Tests auf dem Host müssen die Domains zusätzlich lokal auf
`127.0.0.1` zeigen, zum Beispiel über `/etc/hosts` oder die Windows
`hosts`-Datei:

```text
127.0.0.1 rag.top.secret
127.0.0.1 seafile.top.secret
127.0.0.1 connector.top.secret
```

## Erwartete Bewertung

Für eine von einer internen CA signierte Server-Chain ist das Root- oder
vollständige CA-Bundle der richtige Wert für `RAGFLOW_CA_BUNDLE`,
`SEAFILE_CA_BUNDLE` und `OPENWEBUI_PROXY_CA_BUNDLE`. Das reine Leaf-Zertifikat
des Servers ist nicht der empfohlene Betriebszustand und reicht im
Connector-Container nicht als CA-Ersatz. Einzelne lokale Python/OpenSSL-
Versionen können ein exakt passendes Leaf als direkten Trust-Anker akzeptieren;
darauf darf sich das Deployment nicht verlassen. Ein falsches Leaf-Zertifikat
hilft nicht. Wenn ein einzelnes self-signed Server-Zertifikat direkt als
Trust-Bundle funktioniert, ist das ebenfalls eine Diagnose- oder Lab-Variante,
aber keine gute Betriebsstrategie: Zertifikatserneuerung und Hostwechsel
brechen dann sofort den Trust.
