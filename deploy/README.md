# Deployment

Dieser Ordner enthält alles, was zum Betrieb außerhalb der lokalen
Entwicklungsumgebung benötigt wird.

- `docker/` baut das Connector-Image und enthält den Container-Entrypoint.
- `portainer/` enthält die Portainer-fähige Compose-Datei.
- `compose/` enthält direkt nutzbare Docker-Compose-Varianten für externe
  Dienste, gemeinsames Docker-Netz und OpenWebUI-Anbindung.
- `swarm/` enthält eine Docker-Swarm-Alternative mit eigenem Stackfile und
  eigener Env-Vorlage.

Die empfohlene einheitliche Konfigurationsschnittstelle liegt im Repo-Root:
`connector.env.example`. Kopiere sie zu `connector.env`, ersetze die
Platzhalter und verwende dieselbe Datei für Docker Compose oder importiere ihren
Inhalt in Portainer.
Für die erste Abnahme nach einem neuen Deploy steht die
[Admin-Erststart-Checkliste](../docs/admin-first-start-checklist.md) bereit.

Der Stack bringt PostgreSQL und Redis für den Connector-State mit. Seafile,
RAGFlow und optional OpenWebUI bleiben externe Systeme und werden nie durch
dieses Repository bereitgestellt.
