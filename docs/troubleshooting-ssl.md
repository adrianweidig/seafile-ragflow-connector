# SSL-/TLS-Troubleshooting

## Fehlermatrix

| Fehlerbild | Wahrscheinliche Ursache | Betroffene Strecke | Prüfung | Lösung |
| --- | --- | --- | --- | --- |
| `unable to get local issuer certificate` | CA fehlt | jeweilige HTTPS-Strecke | `openssl s_client` und HTTPX-Test | CA-Bundle mounten und passende `*_CA_BUNDLE`-Variable setzen |
| `self-signed certificate in certificate chain` | interne CA nicht vertraut | jeweilige HTTPS-Strecke | Chain prüfen | interne CA ins CA-Bundle aufnehmen |
| `certificate has expired` | abgelaufenes Zertifikat | Server-Zertifikat | Zertifikatsdatum prüfen | Zertifikat erneuern |
| `hostname mismatch` | SAN passt nicht zum Hostnamen | Server-Zertifikat | SAN prüfen | Zertifikat für den verwendeten Hostnamen ausstellen |
| `wrong version number` | HTTP statt HTTPS oder Port falsch | Ziel-URL | URL und Port prüfen | Schema oder Port korrigieren |
| `EOF occurred in violation of protocol` | TLS-, Proxy- oder Chain-Problem | jeweilige Strecke | Logs und OpenSSL prüfen | Proxy und Zertifikatskette korrigieren |
| `CERTIFICATE_VERIFY_FAILED` | allgemeiner Zertifikatsfehler | jeweilige HTTPS-Strecke | CA, Chain, Hostname prüfen | konkrete Ursache beheben |
| `CA bundle does not exist` | Containerpfad falsch oder Mount fehlt | HTTPX-Strecke | `docker compose exec ... ls -l /certs` | Mount oder Pfadvariable korrigieren |
| `CA bundle is not a file` | Pfad zeigt auf Verzeichnis | HTTPX-Strecke | `stat /certs/internal-ca.pem` | konkrete PEM-Datei setzen |

## OpenSSL-Prüfung

```bash
openssl s_client -connect ragflow.example.local:443 -servername ragflow.example.local -showcerts
openssl s_client -connect seafile.example.local:443 -servername seafile.example.local -showcerts
```

Ersetze die Beispielhostnamen durch die Hosts aus `RAGFLOW_BASE_URL`,
`SEAFILE_BASE_URL` und `OPENWEBUI_PROXY_PUBLIC_BASE_URL`. Der Hostname nach
`-servername` muss dem Hostnamen in der URL entsprechen.

## Python-/HTTPX-Prüfung

```bash
python - <<'PY'
import httpx
print(httpx.get("https://ragflow.example.local", timeout=10).status_code)
PY
```

Mit internem CA-Bundle:

```bash
python - <<'PY'
import httpx
print(httpx.get("https://ragflow.example.local", verify="/certs/internal-ca.pem", timeout=10).status_code)
PY
```

Im Container prüfen:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml exec connector-controller sh
ls -l /certs/internal-ca.pem
python - <<'PY'
import httpx
print(httpx.get("https://ragflow.example.local", verify="/certs/internal-ca.pem", timeout=10).status_code)
PY
```

## TLS-Healthcheck

Wenn das Dashboard aktiv ist:

```bash
curl -u admin:change-me-dashboard-password \
  http://127.0.0.1:18080/health/tls
```

Der Endpunkt prüft RAGFlow und Seafile separat und gibt keine Tokens aus. Ein
TLS-Fehler wird pro Upstream mit `error_type` und Hint wie
`RAGFLOW_CA_BUNDLE prüfen` oder `SEAFILE_CA_BUNDLE prüfen` markiert.

## Lokales TLS-Lab

Das Repository enthält unter `deploy/tls-lab` ein lokales HTTPS-Lab mit eigener
Root-CA und den Domains `rag.top.secret`, `seafile.top.secret`,
`connector.top.secret`, `search.top.secret`, `selfsigned-rag.top.secret`,
`wronghost.top.secret` und
`expired-rag.top.secret`.

Zertifikate erzeugen:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/tls-lab/generate-certs.ps1
```

Lab starten und prüfen:

```bash
docker compose -f deploy/tls-lab/docker-compose.yml up --build -d
docker compose -f deploy/tls-lab/docker-compose.yml run --rm tls-probe
```

Die Probe prüft Root-CA erfolgreich, fehlende CA fehlerhaft, CA-signiertes
Server-Leaf als nicht ausreichenden CA-Ersatz im Connector-Container, falsches
Leaf fehlerhaft, Self-signed-Leaf als Diagnosefall, Hostname-Mismatch und
abgelaufenes Zertifikat. Auf dem Host müssen die `.top.secret`-Domains nur dann
in die Hosts-Datei eingetragen werden, wenn Browser oder Host-Tools direkt
gegen die veröffentlichten Ports testen sollen.

## Browser vs. Backend

Browser-Fehler betreffen den Trust-Store des Benutzergeräts und die öffentliche
Preview-URL. Backend-Fehler betreffen den Trust-Store im Connector- oder
OpenWebUI-Container. Beide Umgebungen können unterschiedlich konfiguriert sein.

## Warum nicht VERIFY_SSL=false?

`VERIFY_SSL=false` deaktiviert Hostname- und Chain-Prüfung und macht
Man-in-the-Middle-Angriffe leichter. Der Connector loggt dafür eine Warnung.
Nutze diese Einstellung nur für Debug oder kurze Diagnose und behebe danach die
CA-Konfiguration.

## Integrationstestplan

Für eine vollständige TLS-E2E-Prüfung sollte eine Test-CA erzeugt werden, die
Zertifikate für Mock-RAGFlow, Mock-Seafile und den Connector-Reverse-Proxy
ausstellt. Danach werden diese Szenarien geprüft:

- Self-signed Ziel ohne CA-Bundle schlägt mit `CERTIFICATE_VERIFY_FAILED` fehl.
- Interne CA mit korrektem Bundle funktioniert.
- Exaktes Server-Leaf ist laufzeitabhängig und im Connector-Container kein
  ausreichender CA-Ersatz.
- Ein falsches Leaf-Zertifikat als CA-Bundle schlägt fehl.
- Falscher CA-Pfad schlägt bereits als Konfigurationsfehler fehl.
- Falsches CA-Bundle schlägt als Zertifikatsfehler fehl.
- Abgelaufenes Zertifikat und Hostname-Mismatch schlagen getrennt sichtbar fehl.
- Fehlende Intermediate-CA schlägt fehl; vollständige Chain funktioniert.
- `VERIFY_SSL=false` funktioniert technisch, erzeugt aber eine Warnung.
- OpenWebUI-Pipe-ähnlicher HTTPX-Client erreicht den Connector-Proxy nur, wenn
  das CA-Bundle im OpenWebUI-Container vorhanden ist.
