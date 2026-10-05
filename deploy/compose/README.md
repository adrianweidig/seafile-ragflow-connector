# Docker Compose Anwendungsfälle

Dieser Ordner enthält direkt nutzbare Compose-Varianten für typische
Installationen. Für schnelle Installationen im Unternehmensnetz ist der
empfohlene Weg der Frage-Antwort-Assistent:

```bash
bash scripts/configure-enterprise-compose.sh
```

Er fragt Seafile-, RAGFlow-, OpenWebUI- und CA-Werte ab, erzeugt `connector.env`
und legt ausführbare Startskripte unter `output/enterprise-compose/` ab:

```bash
bash output/enterprise-compose/check-config.sh
bash output/enterprise-compose/check-portainer-config.sh
bash output/enterprise-compose/up.sh
bash output/enterprise-compose/check-live.sh
```

Für Portainer entstehen zusätzlich:

```text
output/enterprise-compose/portainer-compose.yml
output/enterprise-compose/portainer.env
```

In Portainer reicht dann: Compose-Inhalt einfügen, Env-Werte importieren,
Stack deployen. Secret-Werte stehen nur in der Env-Datei.
Für die erste Abnahme nach dem Start verweist die
[Admin-Erststart-Checkliste](../../docs/admin-first-start-checklist.md) auf die
konkreten Erfolgskriterien für `check-config`, `check-live`, Dashboard-Health
und erste Nutzerfreigabe.

Für manuelle Installationen bleibt die zentrale Datei im Repo-Root gültig:

```bash
cp connector.env.example connector.env
```

Ersetze in `connector.env` nur die Pflichtwerte für den gewählten Modus. Zu den
Seafile-/RAGFlow-Werten kommt genau ein State-Profil: `POSTGRES_PASSWORD` für
`bundled-state.compose.yml` oder `DATABASE_URL` und `REDIS_URL` für
`external-state.compose.yml`. Search gehört zum Standardprofil und ergänzt
`search.compose.yml`; Core-only lässt dieses Overlay weg. Der Wizard stellt
diese Kombinationen automatisch zusammen. Die älteren `*.stack.env.example`
Dateien bleiben als szenariospezifische Referenz erhalten.

Wenn Images lokal importiert wurden, müssen `CONNECTOR_IMAGE`,
`POSTGRES_IMAGE` und `REDIS_IMAGE` exakt auf die vorhandenen Image-Tags zeigen.
Mit `CONNECTOR_IMAGE_PULL_POLICY=never`, `POSTGRES_IMAGE_PULL_POLICY=never` und
`REDIS_IMAGE_PULL_POLICY=never` wird ein versehentlicher Pull verhindert.

## Welche Datei benutze ich?

| Anwendungsfall | Compose-Datei | Empfohlene Env-Datei | Zweck |
| --- | --- | --- | --- |
| Externe Dienste über Host/LAN | `external-services.compose.yml` | `../../connector.env.example` | Seafile, RAGFlow und optional OpenWebUI laufen außerhalb des Stacks, z. B. über Reverse Proxy, LAN-IP oder veröffentlichte Host-Ports. |
| Bestehendes Docker-Netz | `shared-network.compose.yml` | `../../connector.env.example` | Connector, Seafile, RAGFlow und optional OpenWebUI hängen im selben Docker-Netz und sprechen sich über Service-Namen an. |
| OpenWebUI zusätzlich anbinden | `openwebui.compose.yml` | `../../connector.env.example` | Wie Shared-Network, zusätzlich mit Dashboard/Proxy und aktivierter OpenWebUI-Synchronisation. |
| Gebündelter Connector-State | `bundled-state.compose.yml` als Overlay | `../../connector.env.example` | Startet PostgreSQL und Redis aus der Basisdatei und erzwingt `POSTGRES_PASSWORD`. |
| Externer Connector-State | `external-state.compose.yml` als Overlay | `../../connector.env.example` | Verlangt `DATABASE_URL` und `REDIS_URL`; die lokalen State-Dienste werden nicht gestartet. |
| Nutzernahe Search-Webseite | `search.compose.yml` als Standard-Overlay | `../../connector.env.example` | Ergänzt einen separaten Search-Service ohne Seafile-Admin-Token; vor RAGFlow wird die Authz-API des Cores gefragt. Weglassen ergibt Core-only. |
| Unternehmensnetz mit interner CA | `enterprise-ca.compose.yml` als Overlay | per `scripts/configure-enterprise-compose.sh` | Mountet die Unternehmens-Root-CA/Chain read-only, wenn ein CA-Pfad bekannt ist, und setzt alle Connector-TLS-Strecken auf verifizierte HTTPS-Kommunikation. |
| Manuelles TLS-Beispiel | `docker-compose.tls-example.yml` als Overlay | `../../connector.env.example` | Schlankes Referenz-Overlay für selbst konfigurierte CA-Mounts. Für neue Enterprise-Installationen ist `enterprise-ca.compose.yml` klarer. |

Die Compose-Varianten starten standardmäßig mit `CONNECTOR_STARTUP_CHECK=infra`.
Damit kommen Controller, Dashboard und Logs hoch, auch wenn Seafile, RAGFlow
oder RAGFlow-Parserressourcen noch nicht vollständig bereit sind. Für strikte
Starts kann `CONNECTOR_STARTUP_CHECK=live` gesetzt werden; die explizite
Live-Prüfung bleibt über `connector check-live` beziehungsweise das generierte
`check-live.sh` verfügbar.

## Startbeispiele

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/external-services.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/search.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/shared-network.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/search.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/search.compose.yml \
  up -d
```

Externe PostgreSQL-/Redis-Dienste statt der gebündelten State-Container:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/external-services.compose.yml \
  -f deploy/compose/external-state.compose.yml \
  -f deploy/compose/search.compose.yml \
  up -d
```

Core-only nutzt dieselben Basis- und State-Dateien, lässt aber
`search.compose.yml` vollständig weg. `SEARCH_SERVICE_ENABLED=false` ist nicht
der Abschaltweg für einen bereits definierten Container, weil dessen reguläres
Beenden sonst mit einer Restart-Policy kollidiert.

Enterprise-HTTPS/CA-Overlay:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/enterprise-ca.compose.yml \
  config --quiet
```

Manuelles TLS-Referenzoverlay:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/bundled-state.compose.yml \
  -f deploy/compose/docker-compose.tls-example.yml \
  config --quiet
```

## Wichtige Betriebsregel

Seafile ist immer die Quelle der Wahrheit. Diese Compose-Dateien können
Zielartefakte in RAGFlow und OpenWebUI erzeugen, reparieren oder löschen, aber
sie ändern keine Daten in Seafile.
