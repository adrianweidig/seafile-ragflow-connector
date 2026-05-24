## Zusammenfassung

-

## Art der Änderung

- [ ] Dokumentation
- [ ] Test oder CI
- [ ] Bugfix
- [ ] Feature
- [ ] Deployment, Compose, Portainer oder Swarm
- [ ] Security- oder TLS-bezogene Änderung

## Prüfung

- [ ] `python scripts/verify.py --skip-compose`
- [ ] `python scripts/verify.py --with-compose`
- [ ] Einzelcheck dokumentiert:
- [ ] Nicht ausgeführt, Begründung:

## Betriebs- und Sicherheitscheck

- [ ] Keine Secrets, Tokens, privaten Schlüssel, produktiven Zertifikate oder vollständigen Env-Dateien enthalten.
- [ ] Keine öffentlichen CLI-Flags, Env-Namen, Dateiformate oder Standardwerte unbegründet geändert.
- [ ] README, `docs/`, `connector.env.example` oder Deployment-Beispiele sind aktualisiert, falls Nutzung oder Betrieb betroffen sind.
- [ ] Delete-/Repair-Logik respektiert Seafile als Quelle der Wahrheit.

## Hinweise für Reviewer
