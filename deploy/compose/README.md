# Docker Compose Anwendungsfälle

Dieser Ordner enthält direkt nutzbare Compose-Varianten für typische
Installationen. Für normale externe Installationen ist der empfohlene Weg die
zentrale Datei im Repo-Root:

```bash
cp connector.env.example connector.env
```

Ersetze in `connector.env` nur die Pflichtwerte für den gewählten Modus. Für
den Minimalbetrieb sind das `SEAFILE_BASE_URL`, `SEAFILE_ADMIN_TOKEN`,
`SEAFILE_SYNC_USER_TOKEN`, `RAGFLOW_BASE_URL`, `RAGFLOW_API_KEY` und
`POSTGRES_PASSWORD` oder alternativ `DATABASE_URL`. Die älteren
`*.stack.env.example` Dateien bleiben als szenariospezifische Referenz
erhalten.

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
| Internes CA-Bundle | `docker-compose.tls-example.yml` als Overlay | `../../connector.env.example` | Ergänzt read-only CA-Mounts und TLS-Env-Variablen für HTTPS-Setups mit interner CA. |

## Startbeispiele

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/external-services.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/shared-network.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  up -d
```

TLS-Overlay:

```bash
docker compose \
  --env-file connector.env \
  -f deploy/compose/openwebui.compose.yml \
  -f deploy/compose/docker-compose.tls-example.yml \
  config --quiet
```

## Wichtige Betriebsregel

Seafile ist immer die Quelle der Wahrheit. Diese Compose-Dateien können
Zielartefakte in RAGFlow und OpenWebUI erzeugen, reparieren oder löschen, aber
sie ändern keine Daten in Seafile.
