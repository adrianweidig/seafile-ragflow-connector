# Docker Image

Dieser Ordner beschreibt das Runtime-Image des Connectors.

- `Dockerfile` baut ein schlankes Python-3.12-Image, installiert das Paket aus
  dem Repository und startet als unprivilegierter Benutzer.
- `entrypoint.sh` führt optionale Startup-Prüfungen, Datenbankinitialisierung
  und danach den gewünschten Connector-Befehl aus.

Das Image installiert zur Laufzeit keine Pakete. Für GHCR wird es durch
`.github/workflows/docker.yml` gebaut und unter
`ghcr.io/adrianweidig/seafile-ragflow-connector` veröffentlicht.
