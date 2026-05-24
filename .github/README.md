# GitHub-Automatisierung

Dieser Ordner enthält GitHub-spezifische Automatisierung und
Kollaborationsvorlagen.

- `workflows/test.yml` installiert die Python-Abhängigkeiten mit `uv sync
  --locked --all-extras` und führt den Verify-Runner ohne Compose-Nebenwirkung
  aus.
- `workflows/docker.yml` baut das Runtime-Image aus `deploy/docker/Dockerfile`
  und veröffentlicht es nach GHCR unter
  `ghcr.io/adrianweidig/seafile-ragflow-connector`.
- `workflows/codeql.yml` führt CodeQL für Python aus.
- `dependabot.yml` prüft `uv`, Docker und GitHub Actions wöchentlich.
- `ISSUE_TEMPLATE/` enthält Vorlagen für Bugs, Features und Dokumentation.
- `PULL_REQUEST_TEMPLATE.md` erfasst Prüfungen, Betriebsrisiken und
  Secret-Hygiene.

Das GHCR-Image bekommt auf dem Default-Branch den Tag `latest`, zusätzlich
Branch-, SHA- und bei Git-Tags SemVer-Tags. Damit kann Portainer standardmäßig
`ghcr.io/adrianweidig/seafile-ragflow-connector:latest` ziehen, während
produktive Installationen auch auf einen SHA- oder Release-Tag pinnen können.
