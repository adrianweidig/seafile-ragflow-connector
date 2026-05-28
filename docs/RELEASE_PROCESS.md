# Release-Prozess

Dieses Repository enthält aktuell Paketmetadaten mit Version `0.1.4`, einen
Docker-Publish-Workflow für GHCR und einen einfachen SemVer-Release-Pfad. Dieser
Prozess beschreibt einen vorsichtigen Maintainer-Ablauf für zukünftige Releases.

## Vorbereitende Checks

```bash
uv sync --locked --all-extras
python scripts/verify.py --skip-compose
```

Wenn Docker Compose im Release-Kontext verfügbar und sicher ist:

```bash
python scripts/verify.py --with-compose
```

## Version und Changelog

1. Version in `pyproject.toml` prüfen und bei Bedarf erhöhen.
2. `CHANGELOG.md` aus `Unreleased` in einen Release-Abschnitt überführen.
3. README, `docs/`, `connector.env.example` und Deployment-Artefakte auf Konsistenz prüfen.
4. Keine Secrets, lokalen Env-Dateien oder privaten Zertifikate committen.

## GitHub Release

1. Einen signifikanten Commit-Stand auf `master` wählen.
2. Einen Tag im Format `vX.Y.Z` erstellen.
3. Tag pushen.
4. GitHub Release mit kompakten Release Notes aus `CHANGELOG.md` erstellen.

Der Docker-Workflow veröffentlicht für SemVer-Tags entsprechende GHCR-Tags. Für
produktionsnahe Installationen sollten Betreiber nach Möglichkeit einen Release-
oder SHA-Tag statt eines beweglichen Branch-Tags pinnen.

## Offline-Bundle

Ein manuelles Offline-Bundle kann enthalten:

```text
docker-compose.yml
connector.env.example
images/
  seafile-ragflow-portainer-images.tar
SHA256SUMS
```

Die Erstellung und Signierung eines solchen Bundles ist derzeit ein manueller
Maintainer-Schritt.
