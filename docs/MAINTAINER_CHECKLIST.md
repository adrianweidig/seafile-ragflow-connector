# Maintainer-Checkliste

Diese Punkte betreffen GitHub- oder Release-Einstellungen, die nicht sicher aus
dem Arbeitsbaum allein abgeschlossen werden können.

## Repository-Metadaten

- Beschreibung: `Offline-first Seafile to RAGFlow sync orchestrator for Portainer deployments`.
- Topics prüfen oder setzen, z. B. `seafile`, `ragflow`, `openwebui`, `portainer`, `docker-compose`, `python`, `sync`, `rag`.
- Website-URL leer lassen, solange keine öffentliche Dokumentationsseite existiert.
- Social Preview aus `docs/assets/social-preview.svg` ableiten und manuell in GitHub hochladen. Optional vorher als 1280 x 640 PNG exportieren.

## Schutzregeln

- Branch Protection oder Ruleset für `master` prüfen.
- Required Status Checks mindestens für CI und CodeQL festlegen, sobald sie stabil grün laufen.
- Force Pushes und Branch Deletion für `master` unterbinden.
- Pull Requests mit Review-Pflicht aktivieren, wenn mehrere Maintainer beteiligt sind.

## Security

- Private Vulnerability Reporting aktivieren, wenn für das Repository verfügbar.
- Dependabot Security Updates aktivieren.
- Code Scanning Alerts aktivieren und den CodeQL-Workflow beobachten.
- Secret Scanning aktivieren, sofern im GitHub-Plan verfügbar.
- Einen privaten Sicherheitskontakt ergänzen, falls Maintainer einen solchen veröffentlichen wollen.

## Releases und Packages

- Erstes GitHub Release erstellen, wenn ein stabiler öffentlicher Stand markiert werden soll.
- GHCR-Package-Sichtbarkeit prüfen, wenn Betreiber das Image ohne Authentifizierung pullen sollen.
- Release Notes aus `CHANGELOG.md` übernehmen.
- Für produktive Dokumentation eher Release- oder SHA-Tags empfehlen als bewegliche Branch-Tags.

## Dokumentation

- Prüfen, ob GitHub Pages oder eine externe Docs-Seite sinnvoll ist.
- Social Preview nach größeren README-/Branding-Änderungen aktualisieren.
- FAQ und Operations-Dokumente nach wiederkehrenden Issues erweitern.
