# Portainer-Betrieb

## Basis-Stack

Einen neuen Portainer-Stack erstellen und `docker-compose.portainer.yml`
einfügen.

Environment-Werte aus `stack.env.example` setzen. Mindestens konfigurieren:

- `SEAFILE_BASE_URL`
- `SEAFILE_ADMIN_TOKEN`
- `SEAFILE_SYNC_USER_TOKEN`
- `RAGFLOW_BASE_URL`
- `RAGFLOW_API_KEY`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`

## Worker skalieren

`connector-worker` in Portainer skalieren, wenn RAGFlow und Seafile zusätzliche
Last verarbeiten können. Parsing und Embedding in RAGFlow sind meist der Engpass,
daher Worker-Anzahl konservativ erhöhen.

## Externe Docker-Netzwerke

Wenn Seafile oder RAGFlow in Docker laufen, diesen Stack an das bestehende
Netzwerk hängen und interne Service-Namen für `SEAFILE_BASE_URL` und
`RAGFLOW_BASE_URL` verwenden.
