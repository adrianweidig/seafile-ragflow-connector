# Support

Dieses Repository bietet Community-Support über GitHub Issues und Pull
Requests. Es gibt keinen veröffentlichten kommerziellen Supportkanal und keinen
SLA.

## Geeignete Issues

- Reproduzierbare Fehler im Connector-Code.
- Widersprüche oder Lücken in README, `docs/` oder Deployment-Beispielen.
- Probleme mit lokaler Compose-/Portainer-Konfiguration, wenn Logs und
  relevante Env-Namen ohne Secrets bereitgestellt werden.
- Verbesserungsvorschläge für Tests, CI oder Developer Experience.

## Vor einem Issue

1. Prüfe [README.md](README.md), [docs/README.md](docs/README.md) und [docs/troubleshooting-ssl.md](docs/troubleshooting-ssl.md).
2. Führe, wenn möglich, `python scripts/verify.py --skip-compose` aus.
3. Entferne Secrets aus Logs, Screenshots und Env-Auszügen.
4. Beschreibe, ob Docker Compose, Portainer, Swarm oder ein lokales TLS-Lab betroffen ist.

## Keine geeigneten Issues

- Produktive Zugangsdaten, Tokens, private Schlüssel oder vollständige Env-Dateien.
- Sicherheitslücken mit Exploit-Details. Nutze dafür [SECURITY.md](SECURITY.md).
- Allgemeiner Support für Seafile, RAGFlow oder OpenWebUI außerhalb der Connector-Anbindung.

## Nützliche Informationen

- Connector-Version oder Commit-Hash.
- Betriebssystem und Docker-/Compose-Version, wenn Deployment betroffen ist.
- Relevante Env-Namen und Werte nur als Platzhalter oder redigiert.
- Auszug aus Controller-, Worker- oder Reconciler-Logs ohne Secrets.
- Erwartetes und tatsächliches Verhalten.
