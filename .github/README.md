# GitHub Automatisierung

Dieser Ordner enthält GitHub-spezifische Automatisierung.

- `workflows/test.yml` installiert die Python-Abhängigkeiten mit `uv sync
  --locked --all-extras` und führt `ruff`, `mypy` und `pytest` aus.
- `workflows/docker.yml` baut das Runtime-Image aus `deploy/docker/Dockerfile`
  und veröffentlicht es nach GHCR unter
  `ghcr.io/adrianweidig/seafile-ragflow-connector`.

Das GHCR-Image bekommt auf dem Default-Branch den Tag `latest`, zusätzlich
Branch-, SHA- und bei Git-Tags SemVer-Tags. Damit kann Portainer standardmäßig
`ghcr.io/adrianweidig/seafile-ragflow-connector:latest` ziehen, während
produktive Installationen auch auf einen SHA- oder Release-Tag pinnen können.
