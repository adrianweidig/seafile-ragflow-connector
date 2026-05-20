# Docker Swarm Stack

Dieser Ordner enthält eine Alternative für Docker Swarm.

## Wann diese Variante nutzen?

Nutze `docker-stack.yml`, wenn der Connector als Swarm-Stack laufen soll und
PostgreSQL/Redis ebenfalls durch Swarm verwaltet werden sollen. Seafile,
RAGFlow und optional OpenWebUI bleiben externe Systeme. Sie müssen aus den
Swarm-Nodes beziehungsweise aus den Connector-Tasks erreichbar sein.

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
cp stack.env.example stack.env
```

`stack.env` bearbeiten, alle `change-me` Werte ersetzen und dann:

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

Stack entfernen:

```bash
docker stack rm seafile-ragflow-connector
```

Die benannten Volumes bleiben je nach Swarm-Volume-Treiber auf den Nodes
erhalten und müssen bewusst separat entfernt werden, wenn der Sync-State
verworfen werden soll.
