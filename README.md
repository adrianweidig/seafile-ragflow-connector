# Seafile RAGFlow Connector

Offline-fähiger Sync-Orchestrator für den Betrieb zwischen einem bestehenden
Seafile-Server und einem bestehenden RAGFlow-Server. Der Connector entdeckt
Seafile-Libraries, erzeugt pro Library ein RAGFlow-Dataset aus einem
`connector_template`, importiert Dateien, erkennt Änderungen, löscht entfernte
Dokumente sicher und läuft nach Neustarts weiter.

## Kernprinzipien

- Die Seafile API ist die Quelle der Wahrheit.
- Die RAGFlow API ist das Zielsystem.
- PostgreSQL speichert den dauerhaften Sync-Zustand.
- Redis übernimmt Queueing, Retries und Backpressure.
- RAGFlow-Dataset-Einstellungen bleiben nach der Erstellung live. Das Template
  wird nur für neue Datasets genutzt.
- Der Runtime-Betrieb ist offline-fähig: keine Paket-Downloads, keine Telemetrie
  und keine externen Service-Abhängigkeiten außerhalb der konfigurierten
  Seafile- und RAGFlow-URLs.

## Offline-Deployment mit Portainer

1. Benötigte Images auf dem Docker-Host importieren, zum Beispiel:
   `docker load -i images/seafile-ragflow-connector_0.1.0.tar`
2. In Portainer einen neuen Stack erstellen.
3. `docker-compose.portainer.yml` einfügen.
4. `stack.env.example` nach `stack.env` übernehmen und lokale Seafile-/RAGFlow-URLs
   sowie Tokens eintragen.
5. Stack starten.
6. Controller-Logs und `/readyz` prüfen.

Seafile und RAGFlow werden nicht durch diesen Stack bereitgestellt. Sie bleiben
externe Systeme, erreichbar über LAN, Reverse Proxy oder ein gemeinsames
Docker-Netzwerk.

## Entwicklungschecks

```bash
python -m compileall src tests
python -m unittest discover -s tests/unit
```

Full development environments can also run:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
```

## Dokumentation

- [Architektur](docs/architecture.md)
- [Offline-Deployment](docs/offline-deployment.md)
- [Portainer-Betrieb](docs/portainer.md)
- [Konfiguration](docs/configuration.md)
- [RAGFlow-Template-Verhalten](docs/ragflow-template.md)
- [Recovery](docs/recovery.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Release-Prozess](docs/release.md)
