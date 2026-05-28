# Changelog

🌐 Sprachen: **Deutsch** | [English](CHANGELOG.en.md)

Alle nennenswerten Änderungen an diesem Repository sollten hier dokumentiert
werden. Das Format orientiert sich an einer einfachen `Unreleased`-Sektion; es
werden keine historischen Releases nachträglich erfunden.

## Unreleased

## 0.1.6 - 2026-05-28

### Fixed

- OpenWebUI-Chat-Proxy fällt bei RAGFlow-Chat-Timeouts kontrolliert auf
  Retrieval-Quellen zurück, statt bis zum HTTP-Timeout ohne Antwort zu hängen.

## 0.1.5 - 2026-05-28

### Added

- Öffentliche Seafile-Basis-URL und flexibles Datei-Link-Template für
  Originaldatei-Links in OpenWebUI-Quellen.

### Changed

- OpenWebUI-Quellenlinks unterscheiden jetzt sauberer zwischen internen
  Docker-Service-URLs und extern erreichbaren Browser-/Preview-URLs.
- Der Enterprise-Compose-Assistent fragt interne Service-Endpunkte und externe
  Browser-Endpunkte getrennt ab und bleibt dadurch im Shared-Network-Betrieb
  verständlicher.

## 0.1.4 - 2026-05-28

### Added

- Portainer-fertiger Enterprise-Compose-Assistent, der bestehende Seafile-,
  RAGFlow- und optionale OpenWebUI-Instanzen abfragt und eine einfügbare
  `portainer-compose.yml` plus zugehörige `portainer.env` erzeugt.
- Enterprise-CA-Compose-Overlay für HTTPS-Ziele mit interner Root-CA.

### Changed

- Das Connector-Image führt beim Containerstart immer `update-ca-certificates`
  aus, kopiert eine gesetzte `CONNECTOR_CA_BUNDLE` vorher in den
  System-Trust-Store und startet danach wieder als unprivilegierter Benutzer.
- Enterprise-Compose startet standardmäßig mit `CONNECTOR_STARTUP_CHECK=infra`,
  damit Dashboard und Logs auch bei externen TLS-, Auth- oder Parserproblemen
  erreichbar bleiben; strikte Live-Prüfung bleibt per `check-live.sh` möglich.
- Der Enterprise-Assistent behandelt unbekannte Root-CA-Pfade und fehlende
  OpenWebUI-Admin-Keys als nachpflegbare Werte statt als Blocker für den
  Grundstart.

## 0.1.3 - 2026-05-27

### Added

- Auditierbarer OpenWebUI-Quellenmodus `audit` mit `[S1]`-Quellenmarken,
  Markdown-Nachweistabelle, Nachweisqualität und transparenter
  Fundstellenqualität.
- Normalisierte `locator_quality` für Zeile, Seite, Abschnitt, Position, Chunk,
  Dokument, Snippet-Fallback und unbekannte Fundstellen.
- Tests für Audit-Markdown, Citation-Event-Payloads, fehlende Fundstellen,
  Debug-Metadaten, Connector-Preview-Links und widersprüchliche oder fehlende
  Quellen.

### Changed

- OpenWebUI-Pipes erscheinen im Modellpicker als `Seafile · <Dataset>` und
  beschreiben sich als prüfbare Wissensmodelle für synchronisierte
  Seafile-Bibliotheken.
- OpenWebUI-Antworten hängen im Standard eine sichtbare Nachweistabelle an,
  während numerische Scores und interne IDs im Normalbetrieb verborgen bleiben.
- Connector-Preview-Links sind der bevorzugte Direktsprungpfad für Citations;
  interne Proxy-Backend-URLs werden weiterhin aus OpenWebUI-Ausgaben gefiltert.

## 0.1.2 - 2026-05-27

### Changed

- TLS-/CA-Bundle-Verarbeitung nutzt für HTTPX jetzt `ssl.SSLContext`, damit
  private CAs konsistent funktionieren und kein veralteter `verify=<pfad>`-Pfad
  mehr nötig ist.
- OpenWebUI-Tool- und Pipe-Artefakte wurden auf `artifact_version` 17 gehoben;
  sie verwenden denselben SSLContext-Ansatz für den Connector-Proxy.
- Release- und Betreiberhinweise erklären feste SemVer-Image-Tags wie `0.1.2`
  klarer und grenzen `latest` als Komfortoption ab.

### Fixed

- Ungültige CA-Bundles werden kontrolliert als TLS-Konfigurationsfehler
  gemeldet, ohne CA-Inhalte oder Secret-Werte auszugeben.
- OpenWebUI-Quellen-Snippets werden parserbasiert bereinigt, damit
  fehlerhaftes HTML nicht über ungebundene Regex-Fallbacks verarbeitet wird.
- Transport- und Dashboard-Diagnose zeigen Custom-CA-Nutzung als `custom_ca`,
  ohne lokale CA-Pfade oder interne TLS-Objekte offenzulegen.

## 0.1.1 - 2026-05-27

### Added

- Ressourcenbasierte Internationalisierung mit Deutsch als Standard,
  Englisch als Alternativsprache, `CONNECTOR_LANGUAGE`, Dashboard-Sprachwahl,
  OpenWebUI-Artifact-Sprachmetadaten und UTF-8-/Unicode-Tests.
- Öffentliche Repository-Dokumentation mit Community-Dateien, Issue-/PR-Vorlagen,
  Security Policy, Support-Hinweisen und Maintainer-Checkliste.
- RAG Evidence Viewer für OpenWebUI-Quellenpreviews mit klarer Trennung zwischen
  Connector-Preview und Original-Seafile-Link.
- Tests für Preview-Token, Original-Link-Sicherheit, XSS-Escaping, Score-Anzeige
  und Fallback-Ansichten.

### Changed

- Repository-Struktur um `README.en.md`, `docs/de/`, `docs/en/` und englische
  Community-Dateien erweitert; GitHub-Sprachwechsel erfolgt über sichtbare Links.
- README stärker auf öffentliche Nutzung, schnellen Einstieg und
  Dokumentationsnavigation ausgerichtet.
- OpenWebUI-Quellenpreviews priorisieren den verwendeten RAG-Kontext,
  Fundstellen, Dataset-Metadaten und technische Details übersichtlicher.
