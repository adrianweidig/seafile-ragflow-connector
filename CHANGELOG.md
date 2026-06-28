# Changelog

🌐 Sprachen: **Deutsch** | [English](CHANGELOG.en.md)

Alle nennenswerten Änderungen an diesem Repository sollten hier dokumentiert
werden. Das Format orientiert sich an einer einfachen `Unreleased`-Sektion; es
werden keine historischen Releases nachträglich erfunden.

## Unreleased

Keine Einträge.

## 2.5.0 - 2026-06-28

### Changed

- Wissenssuche nutzt nach visuellem Review eine ruhigere Arbeitsflächen-Hierarchie
  mit dezenter Trefferpassage, priorisierter Viewer-Aktion und kompakteren
  Quellen-/Bibliotheksflächen.
- Text- und Markdown-Viewer markieren im Dokument nur noch einen kurzen,
  priorisierten Trefferanker; die vollständige Passage bleibt als kopierbarer
  Auszug mit linker Akzentlinie sichtbar.
- Das Dashboard verwendet dichtere operative UI-Tokens mit flacheren Panels,
  kompakteren Metriken, ruhigeren Statusflächen und stabileren Tablet-/Mobile-
  Breakpoints.

## 2.4.11 - 2026-06-27

### Fixed

- Wissenssuche markiert im Text-/Markdown-Viewer nur noch einen kurzen,
  relevanten Fokus-Treffer statt den gesamten RAG-Chunk gelb hervorzuheben.
- Die Trefferpassage unter dem Viewer bleibt als neutraler, kopierbarer Auszug
  sichtbar und wiederholt nicht mehr dieselbe große gelbe Markierung.
- Der Viewer-Hinweis erklärt klarer, dass die vollständige Passage kopierbar
  bleibt, während im Dokument nur der relevanteste Treffer hervorgehoben wird.

## 2.4.10 - 2026-06-26

### Fixed

- Wissenssuche liefert im Antwortmodus weiterhin eine synthetisierte,
  zitierte Antwort und nutzt für Prompt, Kopieren und Textmarkierung den
  ungekürzten Passage-Text statt der gekürzten Quellenkarte.
- Text- und Markdown-Viewer markieren die relevante Passage direkt im
  Dokument-DOM mit `<mark>` und springen beim Quellenwechsel zur Fundstelle.
- Quellenmarker wie `[S2]` im Antworttext sind klickbar und synchronisieren
  Viewer, aktive Quelle und Quellenleisten.

## 2.4.9 - 2026-06-26

### Fixed

- Wissenssuche staffelt Bibliotheken, Arbeitsbereich und Quellen responsiver,
  sodass Quellen auf mittleren Viewports als kompakte Leiste im Arbeitsbereich
  erhalten bleiben.
- Dokumentviewer, Trefferpassage, Antwortbereich und Composer sind kompakter
  und priorisieren die Antwort direkt unter dem Dokument.
- Text- und Markdown-Quellen werden als sichere dunkle Textvorschau statt als
  dominante weiße Browserfläche angezeigt.

## 2.4.8 - 2026-06-26

### Added

- Wissenssuche kann Antworten optional über einen OpenAI-kompatiblen
  `/chat/completions`-Endpunkt erzeugen, der per `SEARCH_ANSWER_LLM_*`
  konfiguriert wird.

### Fixed

- Antwortgenerierung fällt bei nicht konfiguriertem oder fehlerhaftem
  OpenAI-kompatiblem Modell weiterhin sauber auf RAGFlow beziehungsweise die
  lokale quellengestützte Kurzantwort zurück.

## 2.4.7 - 2026-06-26

### Fixed

- Wissenssuche blendet den leeren Dokumentviewer-Zustand zuverlässig aus, sobald
  eine Quelle im nativen Viewer geladen wird.
- Antwortmodus zeigt Fundstellen kompakt unter der Antwort und nutzt Toast-
  Feedback für Passage-Kopieren, damit die Antwort nicht nach unten springt.
- Quellengestützter Antwort-Fallback formuliert eine lesbare Zusammenfassung
  mit Quellenmarkern statt technischer Roh-Auszüge.

## 2.4.6 - 2026-06-25

### Added

- Search-Service erzeugt aus gefundenen Quellen eine RAGFlow-gestützte Antwort
  mit Quellenmarkern und fällt bei RAGFlow-Problemen auf eine kurze
  quellengestützte Antwort zurück.
- Wissenssuche erhält einen mittigen Dokumentviewer mit sicherem
  Connector-Proxy, Quellen-Auswahl, Antwortbereich und Chatfeld am unteren
  Rand.
- Lokaler HTTPS-Edge unterstützt zusätzlich `https://search.top.secret/search`
  für Portainer-/Compose-Tests.

## 2.4.5 - 2026-06-18

### Fixed

- Release-Metadaten, README-Beispiele und Betreiberhinweise auf den aktuellen
  GHCR-Release-Tag synchronisiert.

## 2.4.4 - 2026-06-18

### Fixed

- Controller bleibt beim Start stabil, wenn RAGFlow- oder OpenWebUI-Template-
  Abfragen vorübergehend nicht verfügbar sind.
- RAGFlow-`search_template`-Auflösung toleriert ältere RAGFlow-Versionen ohne
  Search-App-Endpunkte und fällt kontrolliert auf Chat- oder Built-in-Defaults
  zurück.
- OpenWebUI-Pipe zeigt im Deny-Fall nur die knappe Nutzerantwort
  `Kein Zugriff auf diese Bibliothek.`.

## 2.4.3 - 2026-06-18

### Fixed

- Search-Webseite nutzt im Kopfbereich ein verständliches Such-/Quellen-Icon
  statt eines einzelnen Buchstaben-Watermarks.
- Placeholder im Suchfeld und Bibliotheksfilter sind nutzerorientiert
  formuliert.

## 2.4.2 - 2026-06-18

### Added

- Gemeinsames Evidence-/Source-Modell für Search-Service und OpenWebUI-Pipe
  ergänzt, damit Quellen, Locators, Preview-Links und Original-Links konsistent
  dargestellt werden.
- Search-Service zeigt Quellen jetzt mit Quellenpanel, Hover-/Fokus-Vorschau,
  signiertem Evidence-Viewer, Locator-Chips und bestmöglichen Original- bzw.
  Textfragment-Links.

### Changed

- Antwortmodus und OpenWebUI-Pipe geben Quellen kompakt, klickbar und ohne rohe
  RAGFlow-Projektionsmarker wie `BEGIN SOURCE CONTENT` aus.

## 2.4.1 - 2026-06-17

### Fixed

- Antwortquellen in der Search-Webseite werden als klickbare Quellenkarten mit
  direktem `Quelle öffnen`-Link gerendert, statt nur als statische
  Ergebnisliste.

## 2.4 - 2026-06-17

### Fixed

- Der ACL-Snapshot löst technische Seafile-User-IDs aus Direct User Shares über
  die Admin-User-Liste auf `contact_email` auf. Das deckt Seafile-LDAP-/SSO-
  Installationen ab, bei denen `/api/v2.1/admin/shares/` nur interne
  `@auth.local`-IDs liefert.

## 2.3 - 2026-06-17

### Fixed

- Der ACL-Snapshot bevorzugt bei Seafile-LDAP-/SSO-Identitäten jetzt
  `contact_email` bzw. `owner_contact_email` vor technischen internen
  Seafile-IDs wie `@auth.local`. Dadurch treffen Search-Service und
  OpenWebUI-Pipe dieselbe Allow/Deny-Entscheidung für reale Nutzer-Mailadressen.

## 2.2 - 2026-06-17

### Fixed

- Search-Ergebnisse zeigen für echte RAGFlow-Retrieval-Antworten wieder
  nutzerfreundliche Dokumentnamen und Quellpfade, auch wenn RAGFlow diese nur
  über `document_keyword` oder `doc_aggs` liefert.
- Die zentrale Authz-API liefert bei `filter-profiles` alle für die
  Suchoberfläche benötigten Profilfelder zurück.
- OpenWebUI-Pipes behandeln technische RAGFlow-Backendfehler nicht mehr als
  generierte Nutzerantwort und zeigen bei Connector-403 nur die sichere Meldung
  `Kein Zugriff auf diese Bibliothek.`.

## 2.1 - 2026-06-16

### Added

- ACL-Snapshot und zentrale Authz-API für nutzerbezogene RAGFlow-Abfragen
  ergänzt. Der Connector-Core spiegelt Seafile-Bibliotheksrechte, expandiert
  Gruppen-Shares und entscheidet fail-closed für Search-Service und
  OpenWebUI-Pipe.
- Separater `connector search-server` mit nutzerfreundlicher
  Wissenssuche, Trusted-Header-Auth, SearchProfiles, Retrieval-Suche,
  Quellen-/Vorschau-Aktionen und Portainer-/Compose-/Swarm-Artefakten.

### Changed

- OpenWebUI-Proxy-Abfragen prüfen vor RAGFlow-Aufrufen dieselbe zentrale
  ACL-Entscheidung wie der Search-Service. Die OpenWebUI-Artefaktversion wurde
  dafür auf 25 erhöht.
- Runtime-Entwicklungsabhängigkeiten aus Dependabot aktualisiert:
  `cryptography` 49.0.0, `ruff` 0.15.17 und `pytest` 9.1.0.

## 2.0 - 2026-06-04

### Added

- Demo-Video zum vollständigen Seafile -> RAGFlow -> OpenWebUI-Workflow ins
  Repository aufgenommen und in der README eingebunden.
- Der Dashboard-OpenWebUI-Tab kann connector-eigene Pipes, RAGFlow-Chats und
  RAGFlow-Datasets gezielt löschen, ohne die zugehörige Seafile-Bibliothek zu
  löschen.

### Changed

- README, Changelog, Release-Prozess und Versionshinweise auf Version `2.0`
  vorbereitet.
- Dokumentation auf widersprüchliche Demo-, Release- und Encoding-Hinweise
  geprüft; sichere Korrekturen wurden gezielt eingearbeitet.
- Docker-Kontext bereinigt, damit die Repository-Demo-Videos nicht unnötig in
  lokale Container-Images gelangen.
- Docker-Image-Workflow unterstützt zusätzlich `vX.Y`-Tags wie `v2.0` als
  Image-Tag `2.0`.
- Normale OpenWebUI-/RAGFlow-Chatantworten kuratieren sichtbare Quellen auf
  zitierte Dokumente, damit irrelevante Treffer nicht mehr als scheinbare
  Antwortbelege erscheinen. Die OpenWebUI-Pipe-Artefaktversion wurde dafür auf
  24 erhöht.

### Fixed

- RAGFlow-Template-Datasets mit `graphrag.batch_chunk_token_size` aus RAGFlow
  0.25.4 können wieder als Vorlage für neu angelegte Connector-Datasets dienen.
- Die Dashboard-Löschung von OpenWebUI-Pipes erkennt auch die von OpenWebUI
  gespeicherte kompakte Function-Metadatenform sicher als connector-eigen.

## 0.1.13 - 2026-06-02

### Changed

- Auditierte OpenWebUI-Nachweise werden als schmale Quellenblöcke statt als
  breite Markdown-Tabelle gerendert, damit das Evidenzregister in OpenWebUI ohne
  horizontales Abschneiden lesbar bleibt.
- Die OpenWebUI-Artefaktversion wurde auf 22 erhöht, damit vorhandene Pipes das
  korrigierte Audit-Rendering sicher übernehmen.

## 0.1.12 - 2026-06-02

### Added

- OpenWebUI-Pipe-Auditmodus als Standard: Antworten zeigen zuerst die
  Nutzerantwort und danach ein deutsches Evidenzregister mit Audit-Status,
  Claim-Abdeckung, Rollen, Match-Typ, Audit-Score und sicheren
  Lauf-Metadaten.
- Quellen-Normalisierung mit `source_role`, `match_type`, `audit_score`,
  `score_components`, `used_in_answer`, Claim-IDs und ursprünglicher
  RAGFlow-Provider-Zitation.

### Changed

- RAGFlow-Referenzen werden nach Audit-Relevanz sortiert und anschließend
  stabil als `S1`, `S2`, ... neu nummeriert. Exakte Marker-, ID-, Hash-,
  Ticket- und Dateinamenfragen priorisieren Exact Matches vor semantisch
  ähnlichen Treffern.
- OpenWebUI-Pipe-Defaults wechseln von nativen Citation-Events auf den
  sichtbaren Auditmodus, damit OpenWebUI keine zweite, anders nummerierte
  Quellenliste erzeugt.

### Fixed

- Antwortmarker wie `[ID:3]` werden nach der Audit-Sortierung gegen die
  ursprüngliche RAGFlow-Referenz-ID aufgelöst und sichtbar konsistent als
  `[S1]`/`[S2]` gerendert.

## 0.1.11 - 2026-06-02

### Added

- Dashboard-Aktion zum Bereinigen toter Sync-Jobs direkt im `Sync-Jobs`-
  Health-Eintrag. Die Jobs werden auf `cancelled` gesetzt, damit die
  Historie erhalten bleibt und der aktive Dead-Job-Zähler zurück auf 0 fällt.

### Changed

- Tote Sync-Jobs gelten im Dashboard als Wartungsbedarf und nicht mehr als
  harter Connector-Fehler, solange die übrigen Systemchecks gesund sind.

## 0.1.10 - 2026-06-01

### Changed

- OpenWebUI-Pipes trennen echte Chat-Antworten strikt von Retrieval-only-
  Ergebnissen und markieren Läufe nur noch dann als generiert, wenn ein
  belastbarer Antwortpfad oder der Synthese-Fallback genutzt wurde.
- Native OpenWebUI-Citations sind der Standard-Quellenkanal; Markdown-
  Nachweistabellen sind expliziter Audit- oder Debug-Modus.
- RAGFlow-/OpenAI-kompatible Antwort- und Referenzpfade, Quellen-Dedup,
  Score-Sortierung und redigierte Proxy-Diagnosen wurden präzisiert.

### Fixed

- Quellen- oder Dateititel können nicht mehr als generierte Antwort
  durchrutschen.

## 0.1.9 - 2026-06-01

### Added

- Dashboard-Tab `Prüfablauf`, der mit dem Seafile-API-Key sichtbare
  Bibliotheken anzeigt und ausgewählte Bibliotheken für RAGFlow-Dataset-,
  Dokument-, Chat- und OpenWebUI-Tool-/Pipe-Sync starten kann.
- Fake-basierter Integrationstest und deutsch/englisches Runbook für den
  manuell prüfbaren Seafile-RAGFlow-OpenWebUI-Ablauf.

### Changed

- OpenWebUI-Sync kann auf ausgewählte Repo-IDs begrenzt werden, damit
  Dashboard-gesteuerte Prüfläufe keine ungewählten Bibliotheken anfassen.
- Dashboard-, Betriebs- und Konfigurationsdokumentation beschreibt den
  Controller-Workflow und grenzt ihn vom Standalone-Status-Dashboard ab.

## 0.1.8 - 2026-06-01

### Changed

- Runtime-Abhängigkeiten aktualisiert: `python-multipart` auf `0.0.30` und
  `typer` auf `0.26.4`.
- Entwicklungs- und Testabhängigkeiten aktualisiert: `pytest-asyncio` auf
  `1.4.0` und `ruff` auf `0.15.15`.

### Fixed

- Dependabot-Lockfile-Aktualisierungen wurden auf dem aktuellen `master`
  zusammengeführt und gegen den Verify-Runner geprüft.

## 0.1.7 - 2026-06-01

### Added

- WSL-Verify-Wrapper für Windows-Hosts, der `uv` in einer WSL-eigenen
  Umgebung ausführt und dadurch bestehende Windows-`.venv`-Verzeichnisse nicht
  berührt.
- Reproduzierbarer Docker-Mock-Smoke im Verify-Runner, der ein lokales
  Connector-Test-Image aus dem aktuellen Checkout baut, Test-Volumes vor und
  nach dem Lauf bereinigt und `check-live` sowie `/health/tls` prüft.

### Changed

- Periodische Discovery-, Delta-Sync-, Reconcile-, RAGFlow-Template-Refresh-
  und OpenWebUI-Sync-Defaults sind auf 30 Minuten konsolidiert und in
  Konfiguration, Compose-/Portainer-/Swarm-Beispielen sowie Dokumentation
  beschrieben.
- Dashboard- und Export-Texte wurden in weiteren Betreiberansichten
  konsistent lokalisiert, inklusive First-Paint-Platzhaltern, Systemtabellen,
  Audit-Export und OpenWebUI-/Log-Labels.
- Der lokale HTTPS-Mock-Smoke nutzt für `/health/tls` denselben Basic-Auth-Pfad
  wie die Betreiberbeispiele.

### Fixed

- Parallele Controller-, Worker- und Reconciler-Starts serialisieren die
  PostgreSQL-Schema-Initialisierung per Advisory Lock.
- `language_from_settings()` bleibt ohne explizite Connector-Sprache beim
  dokumentierten deutschen Default, unabhängig von der Host-Locale.
- README-CLI-Beispiele nutzen die existierenden Typer-Kommandos `dashboard`,
  `controller`, `worker` und `reconciler`.
- Kurzlebige Runtime-Prüfpfade schließen Datenbank- und Redis-Ressourcen
  deterministischer.

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
