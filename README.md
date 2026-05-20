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
3. `deploy/portainer/docker-compose.yml` einfügen oder dieses Repo als Git-Stack
   verwenden.
4. `deploy/portainer/stack.env.example` in Portainer als Environment importieren.
5. Alle `change-me` Werte ersetzen und `SEAFILE_BASE_URL` sowie
   `RAGFLOW_BASE_URL` auf aus dem Connector-Container erreichbare URLs setzen.
6. Stack starten und die Logs von Controller, Worker und Reconciler prüfen.

Seafile und RAGFlow werden nicht durch diesen Stack bereitgestellt. Sie bleiben
externe Systeme, erreichbar über LAN, Reverse Proxy, veröffentlichte Host-Ports
oder ein gemeinsames Docker-Netzwerk. Für bestehende Docker-Stacks kann
`CONNECTOR_DOCKER_NETWORK_EXTERNAL=true` mit dem vorhandenen Netzwerknamen
gesetzt werden. Die Compose-Datei referenziert keine lokale `env_file`;
Portainer-Environment-Variablen reichen aus.

## Entwicklungschecks

```bash
python -m compileall src tests migrations
PYTHONPATH=src python -m unittest discover -s tests/unit
```

Vollständige Entwicklungsumgebungen können zusätzlich ausführen:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
```

## Dokumentation

- [Architektur](docs/architecture.md)
- [Konfiguration](docs/configuration.md)
- [Betrieb, Offline-Deployment und WSL-/Docker-Prüfung](docs/operations.md)
- [RAGFlow-Template-Verhalten](docs/ragflow-template.md)
