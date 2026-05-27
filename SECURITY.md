# Security Policy

🌐 Sprachen: **Deutsch** | [English](SECURITY.en.md)

## Unterstützte Versionen

Das Repository enthält derzeit die Paketversion `0.1.1` in `pyproject.toml` und
keine dokumentierten Release-Branches. Sicherheitsprüfungen beziehen sich daher
auf den aktuellen Default-Branch, bis Maintainer einen abweichenden
Release-Prozess veröffentlichen.

## Sicherheitsprobleme melden

Bitte veröffentliche keine sensiblen Schwachstellendetails als öffentliches
Issue. Nutze stattdessen GitHub Private Vulnerability Reporting oder GitHub
Security Advisories, sofern sie für dieses Repository aktiviert sind.

Wenn dieser private Kanal nicht verfügbar ist, erstelle ein öffentliches Issue
ohne Exploit-Details und bitte um einen privaten Meldeweg. Füge keine Tokens,
Passwörter, privaten Schlüssel, produktiven Zertifikate, Datenbank-Dumps oder
vollständigen Produktionslogs an.

## Was eine gute Meldung enthält

- Betroffene Komponente, z. B. Connector-Proxy, OpenWebUI-Sync, TLS-Konfiguration oder Deployment-Artefakt.
- Reproduzierbare Schritte in einer isolierten Testumgebung.
- Erwartetes und tatsächliches Verhalten.
- Betroffene Version oder Commit-Hash.
- Risikoeinschätzung ohne Veröffentlichung sensibler Details.

## Erwarteter Ablauf

Maintainer prüfen die Meldung, reproduzieren das Verhalten soweit möglich und
entscheiden über Fix, Dokumentation oder Konfigurationshinweis. Es gibt keine
Sicherheitsgarantie und keine feste Reaktionszeit, solange das Repository keinen
separaten Maintainer-SLA veröffentlicht.

## Projektgrenzen

Der Connector ersetzt Seafile, RAGFlow oder OpenWebUI nicht. Sicherheitsfragen
in diesen externen Systemen müssen zusätzlich bei den jeweiligen Projekten oder
Betreibern gemeldet werden. `*_VERIFY_SSL=false` ist nur für Diagnose und
Entwicklung gedacht und darf nicht als produktive Empfehlung verstanden werden.
