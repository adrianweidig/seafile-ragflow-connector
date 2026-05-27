# Changelog

🌐 Sprachen: **Deutsch** | [English](CHANGELOG.en.md)

Alle nennenswerten Änderungen an diesem Repository sollten hier dokumentiert
werden. Das Format orientiert sich an einer einfachen `Unreleased`-Sektion; es
werden keine historischen Releases nachträglich erfunden.

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
