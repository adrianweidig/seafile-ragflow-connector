# Codex Project Readiness

## Zusammenfassung

Das Projekt wurde im aktuellen Checkout geprüft. Es ist ein versioniertes Python-3.12-Projekt mit bestehender GitHub-Anbindung, `uv`-Lockfile, Tests, Lint-/Typecheck-Konfiguration, Docker-/Portainer-Artefakten und projektlokalen Codex-Anweisungen. Eine veraltete absolute Pfadangabe in der Betriebsdokumentation wurde auf den aktuellen Workspace-Pfad korrigiert.

## Projektroot

`E:\Codex_Workspace\repos\seafile-ragflow-connector`

## Projekttyp

Offline-fähiger Python-Connector zwischen Seafile, RAGFlow und optional OpenWebUI.

## Git-Status

Git-Repository vorhanden. Branch: `master`, Upstream: `origin/master`. Der Arbeitsbaum war zu Beginn sauber. Nach der Prüfung wurden nur dieser Bericht und die dokumentierte Pfadkorrektur geändert.

## GitHub-Synchronität

Remote `origin` zeigt auf `https://github.com/adrianweidig/seafile-ragflow-connector.git`. GitHub CLI ist für `adrianweidig` authentifiziert. `git fetch --prune origin` wurde erfolgreich ausgeführt. Der Remote ist ein öffentliches GitHub-Repository mit Default-Branch `master`.

## Abhängigkeiten

Paketmanager: `uv`, vorgegeben durch `uv.lock` und `pyproject.toml`. Python-Version: `>=3.12`. Entwicklungs- und Laufzeitabhängigkeiten sind im Manifest definiert.

## Tests und Builds

`python scripts/verify.py --skip-compose` wurde erfolgreich ausgeführt. Enthalten waren `uv sync --locked --all-extras`, `compileall`, `ruff check`, `mypy src`, `pytest`, `unittest discover -s tests/unit` und `git diff --check`. Ergebnis: 118 Pytest-Tests bestanden, 97 Unittest-Tests bestanden. Docker-Compose-Konfiguration wurde bewusst übersprungen, weil `--skip-compose` der dokumentierte lokale Standardcheck ohne Docker-Nebenwirkungen ist.

## Startfähigkeit

Start- und Betriebswege sind in `README.md`, `docs/operations.md` und den Deployment-Verzeichnissen dokumentiert. Die CLI wird über den Skripteintrag `connector = "seafile_ragflow_connector.app.cli:app"` bereitgestellt. Für produktionsnahe Starts werden externe Seafile-/RAGFlow-/OpenWebUI-Endpunkte und nicht getrackte Env-Dateien benötigt.

## Codex-Nutzbarkeit

`AGENTS.md` ist vorhanden und wurde berücksichtigt. Die Projektstruktur ist für Codex direkt bearbeitbar; relevante Quelltexte, Tests, Migrationsdateien, Docs und Deployment-Artefakte liegen innerhalb des Projektroots.

## Geprüfte alte Pfade

Gezielt geprüft wurden alte lokale Checkout-Pfade und Codex-/WSL-Pfade. Eindeutig veraltete Referenzen auf `/mnt/c/Users/adria/Documents/Seafile-RAGFlow-Connector` in `docs/operations.md` wurden auf `/mnt/e/Codex_Workspace/repos/seafile-ragflow-connector` aktualisiert. Die `.top.secret`-Referenzen sind dokumentierte lokale Testdomains und wurden nicht geändert.

## Durchgeführte Änderungen

- `docs/operations.md`: alte WSL-Checkout-Pfade auf den aktuellen Workspace-Pfad korrigiert.
- `CODEX_PROJECT_READINESS.md`: diesen kompakten Readiness-Bericht erstellt.
- `.venv`: mit `uv sync --locked --all-extras --reinstall` lokal neu synchronisiert, weil die bestehende Umgebung nach dem Workspace-Umzug noch ein Script-Trampoline auf den alten Checkout enthielt. `.venv` bleibt ignoriert und wurde nicht versioniert.

## Nicht durchgeführte Änderungen

Keine Git-Neuinitialisierung, keine neue GitHub-Remote-Anlage, keine Framework- oder Tooling-Änderungen, keine produktiven Deployments und keine lokalen Projektkopien.

## Sensible oder ausgeschlossene Dateien

`.gitignore` schließt unter anderem `.env`, `connector.env`, `stack.env`, TLS-Lab-Zertifikate, Caches, Logs, Build-Artefakte und IDE-Verzeichnisse aus. Es wurden keine Secrets, Tokens, privaten Schlüssel oder produktiven Zertifikate hinzugefügt.

## Fehler und Warnungen

Der erste Verify-Lauf scheiterte beim Aufruf des `mypy`-Entry-Points mit `uv trampoline failed to canonicalize script path`, nachdem `uv` das lokale Paket vom alten Checkout auf den aktuellen Pfad umgehängt hatte. Nach `uv sync --locked --all-extras --reinstall` lief der Verify-Runner erfolgreich.

Während der Tests wurden nicht blockierende Warnungen ausgegeben:

- `httpx`-DeprecationWarning für `verify=<str>` in TLS-Szenariotests.
- `ResourceWarning` für unclosed SQLite-Verbindungen während der Unittest-Ausführung.

Produktive externe Dienste wurden nicht gestartet oder mutiert.

## Offene manuelle Aufgaben

Für echte Laufzeitstarts muss eine nicht getrackte `connector.env` mit gültigen lokalen oder produktiven Endpunkten und Zugangsdaten erstellt werden. Docker-/Compose-Smoke-Tests sollten nur in einer passenden lokalen Umgebung mit erlaubten Pulls oder vorhandenen Images ausgeführt werden.

## Endzustand

Das Projekt ist strukturell arbeitsfähig, GitHub-seitig angebunden, lokal verifiziert und nach der minimalen Pfadkorrektur für den aktuellen Workspace nutzbar. Es gibt lokale Änderungen an `docs/operations.md` und `CODEX_PROJECT_READINESS.md`, die sinnvoll committet und gepusht werden können.
