# Release-Prozess

Online-CI kann Images für die Entwicklung bauen und pushen. Produktive
Installationen sollten feste Image-Tags und Offline-Bundles verwenden.

## Inhalt des Offline-Bundles

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

## Einmal bauen, offline betreiben

Das Connector-Image in einer verbundenen Build-Umgebung bauen:

```bash
docker build -t seafile-ragflow-connector:0.1.0 .
docker save seafile-ragflow-connector:0.1.0 -o images/seafile-ragflow-connector_0.1.0.tar
```

Auf dem Offline-Docker-Host importieren:

```bash
docker load -i images/seafile-ragflow-connector_0.1.0.tar
```

Der Runtime-Container darf beim Start keine Pakete installieren und keine
Artefakte nachladen.
