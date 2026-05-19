# Release Process

Online CI can build and push images for development convenience, but production
installations should use fixed image tags and offline bundles.

## Offline Bundle Contents

```text
seafile-ragflow-connector_0.1.0/
  docker-compose.portainer.yml
  stack.env.example
  README.md
  docs/
  images/
    seafile-ragflow-connector_0.1.0.tar
    postgres_16.tar
    redis_7.tar
  SHA256SUMS
```

## Build Once, Run Offline

Build the connector image in a connected build environment:

```bash
docker build -t seafile-ragflow-connector:0.1.0 .
docker save seafile-ragflow-connector:0.1.0 -o images/seafile-ragflow-connector_0.1.0.tar
```

Import it on the offline Docker host:

```bash
docker load -i images/seafile-ragflow-connector_0.1.0.tar
```

The runtime container must not install packages or fetch artifacts during startup.

