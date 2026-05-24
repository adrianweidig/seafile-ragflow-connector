# Dokumentation

Dieser Ordner enthält die fachliche und betriebliche Dokumentation.

- `architecture.md` erklärt Komponenten, Datenflüsse, Delete-/Repair-Regeln und
  die optionale OpenWebUI-Integration.
- `configuration.md` beschreibt Environment-Variablen, Delete-Policy,
  Dashboard und OpenWebUI-Modi.
- `environment.md` trennt minimale Pflichtvariablen von optionalen und
  modusabhängigen Variablen.
- `operations.md` enthält Portainer-Betrieb, Docker-Compose-Varianten,
  Docker-Swarm-Betrieb, GHCR-/Offline-Hinweise, Recovery, Troubleshooting und
  lokale WSL-/Docker-Prüfungen.
- `ragflow-template.md` beschreibt, wie das RAGFlow-Template beim Erzeugen neuer
  Datasets genutzt wird.
- `tls-topology.md`, `tls-certificates.md`, `docker-compose-tls.md` und
  `troubleshooting-ssl.md` beschreiben TLS-Strecken, CA-Bundles,
  Compose-Mounts und SSL-Fehlerdiagnose.
- `https-edge-testbed.md` dokumentiert den lokal geprüften Nginx-/Root-CA-
  Teststand mit `.top.secret`-Domains, Compose-Stacks und den abgeleiteten
  Connector-Anpassungen.
- `../deploy/tls-lab/README.md` beschreibt das lokale HTTPS-Lab mit eigener
  Test-Root-CA und `.top.secret`-Domains.

Die Dokumentation ist bewusst deployment-orientiert: Ein Betreiber soll daraus
ableiten können, welche Werte in Portainer gesetzt werden müssen und welche
Checks vor dem produktiven Start sinnvoll sind.
