# Offline-Deployment

Der Runtime-Pfad darf keinen Internetzugriff benötigen.

## Release-Bundle

Ein produktives Release sollte enthalten:

- `docker-compose.portainer.yml`
- `stack.env.example`
- Connector-Image als Tar-Datei, zum Beispiel `seafile-ragflow-connector_0.1.0.tar`
- optionale PostgreSQL- und Redis-Image-Tars
- Checksummen

## Host-Vorbereitung

```bash
docker load -i images/seafile-ragflow-connector_0.1.0.tar
docker load -i images/postgres_16.tar
docker load -i images/redis_7.tar
```

Danach den Portainer-Stack aus `docker-compose.portainer.yml` erstellen.

## Netzwerkanforderungen

Der Stack benötigt nur Zugriff auf:

- die konfigurierte Seafile-URL
- die konfigurierte RAGFlow-URL
- die eigenen PostgreSQL- und Redis-Services

Zur Laufzeit dürfen keine öffentlichen Paket-Indizes, Registries,
Telemetrie-Endpunkte oder Modell-Download-Endpunkte aufgerufen werden.
