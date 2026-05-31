# Docker Swarm Stack

Dieser Ordner enthält eine Alternative für Docker Swarm.

## Wann diese Variante nutzen?

Nutze `docker-stack.yml`, wenn der Connector als Swarm-Stack laufen soll und
PostgreSQL/Redis ebenfalls durch Swarm verwaltet werden sollen. Seafile,
RAGFlow und optional OpenWebUI bleiben externe Systeme. Sie müssen aus den
Swarm-Nodes beziehungsweise aus den Connector-Tasks erreichbar sein.
Die allgemeine erste Abnahme steht in der
[Admin-Erststart-Checkliste](../../docs/admin-first-start-checklist.md);
Swarm-spezifisch ist zusätzlich die reine Portnummer für
`CONNECTOR_DASHBOARD_PUBLISHED_PORT` zu beachten.

## Wichtige Unterschiede zu Docker Compose

- `docker stack deploy` kennt kein zuverlässiges `--env-file` wie
  `docker compose`. Exportiere die Variablen deshalb vorher in die Shell.
- Swarm ignoriert `depends_on`. Das ist hier beabsichtigt: Der
  Connector-Entrypoint wartet selbst auf PostgreSQL und Redis.
- Dashboard-Ports werden über Swarm Routing-Mesh veröffentlicht. Verwende im
  Swarm-Env nur eine Portnummer, keine Bind-Adresse wie `127.0.0.1:18080`.
- Für produktive Secrets sollte Docker Secrets oder ein externes Secret
  Management genutzt werden. Die Beispiel-Env enthält nur Platzhalter.

## Start

```bash
cd deploy/swarm
cp ../../connector.env.example stack.env
```

`stack.env` bearbeiten, die Minimalpflichtwerte ersetzen und
`CONNECTOR_DASHBOARD_PUBLISHED_PORT` auf eine reine Portnummer wie `18080`
setzen. OpenWebUI-Werte nur setzen, wenn die Anbindung aktiviert wird. Danach:

```bash
set -a
. ./stack.env
set +a
docker stack deploy -c docker-stack.yml seafile-ragflow-connector
```

Status prüfen:

```bash
docker stack services seafile-ragflow-connector
docker service logs seafile-ragflow-connector_connector-controller
```

Danach die
[Admin-Erststart-Checkliste](../../docs/admin-first-start-checklist.md)
durchlaufen. Für Swarm ersetzt `docker stack services` die Compose-Container-
Liste, alle Health-, Dashboard- und Zielsystemkriterien bleiben gleich.

Stack entfernen:

```bash
docker stack rm seafile-ragflow-connector
```

Die benannten Volumes bleiben je nach Swarm-Volume-Treiber auf den Nodes
erhalten und müssen bewusst separat entfernt werden, wenn der Sync-State
verworfen werden soll.
