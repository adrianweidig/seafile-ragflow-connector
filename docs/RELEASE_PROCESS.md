# Release-Prozess

Dieses Repository enthält aktuell Paketmetadaten mit Version `2.4.2`, einen
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
2. Prüfen, dass der gewünschte Tag lokal, remote und als GitHub Release noch
   nicht existiert.
3. Einen Tag im Format `vX.Y` oder `vX.Y.Z` erstellen. Gültige Beispiele sind
   `v2.1`, `v3.0` oder `v3.0.1`.
4. Tag pushen.
5. Den `docker-image`-Workflow für den Tag abwarten.
6. Den GHCR-Tag prüfen, bevor der GitHub Release veröffentlicht wird. Ein Tag
   `v2.1` muss beispielsweise `ghcr.io/adrianweidig/seafile-ragflow-connector:2.1`
   erzeugen; zusätzlich bleibt der `sha-<commit>`-Tag als Fallback verfügbar.
7. GitHub Release mit kompakten Release Notes aus `CHANGELOG.md` erstellen.

Der Docker-Workflow veröffentlicht für `vX.Y`- und `vX.Y.Z`-Tags entsprechende
GHCR-Tags ohne führendes `v`. Ein Patch-Tag wie `v3.0.1` erzeugt zusätzlich den
Minor-Tag `3.0`. Für produktionsnahe Installationen sollten Betreiber nach
Möglichkeit einen Release- oder SHA-Tag statt eines beweglichen Branch-Tags
pinnen.

## Automatische Release-Artefakte

Der Workflow `.github/workflows/release-artifact.yml` läuft bei jedem Push auf
`master` oder `main` sowie manuell per `workflow_dispatch`. Er erstellt mit
`git archive` ein ZIP des exakten Commits, `release-notes.md` mit Branch,
Commit, Event, Actor, UTC-Zeitpunkt und Änderungsliste sowie `SHA256SUMS`.

Der Workflow erzeugt bewusst keine Tags und keine GitHub Releases. Die
SemVer-Entscheidung und die Veröffentlichung eines GitHub Releases bleiben
Maintainer-Schritte.

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
