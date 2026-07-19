# Dokumentation

🌐 Sprachen: **Deutsch** | [English](en/index.md)

Dieser Ordner enthält die fachliche und betriebliche Dokumentation.

- `architecture.md` erklärt Komponenten, Datenflüsse, die persistente
  Admin-Control-Plane, Delete-/Repair-Regeln und die optionale OpenWebUI-
  Integration.
- `security-model.md` beschreibt die getrennten Rollen von Connector-Core,
  Controller-/Standalone-Dashboard, Search-Service und OpenWebUI-Pipe sowie das
  Fail-Closed-Modell.
- `access-control.md` beschreibt ACL-Snapshot, SearchProfiles und die interne
  Authz-API.
- `search-service.md` dokumentiert die nutzernahe Wissenssuche als separaten
  Container.
- `openwebui-acl.md` erklärt die zentrale Autorisierung für OpenWebUI-Pipes
  vor RAGFlow-Abfragen.
- `configuration.md` beschreibt Environment-Variablen, Delete-Policy,
  Dashboard-Administration, Zustände, Sicherheitsgrenzen und OpenWebUI-Modi.
- `environment.md` trennt minimale Pflichtvariablen von optionalen und
  modusabhängigen Variablen.
- `admin-first-start-checklist.md` führt Administratoren durch Vorprüfung,
  ersten Start, Erfolgskriterien und Nutzerfreigabe.
- `manual-workflow-verification.md` beschreibt den manuell prüfbaren
  Seafile-Upload-zu-RAGFlow-Dataset-zu-OpenWebUI-Pipe-Ablauf.
- `demo-recording.md` beschreibt die vorbereitete Demoaufnahme mit Real-Chrome-
  Skript, Dry-Run-Plan, OBS-Webhooks und Abnahmekriterien.
- `assets/demo/` enthält die aktuell geprüfte Demoaufnahme ohne eingebrannte
  Kapiteltexte, Highlight-Rahmen oder künstlichen Mauszeiger.
- `operations.md` enthält Portainer-Betrieb, Docker-Compose-Varianten,
  Docker-Swarm-Betrieb, GHCR-/Offline-Hinweise, Recovery, Troubleshooting und
  lokale WSL-/Docker-Prüfungen.
- `testing.md` beschreibt den wiederholbaren lokalen und CI-nahen Testablauf
  einschließlich Admin-Control- und Dashboard-Browser-Regression.
- `ragflow-template.md` beschreibt, wie das RAGFlow-Template beim Erzeugen neuer
  Datasets genutzt wird.
- `tls-topology.md`, `tls-certificates.md`, `docker-compose-tls.md` und
  `troubleshooting-ssl.md` beschreiben TLS-Strecken, CA-Bundles,
  Compose-Mounts, den Enterprise-Compose-Assistenten und SSL-Fehlerdiagnose.
- `local-https-compose.md` beschreibt den produktionsnahen lokalen
  WSL-Docker-Betrieb mit Compose-Updatepfad, lokalen HTTPS-Mocks und
  `https://connector.top.secret` sowie `https://search.top.secret/search`.
- `https-edge-testbed.md` dokumentiert den lokal geprüften Nginx-/Root-CA-
  Teststand mit `.top.secret`-Domains, Compose-Stacks und den abgeleiteten
  Connector-Anpassungen.
- `FAQ.md` beantwortet wiederkehrende Betriebs- und Integrationsfragen.
- `RELEASE_PROCESS.md` beschreibt den vorsichtigen manuellen Release-Ablauf.
- `MAINTAINER_CHECKLIST.md` bündelt GitHub-Einstellungen, Security-Optionen und
  Release-Aufgaben, die Maintainer außerhalb des Arbeitsbaums prüfen müssen.
- `i18n.md` beschreibt Sprachwahl, Locale-Erkennung, UTF-8-/Unicode-Regeln und
  das Ergänzen weiterer Sprachen.
- `de/index.md` und `en/index.md` sind die expliziten Sprach-Einstiege für
  GitHub und spätere statische Dokumentation.
- `../deploy/tls-lab/README.md` beschreibt das lokale HTTPS-Lab mit eigener
  Test-Root-CA und `.top.secret`-Domains.

Die Dokumentation ist bewusst deployment-orientiert: Ein Betreiber soll daraus
ableiten können, welche Werte in Portainer gesetzt werden müssen und welche
Checks vor dem produktiven Start sinnvoll sind.
