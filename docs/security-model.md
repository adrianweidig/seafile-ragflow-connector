# Sicherheitsmodell

Der Connector bleibt eine kontrollierte Sync- und Autorisierungsinstanz. Er ist
kein generischer Datentunnel und kein Zwangspfad für alle Benutzeroberflächen.
Die neue Search-Rolle trennt Secrets, Benutzeridentität und RAGFlow-Abfragen
klar voneinander.

## Rollen

| Rolle | Aufgabe | Seafile-Admin-Token | RAGFlow-Zugriff |
| --- | --- | --- | --- |
| `connector-controller` | Seafile Discovery, Dataset-Provisioning, Datei-Sync-Planung, ACL-Snapshot, Authz-API | ja | ja |
| `connector-worker` | Datei-Download, Upload zu RAGFlow, Parse-Steuerung | nein, nutzt Sync-Token | ja |
| `connector-reconciler` | Repair und Drift-Korrektur | ja, über Core-Konfiguration | ja |
| `connector-dashboard` | Admin-Dashboard und Diagnose, optional | indirekt über Core | nein als Benutzeroberfläche |
| `connector-search` | nutzernahe Wissenssuche | nein | nur nach Authz-allow |
| OpenWebUI-Pipe | Chat-/Retrieval-Nutzung in OpenWebUI | nein | nur nach Authz-allow |

Der Seafile-Admin-Token gehört ausschließlich in den Connector-Core. Der
Search-Service und die OpenWebUI-Pipe bekommen keinen Seafile-Admin-Token und
keinen Seafile-Sync-Token. Sie fragen den Connector-Core nur:

```text
Darf Nutzer X auf Bibliothek/Dataset Y suchen?
```

Erst bei `decision=allow` wird RAGFlow abgefragt.

## Seafile ist Berechtigungsquelle

RAGFlow kennt Seafile-Berechtigungen nicht. Der Connector spiegelt deshalb
regelmäßig Bibliotheksrechte aus Seafile in einen ACL-Snapshot:

```text
GET /api/v2.1/admin/libraries/
GET /api/v2.1/admin/shares/?repo_id=<repo_id>&share_type=user
GET /api/v2.1/admin/shares/?repo_id=<repo_id>&share_type=group
GET /api/v2.1/admin/groups/{group_id}/members/
```

Es zählen ausschließlich Bibliotheksrechte:

- Owner erhalten immer `admin`.
- Direkte User-Shares werden übernommen.
- Gruppen-Shares werden auf die Gruppenmitglieder expandiert.
- Wenn ein Nutzer mehrere Rechte bekommt, gewinnt die höchste Berechtigung:
  `admin > rw > r`.

Unterordnerrechte werden nicht berücksichtigt. Share-Links erzeugen keine
personenbezogene Berechtigung. Beide Entscheidungen sind absichtlich
fail-closed: Ohne eindeutige personenbezogene Bibliotheksberechtigung gibt es
keine RAGFlow-Abfrage.

## Zentrale Authz-API

Die interne Authz-API wird vom Connector-Core bereitgestellt:

```text
POST /api/authz/check
POST /api/authz/filter-profiles
GET  /api/authz/profiles
```

Technische Komponenten authentifizieren sich mit:

```http
Authorization: Bearer <AUTHZ_API_SHARED_SECRET>
```

Dieses Secret authentifiziert nur die aufrufende Komponente. Die
Benutzeridentität bleibt Teil des Request-Bodys beziehungsweise der internen
Authz-Header. Die E-Mail ist der primäre Match-Key; der Username wird für
Audit, Logging und spätere Mapping-Strategien mitgeführt.

## Fail-Closed

Mit `AUTHZ_API_FAIL_CLOSED=true` gilt:

- unbekannte oder zu alte ACL: deny
- unbekannter Nutzer: deny
- fehlende E-Mail und kein eindeutiger E-Mail-Username: deny
- unbekanntes Dataset oder Repo: deny
- fehlendes Repo/Dataset-Mapping: deny
- nicht bereites oder deaktiviertes SearchProfile: deny

Der Search-Service und die OpenWebUI-Pipe geben an Nutzer nur knappe,
verständliche Fehlermeldungen aus. Interne Deny-Gründe werden geloggt, aber
nicht als detaillierte Zugriffsinformation an Endnutzer weitergegeben.

## Quellen-Preview und Original-Links

Die verbesserte Quellen-UX ändert das Sicherheitsmodell nicht. Search-Service
und OpenWebUI-Pipe fragen RAGFlow weiterhin nur nach positiver Authz-Entscheidung
ab. Treffer erhalten danach signierte Preview-Links. Diese Tokens enthalten nur
die bereits autorisierte Trefferpassage und Metadaten wie Dokumentname,
Bibliothek, Seite, Zeile, Score und Originallink.

Der Evidence-Viewer ist damit eine Fundstellenanzeige, kein generischer
Seafile-Dateidownload. Original-Links zeigen den Browser direkt zu Seafile und
verwenden nach Möglichkeit `#page=` oder Browser-Textfragmente. Wenn Seafile,
der Browser oder ein Login-Redirect diese Sprungmarken nicht unterstützt, bleibt
die signierte Connector-Vorschau die verlässliche Fundstelle.

## Konfigurationsanker

```env
AUTHZ_API_ENABLED=true
AUTHZ_API_SHARED_SECRET=change-me-authz-secret
AUTHZ_API_ALLOW_NETWORKS=
AUTHZ_API_FAIL_CLOSED=true
AUTHZ_API_MAX_ACL_AGE_SECONDS=7200

SEARCH_ACL_SYNC_ENABLED=true
SEARCH_ACL_SYNC_INTERVAL_SECONDS=1800
SEARCH_ACL_INCLUDE_SUBFOLDER_PERMISSIONS=false
SEARCH_ACL_INCLUDE_SHARE_LINKS=false
```

`AUTHZ_API_ALLOW_NETWORKS` kann CIDR-Netze zusätzlich zum Bearer-Secret
einschränken. Leer bedeutet keine zusätzliche IP-Prüfung durch den Connector;
Reverse Proxy, Docker-Netz und Firewall bleiben trotzdem Teil der
Produktionshärtung.
