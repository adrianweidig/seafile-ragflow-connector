# Deployment

Dieser Ordner enthält alles, was zum Betrieb außerhalb der lokalen
Entwicklungsumgebung benötigt wird.

- `docker/` baut das Connector-Image und enthält den Container-Entrypoint.
- `portainer/` enthält die Portainer-fähige Compose-Datei und eine importierbare
  Beispiel-Environment-Datei.
- `compose/` enthält direkt nutzbare Docker-Compose-Varianten für externe
  Dienste, gemeinsames Docker-Netz und OpenWebUI-Anbindung.
- `swarm/` enthält eine Docker-Swarm-Alternative mit eigenem Stackfile und
  eigener Env-Vorlage.

Der Stack bringt PostgreSQL und Redis für den Connector-State mit. Seafile,
RAGFlow und optional OpenWebUI bleiben externe Systeme und werden nie durch
dieses Repository bereitgestellt.
