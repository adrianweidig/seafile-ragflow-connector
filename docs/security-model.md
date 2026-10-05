# Sicherheitsmodell

Der Connector bleibt eine kontrollierte Sync- und Autorisierungsinstanz. Er ist
kein generischer Datentunnel und kein Zwangspfad für alle Benutzeroberflächen.
Die neue Search-Rolle trennt Secrets, Benutzeridentität und RAGFlow-Abfragen
klar voneinander.

## Rollen

| Rolle | Aufgabe | Seafile-Admin-Token | RAGFlow-Zugriff |
| --- | --- | --- | --- |
| `connector-controller` | Seafile Discovery, Dataset-Provisioning, Datei-Sync-Planung, ACL-Snapshot, Authz-API und optional interaktive Dashboard-Administration | ja | ja |
| `connector-worker` | Datei-Download, Upload zu RAGFlow, Parse-Steuerung | nein, nutzt Sync-Token | ja |
| `connector-reconciler` | Repair und Drift-Korrektur | ja, über Core-Konfiguration | ja |
| eigenständiges `connector dashboard` | lesendes Status-Dashboard und Diagnose, optional | indirekt über State/Health | nein als Benutzeroberfläche |
| `connector-search` | nutzernahe Wissenssuche | nein | nur nach Authz-allow |
| OpenWebUI-Pipe | Chat-/Retrieval-Nutzung in OpenWebUI | nein | nur nach Authz-allow |

Der Seafile-Admin-Token gehört ausschließlich in den Connector-Core. Der
Search-Service und die OpenWebUI-Pipe bekommen keinen Seafile-Admin-Token und
keinen Seafile-Sync-Token. Sie fragen den Connector-Core nur:

```text
Darf Nutzer X auf Bibliothek/Dataset Y suchen?
```

Erst bei `decision=allow` wird RAGFlow abgefragt. Der Dokumentviewer folgt
derselben Grenze: `connector-search` prüft nur signierte Preview-Tokens und
Nutzerheader, ruft den Core mit Bearer-Secret auf und streamt freigegebene
Dateien same-origin zurück. Der eigentliche Seafile-Download passiert im Core
über den bestehenden Sync-Client; HTML/Markdown werden nicht als aktives HTML
ausgeliefert.

`connector-search` darf zusätzlich den Connector-State lesen, um RAGFlow-
Anzeigenamen wieder auf echte Seafile-Pfade abzubilden. Diese Datenbanknutzung
ist nur Mapping-/Viewer-Infrastruktur; die fachliche Berechtigung bleibt die
Authz-Prüfung gegen den ACL-Snapshot.

## Dashboard-Admin-Grenze

Nur das im `connector-controller` eingebettete Dashboard darf Connector-Arbeit
steuern. Die Fähigkeit ist standardmäßig aus und wird erst durch
`CONNECTOR_DASHBOARD_CONTROL_ENABLED=true` aktiviert. Die Settings-Validierung
verlangt dann zusätzlich ein aktiviertes Dashboard sowie nicht leere Basic-
Auth-Werte. Jede Mutation benötigt `Content-Type: application/json` und
`X-Connector-Admin-Action: 1`; globaler Stop sowie Stop/Cancel eines Laufs außerdem
`{"confirm":"STOP"}`. Bestehende Authz- und OpenWebUI-Proxy-Endpunkte nutzen
weiterhin ihre eigenen Bearer-Secrets und werden nicht an den Browserheader
gekoppelt.

Ein isolierter Erststart setzt zusätzlich vor dem ersten Runtime-Start
`CONNECTOR_AUTOMATION_INITIAL_STATE=stopped`. Dieser einmalige Wert hält
Scheduler und Queue bis zur authentifizierten Freigabe; ein persistierter
Operatorzustand wird nie aus der Env überschrieben.

Der feste Header ist eine CSRF-/Browser-Aktionsmarkierung, kein Secret und
keine eigene Authentifizierung. Seine Schutzwirkung setzt die JSON-Grenze, das
fehlende permissive CORS und gültige Basic Auth voraus. Ein Reverse Proxy darf
ihn daher nicht als vertrauenswürdige Identität interpretieren oder die Admin-
API pauschal für Cross-Origin-Aufrufe freigeben.

Basic Auth muss außerhalb einer reinen Localhost-Bindung über HTTPS
transportiert werden. Dashboard-Steuerung bekommt weder Docker-Socket noch
Portainer-Zugangsdaten und kann keine Container starten oder stoppen. Globale,
bibliotheksspezifische und laufbezogene Zustände liegen in PostgreSQL und
werden als Adminaktion mit Benutzer, Ziel, Vorher-/Nachher-Zustand und Ergebnis
auditiert; Passwörter, Tokens und andere Secrets werden nicht gespeichert.

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

### Optionale technische Nur-Lese-Freigabe

`SEAFILE_SYNC_USER_AUTO_SHARE_ENABLED` ist standardmäßig `false`. Im Opt-in-
Betrieb muss `SEAFILE_SYNC_USER_EMAIL` gesetzt sein und exakt zur kanonischen
Identität des `SEAFILE_SYNC_USER_TOKEN` passen. Der Connector verifiziert dies
über `GET /api2/account/info/`, bevor er eine Freigabe erwägt.

Der Schalter wirkt retroaktiv auf den sichtbaren ausführbaren Bestand: Der
erste automatische Discovery-Zyklus prüft alle bereits vorhandenen geeigneten
und ausführbaren Bibliotheken, nicht nur künftig neu angelegte. Somit können
bei der ersten Aktivierung mehrere technische Freigaben entstehen.
Deaktivierte oder pausierte Bibliotheken werden dabei nicht automatisch
freigegeben und erst nach erneuter Aktivierung geprüft.

Nur ein HTTP 403 beim Root-Probe der konkreten Bibliothek darf einen
`POST /api/v2.1/admin/shares/` mit `share_type=user`, `path=/` und
`permission=r` auslösen. Erfolg wird weder aus HTTP 200 noch aus dem
POST-Payload abgeleitet: Ein erneutes GET der direkten User-Shares und ein
zweiter Root-Probe sind Pflicht. Bestehende `r`- oder `rw`-Freigaben bleiben
unverändert. Verschlüsselte und virtuelle Bibliotheken werden niemals durch
diesen Pfad freigegeben; automatische Rücknahme oder Berechtigungs-Downgrade
gibt es nicht.

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

Im Modus `trusted_header` akzeptiert Search diese Identität nur von der
unmittelbaren Peer-IP eines Netzes aus `SEARCH_TRUSTED_PROXY_CIDRS`. Der
Reverse Proxy entfernt vom Client gelieferte Identitätsheader und setzt sie
aus der authentifizierten Session neu. Eine öffentliche Produktionsbindung
ohne Proxy-Allowlist wird beim Start abgelehnt; der Swarm-Stack veröffentlicht
Search standardmäßig nicht über das Routing-Mesh.

Im Modus `openwebui_ldap` übergibt Search die Anmeldedaten serverseitig an den
konfigurierten LDAP-Endpunkt von OpenWebUI. OpenWebUI bleibt damit für
LDAP-Bind, Nutzersuche und Gruppensynchronisierung zuständig. Search übernimmt
nur die bestätigte Identität und erstellt daraus eine eigene HMAC-signierte,
zeitlich begrenzte HttpOnly-Sitzung. OpenWebUI-Tokens und LDAP-Passwörter werden
weder in die Sitzung aufgenommen noch im Connector gespeichert.

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

Jeder Preview- und Dokumentviewer-Token enthält eine Version, `iat`, `exp`,
`purpose` und `aud`. Signatur, Ablauf, Zweck und Ziel werden zentral geprüft;
die Standardlebensdauer beträgt 15 Minuten. Fehlende Claims und alte,
unbegrenzte Tokens werden abgelehnt. HTTP-Access-Logs entfernen sämtliche
Querystrings, damit weder Token noch Trefferpassagen in Debug-Logs landen.

Der Evidence-Viewer ist damit eine Fundstellenanzeige, kein generischer
Seafile-Dateidownload. Original-Links zeigen den Browser direkt zu Seafile und
verwenden nach Möglichkeit `#page=` oder Browser-Textfragmente. Wenn Seafile,
der Browser oder ein Login-Redirect diese Sprungmarken nicht unterstützt, bleibt
die signierte Connector-Vorschau die verlässliche Fundstelle.

Vom Seafile-API gelieferte Download-URLs dürfen nur `http` oder `https`
verwenden und müssen zur normalisierten Seafile-Basis-Origin, zu einem bewusst
konfigurierten Rewrite-Ziel oder zu `SEAFILE_DOWNLOAD_ALLOWED_ORIGINS` gehören.
Erst nach dieser Prüfung wird der Sync-Authorization-Header gesetzt. Redirects
werden nicht verfolgt; Größenlimits werden vorab über `Content-Length` und
zusätzlich während des Streamings erzwungen.

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
