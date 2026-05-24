# GitHub-Konfiguration

Diese Datei beschreibt nur den `.github`-Ordner dieses Repositories. Die
fachliche Projektbeschreibung, der Schnellstart und die Betriebsdokumentation
stehen in der [README im Repository-Root](../README.md).

## Workflows

- `workflows/test.yml` installiert die Python-Abhängigkeiten mit `uv sync
  --locked --all-extras` und führt `python scripts/verify.py --skip-compose`
  aus.
- `workflows/docker.yml` baut das Runtime-Image aus `deploy/docker/Dockerfile`
  und veröffentlicht es als GHCR-Image für den Connector.
- `workflows/codeql.yml` führt CodeQL für Python aus.

## Kollaboration und Wartung

- `dependabot.yml` prüft Python-, Docker- und GitHub-Actions-Abhängigkeiten
  wöchentlich.
- `ISSUE_TEMPLATE/` enthält Vorlagen für Bugs, Feature-Vorschläge und
  Dokumentationshinweise.
- `PULL_REQUEST_TEMPLATE.md` erfasst relevante Checks, Betriebsrisiken und
  Secret-Hygiene für Änderungen am Connector.
