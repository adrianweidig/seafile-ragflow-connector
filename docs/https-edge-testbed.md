# Lokales HTTPS-Edge-Testbed

Dieses Testbed wurde genutzt, um den Connector in einer produktionsnahen
HTTPS-Topologie gegen bestehende lokale Seafile-, RAGFlow- und OpenWebUI-
Container zu prüfen.

## Topologie

Der temporäre Compose-Stack liegt lokal außerhalb des Repositories:

```text
/tmp/codex-https-edge/docker-compose.yml
```

Er wurde absichtlich nicht als produktive Deploy-Datei in das Repository
übernommen. Der Stack dient als lokale Prüfstruktur, um mit echter Root-CA,
echten HTTPS-Namen und den bestehenden lokalen Diensten abzuleiten, welche
Connector-Einstellungen und Codepfade produktionsrelevant sind.

Er enthält:

- `root-ca`: erzeugt eine lokale Root-CA und ein Server-Zertifikat für die
  `.top.secret`-Domains.
- `nginx`: terminiert TLS auf `127.0.0.1:24443` und hängt im Docker-Netz
  `ki_infra_seu_test`.
- `tls-client`: optionaler Curl-Testclient im selben Docker-Netz.

Verwendete HTTPS-Namen:

| Domain | Ziel |
| --- | --- |
| `https://seafile.top.secret` | Seafile API und Download-Pfade |
| `https://rag.top.secret` | RAGFlow API |
| `https://openwebui.top.secret` | OpenWebUI Admin API |
| `https://connector.top.secret` | Connector-Dashboard und OpenWebUI-Proxy |

Der Connector lief im Test mit:

```env
SEAFILE_BASE_URL=https://seafile.top.secret
RAGFLOW_BASE_URL=https://rag.top.secret
OPENWEBUI_BASE_URL=https://openwebui.top.secret
OPENWEBUI_PROXY_INTERNAL_BASE_URL=https://connector.top.secret
OPENWEBUI_PROXY_PUBLIC_BASE_URL=https://connector.top.secret:24443

CONNECTOR_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
SEAFILE_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
RAGFLOW_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
OPENWEBUI_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
OPENWEBUI_PROXY_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
SSL_CERT_FILE=/certs/top-secret-edge-root-ca.pem
REQUESTS_CA_BUNDLE=/certs/top-secret-edge-root-ca.pem
```

Die Root-CA wurde read-only nach `/certs` in Connector und OpenWebUI gemountet.

Alle beteiligten Container wurden über Docker Compose gestartet. Der Container-
Audit erfolgte über das Compose-Label `com.docker.compose.project`; laufende
Standalone-Container ohne Compose-Projektlabel wurden im Teststand nicht
vorgefunden. Dadurch tauchen die Stacks in Portainer unter den jeweiligen
Compose-/Stack-Projekten auf und sind dort verwaltbar.

## Nachgewiesene Pfade

Diese Pfade wurden aktiv geprüft:

| Strecke | Ergebnis |
| --- | --- |
| Host -> `https://connector.top.secret:24443/api/health` | HTTPS mit CA ok |
| Connector -> `https://seafile.top.secret` | `/api/health` ok |
| Connector -> `https://rag.top.secret` | `/api/health` ok |
| Connector -> `https://openwebui.top.secret` | Functions API ok |
| Connector `/health/tls` -> Seafile | `tls: ok`, HTTP 200 |
| Connector `/health/tls` -> RAGFlow | `tls: ok`, HTTP 200 |
| OpenWebUI-Container -> `https://connector.top.secret/api/health` | HTTPS mit CA ok |
| OpenWebUI Pipe -> Connector Proxy `/api/openwebui/proxy/chat` | HTTP 200, Quellenantwort |

Zusätzlich wurden direkte Container-Probes aus dem Connector- und dem
OpenWebUI-Container gegen die `.top.secret`-Ziele ausgeführt. RAGFlow liefert
auf `/` erwartbar `404`, der Fehler tritt aber erst nach erfolgreichem TLS-
Handshake und CA-Validierung auf; die API-Pfade sind über `/api/health` und
`/health/tls` geprüft.

Ohne CA-Bundle schlägt der Host-Test mit
`unable to get local issuer certificate` fehl. Damit ist bestätigt, dass der
Test tatsächlich die interne Root-CA validiert und nicht versehentlich TLS-
Prüfung deaktiviert.

Verwendete Prüfkommandos, jeweils mit den realen lokalen Pfaden und ohne
Secrets in der Ausgabe:

```bash
curl --cacert /tmp/codex-https-edge/certs-export/top-secret-edge-root-ca.pem \
  --resolve connector.top.secret:24443:127.0.0.1 \
  https://connector.top.secret:24443/api/health

curl http://127.0.0.1:18080/health/tls

docker exec ki-test-openwebui sh -lc \
  'python -c "import urllib.request; print(urllib.request.urlopen(\"https://connector.top.secret/api/health\", timeout=10).status)"'
```

Für OpenWebUI-Pipe-Tests wurde der generierte Pipe-Valve-Satz genutzt. Der
Proxy-Shared-Secret-Wert wurde dabei nur aus der lokalen Env gelesen und nicht
ausgegeben.

## Abgeleitete Connector-Anpassung

Der normale Dashboard-Dependency-Healthcheck nutzte ursprünglich denselben sehr
kurzen Timeout für alle Dienste. Im HTTPS-Reverse-Proxy-Test war RAGFlow über
den TLS-Healthcheck stabil erreichbar, konnte im normalen `/api/health` aber
sporadisch wegen Timeout als Fehler erscheinen.

Der Connector nutzt deshalb weiterhin kurze Timeouts für schnelle lokale Checks
wie Datenbank, Redis und Seafile, aber einen separaten RAGFlow-Health-Timeout
von 3 Sekunden. Dadurch bleibt das Dashboard reaktionsschnell und erzeugt im
HTTPS-Proxy-Betrieb keine falschen RAGFlow-Fehler.

Zusätzlich hat der Test gezeigt:

- Das CA-Bundle muss in jedem Container liegen, der den jeweiligen HTTPS-Namen
  validiert. Für `OpenWebUI Pipe -> Connector Proxy` reicht es nicht, die CA nur
  im Connector zu mounten.
- Die OpenWebUI-Pipe-Valves müssen den CA-Pfad aus Sicht des OpenWebUI-
  Containers enthalten, z. B. `/certs/top-secret-edge-root-ca.pem`.
- Seafile kann hinter einem lokalen Reverse Proxy mit `400 Bad Request`
  reagieren, wenn Host-/Service-URL-Konfiguration und Proxy-Header nicht
  zusammenpassen. Im Test wurde `Host: seafile` zum Upstream gesetzt.
- Wenn der Connector-Controller neu erstellt wird, muss der lokale Nginx-Proxy
  die Docker-DNS-Auflösung aktualisieren. Ein Restart des Nginx-Compose-
  Services ist für dieses temporäre Testbed ausreichend.

## OpenWebUI API-Key-Hinweis

Im lokalen Test war `ENABLE_API_KEYS=true` als Container-Env gesetzt, die
persistente OpenWebUI-Konfiguration enthielt aber
`auth.enable_api_keys=false`. Dadurch wurde der Connector über HTTPS korrekt zu
OpenWebUI geroutet, bekam aber `403` beziehungsweise vorher `401`.

Für echte Deployments müssen beide Bedingungen erfüllt sein:

- OpenWebUI API-Keys sind persistent aktiviert.
- `OPENWEBUI_ADMIN_API_KEY` ist ein gültiger Admin-API-Key.

Das ist eine OpenWebUI-Konfigurationsanforderung, kein Connector-TLS-Problem.

## Einschränkung

Das Testbed nutzt Nginx als TLS-Edge vor bestehenden HTTP-Diensten. Damit sind
alle getesteten Client-zu-Service-Strecken HTTPS-basiert. Der interne Hop vom
Nginx-Proxy zum jeweiligen Zielcontainer bleibt HTTP, solange Seafile,
RAGFlow, OpenWebUI und der Connector nicht selbst native TLS-Listener
bereitstellen. Wenn diese letzte interne Proxy-Strecke ebenfalls TLS sein muss,
braucht jeder Zielcontainer entweder native HTTPS-Konfiguration oder einen
lokalen TLS-Sidecar mit mTLS/HTTPS zum Upstream.
