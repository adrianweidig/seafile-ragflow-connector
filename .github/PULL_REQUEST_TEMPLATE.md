## Zusammenfassung
## Summary

-

## Art der Änderung
## Type of Change

- [ ] Dokumentation
- [ ] Documentation
- [ ] Test oder CI
- [ ] Test or CI
- [ ] Bugfix
- [ ] Feature
- [ ] Deployment, Compose, Portainer oder Swarm
- [ ] Security- oder TLS-bezogene Änderung
- [ ] Security or TLS-related change

## Prüfung
## Verification

- [ ] `python scripts/verify.py --skip-compose`
- [ ] `python scripts/verify.py --with-compose`
- [ ] Einzelcheck dokumentiert:
- [ ] Individual check documented:
- [ ] Nicht ausgeführt, Begründung:
- [ ] Not run, reason:

## Betriebs- und Sicherheitscheck
## Operations and Security Check

- [ ] Keine Secrets, Tokens, privaten Schlüssel, produktiven Zertifikate oder vollständigen Env-Dateien enthalten.
- [ ] No secrets, tokens, private keys, productive certificates, or complete environment files are included.
- [ ] Keine öffentlichen CLI-Flags, Env-Namen, Dateiformate oder Standardwerte unbegründet geändert.
- [ ] No public CLI flags, environment names, file formats, or defaults were changed without rationale.
- [ ] README, `docs/`, `connector.env.example` oder Deployment-Beispiele sind aktualisiert, falls Nutzung oder Betrieb betroffen sind.
- [ ] README, `docs/`, `connector.env.example`, or deployment examples are updated when usage or operations are affected.
- [ ] Delete-/Repair-Logik respektiert Seafile als Quelle der Wahrheit.
- [ ] Delete/repair logic respects Seafile as the source of truth.

## Hinweise für Reviewer
## Reviewer Notes
