# Offline Deployment

The runtime path must not require internet access.

## Release Bundle

A production release should contain:

- `docker-compose.portainer.yml`
- `stack.env.example`
- connector image tar, for example `seafile-ragflow-connector_0.1.0.tar`
- optional Postgres and Redis image tars
- checksums

## Host Preparation

```bash
docker load -i images/seafile-ragflow-connector_0.1.0.tar
docker load -i images/postgres_16.tar
docker load -i images/redis_7.tar
```

Then create the Portainer stack from `docker-compose.portainer.yml`.

## Network Requirements

The stack only needs access to:

- configured Seafile URL
- configured RAGFlow URL
- its own Postgres and Redis services

It must not call public package indexes, registries, telemetry endpoints, or model
download endpoints at runtime.

