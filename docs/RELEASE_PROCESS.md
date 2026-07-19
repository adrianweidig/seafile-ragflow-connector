# Release-Prozess

Dieses Repository enthält aktuell Paketmetadaten mit Version `2.6.1`, einen
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

1. Version in `pyproject.toml`,
   `src/seafile_ragflow_connector/__init__.py` und `uv.lock` konsistent setzen.
2. `CHANGELOG.md` und `CHANGELOG.en.md` aus `Unreleased` in denselben datierten
   Release-Abschnitt überführen. Für diesen Stand ist das
   `2.6.1 - 2026-07-19`.
3. Versionsbadge, README-Image-Beispiele, `connector.env.example`, Portainer-
   Env-Beispiel und Release-Dokumentation abgleichen.
4. README, `docs/`, Deployment-Artefakte und Admin-Erststart-Checklisten auf
   denselben Dashboard-Control-Vertrag prüfen.
5. Metadatatest und Lock-Konsistenz ausführen:

   ```bash
   uv run --offline --no-sync pytest tests/unit/test_release_metadata.py
   uv lock --check
   ```

6. Keine Secrets, lokalen Env-Dateien oder privaten Zertifikate committen.

Für 2.6.1 gehört zur Release-Abnahme außerdem ein Browser-Smoke gegen das im
`connector-controller` eingebettete Dashboard: Basic Auth, globales
Pause/Fortsetzen, Bibliotheks-Pause/Fortsetzen, manueller Delta-Lauf,
Dateifortschritt, Parsing-Bereich einschließlich Leerzustand, Historie und
mobile Darstellung. Server- und Unit-Tests prüfen die globale Aktionsmatrix,
Laufübergänge und Bestätigungen, persistente Bibliothekszustände sowie die
Zuordnung von Delta-, Voll- und Reconcile-Spezifikationen.
Der produktive HTTPS-Pfad wird nach dem Rollout separat live geprüft.
`connector dashboard` ist der negative Read-only-Test und darf keine
Adminsteuerung anbieten.

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

## Offline-Bundle als `.7z`

Das vollständige manuelle Airgap-Bundle liegt außerhalb des Git-Worktrees und
verwendet einen eindeutigen Namen wie
`seafile-ragflow-connector-airgap-2.6.1-<sha7>.7z`. Es enthält mindestens:

```text
ANLEITUNG.txt
INHALT.txt
REPO_STAND.txt
RELEASE_MANIFEST.json
SHA256SUMS.txt
docker-images/
  IMAGES.txt
  image-manifests.json
  seafile-ragflow-connector_2.6.1_linux-amd64.docker-image.tar
  postgres_16_linux-amd64.docker-image.tar
  valkey_8_linux-amd64.docker-image.tar
  redis_7_compat_linux-amd64.docker-image.tar
install/
  README.md
  README.en.md
  CHANGELOG.md
  CHANGELOG.en.md
  LICENSE
  connector.env.example
  deploy/
  docs/
python-dist/
  seafile_ragflow_connector-2.6.1-py3-none-any.whl
  seafile_ragflow_connector-2.6.1.tar.gz
repo/
  seafile-ragflow-connector-2.6.1.git.bundle
  seafile-ragflow-connector-source-2.6.1.zip
```

Git-Bundle und Source-ZIP müssen exakt den veröffentlichten Release-Commit
abbilden; die Connector-Image-Tar muss zum verifizierten `2.6.1`-Digest gehören.
Für den produktiven Portainer-Stand werden die tatsächlich verwendeten
PostgreSQL-16- und Valkey-8-Images digestgenau aufgenommen. Redis 7 bleibt
zusätzlich und ausdrücklich als Kompatibilitätsfallback für die
Repository-Defaults gekennzeichnet; alle beweglichen State-Tags werden mit
Registry-Digest und lokaler Image-ID dokumentiert.
Lokale `connector.env`-/`stack.env`-Dateien, Tokens, private Zertifikate,
Caches und `output/` gehören nicht in das Archiv. Für jede interne Paketdatei
außer `SHA256SUMS.txt` selbst wird eine Prüfsumme in `SHA256SUMS.txt`
geschrieben; neben dem fertigen `.7z` liegt zusätzlich dessen externe
SHA-256-Prüfsumme.

Vor Übergabe werden Wheel und Source-Distribution gebaut, das Wheel in einer
frischen Umgebung installiert, jede Image-Tar per `crane validate --tarball`
oder `docker load` geprüft und der Connector-Container einmal mit `--help`
gestartet. Abschließend:

```powershell
$sha7 = (git rev-parse --short=7 'v2.6.1^{commit}').Trim()
$bundlePath = "F:\seafile-ragflow-connector-airgap-2.6.1-$sha7.7z"
if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
  throw "Airgap-Bundle fehlt: $bundlePath"
}
& 'C:\Program Files\7-Zip\7z.exe' t $bundlePath
Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256
```

Die Erstellung dieses vollständigen `.7z` und der Docker-Image-Tars bleibt ein
bewusster Maintainer-Schritt; der GitHub-Workflow erzeugt sie nicht.
