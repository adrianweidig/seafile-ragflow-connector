# Docker Compose Anwendungsfälle

Dieser Ordner enthält direkt nutzbare Compose-Varianten für typische
Installationen. Jede Variante hat eine eigene kommentierte
`*.stack.env.example`. Kopiere die passende Datei bei Bedarf zu `stack.env`,
ersetze alle `change-me` Werte und starte dann mit `--env-file`.

## Welche Datei benutze ich?

| Anwendungsfall | Compose-Datei | Env-Vorlage | Zweck |
| --- | --- | --- | --- |
| Externe Dienste über Host/LAN | `external-services.compose.yml` | `external-services.stack.env.example` | Seafile und RAGFlow laufen außerhalb des Stacks, z. B. über Reverse Proxy, LAN-IP oder veröffentlichte Host-Ports. |
| Bestehendes Docker-Netz | `shared-network.compose.yml` | `shared-network.stack.env.example` | Connector, Seafile und RAGFlow hängen im selben Docker-Netz und sprechen sich über Service-Namen an. |
| OpenWebUI zusätzlich anbinden | `openwebui.compose.yml` | `openwebui.stack.env.example` | Wie Shared-Network, zusätzlich mit Dashboard/Proxy und aktivierter OpenWebUI-Synchronisation. |

## Startbeispiele

```bash
docker compose \
  --env-file deploy/compose/external-services.stack.env.example \
  -f deploy/compose/external-services.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file deploy/compose/shared-network.stack.env.example \
  -f deploy/compose/shared-network.compose.yml \
  up -d
```

```bash
docker compose \
  --env-file deploy/compose/openwebui.stack.env.example \
  -f deploy/compose/openwebui.compose.yml \
  up -d
```

## Wichtige Betriebsregel

Seafile ist immer die Quelle der Wahrheit. Diese Compose-Dateien können
Zielartefakte in RAGFlow und OpenWebUI erzeugen, reparieren oder löschen, aber
sie ändern keine Daten in Seafile.
