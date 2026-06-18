# OpenWebUI-ACL

OpenWebUI bleibt optional. Wenn OpenWebUI-Pipes genutzt werden, fragen sie vor
jeder RAGFlow-Abfrage den Connector-Core nach Autorisierung. OpenWebUI bekommt
keinen Seafile-Admin-Token und keinen Seafile-Sync-Token.

## Datenfluss

```text
OpenWebUI Nutzerfrage
  -> OpenWebUI-Pipe
  -> Connector-Core /api/openwebui/proxy/chat oder /query
  -> zentrale Authz-Prüfung
  -> RAGFlow nur bei allow
```

Der Connector-Core kennt das OpenWebUI-Mapping, löst daraus Dataset und Repo
auf und ruft dieselbe Access-Control-Entscheidung wie der Search-Service auf.

## Nutzeridentität

Die Pipe sendet die verfügbare OpenWebUI-Nutzeridentität im Payload:

```json
{
  "user": {
    "username": "olaf",
    "email": "olaf@example.local"
  }
}
```

Die E-Mail ist der primäre Match-Key. Ein Username im Format
`username@domain` wird ebenfalls als E-Mail-Adresse geprüft. Wenn OpenWebUI nur
einen kurzen Login-Namen wie `olaf` liefert, erlaubt der Connector den Zugriff
nur dann, wenn dieser lokale Teil in der effektiven ACL der Bibliothek eindeutig
ist. Mehrdeutige kurze Namen bleiben fail-closed.

## Allow und Deny

Bei `allow` führt der Connector-Core die RAGFlow-Abfrage aus und gibt Antwort
und Quellen an OpenWebUI zurück.

Bei `deny` wird RAGFlow nicht angesprochen. Die Pipe beziehungsweise der Proxy
geben eine knappe nutzerfreundliche Meldung zurück:

```text
Kein Zugriff auf diese Bibliothek.
```

Der interne Deny-Grund wird geloggt, aber nicht detailliert an Endnutzer
weitergegeben.

## Quellenanzeige in OpenWebUI

Die Pipe zeigt im Standardmodus zuerst den Antworttext und danach eine kompakte
Quellenliste. Lange Audit-Tabellen sind nicht mehr der Standard, bleiben aber
für Administratoren und Prüfzwecke verfügbar.

Standardverhalten neuer Pipe-Artefakte:

```env
SOURCE_DISPLAY_MODE=compact
SOURCE_MARKDOWN_MODE=compact
APPEND_SOURCE_OVERVIEW=true
OPENWEBUI_SOURCE_PREVIEW_MODE=connector_viewer
```

Die kompakte Liste enthält pro Quelle:

- Quellenlabel, z. B. `S1`
- Dokumentname
- Bibliothek/Dataset
- Fundstelle, z. B. Seite oder Zeile
- kurzes Snippet
- Link zur Connector-Vorschau
- Link zum Originaldokument, wenn ein sicherer Browserlink erzeugt werden kann

OpenWebUI kann keine eigene NotebookLM-artige Seitenleiste oder Hoverkarten
rendern. Deshalb nutzt die Pipe native Citation-Events und Markdown-Links. Der
reichere Evidence-Viewer öffnet sich über den Vorschau-Link.

Für Audits kann weiterhin gesetzt werden:

```env
SOURCE_DISPLAY_MODE=audit
SOURCE_MARKDOWN_MODE=audit
```

Dann wird die ausführliche Nachweisansicht mit Audit-Status,
Claim-Abdeckung und technischen Prüfinformationen eingeblendet.

## Konfiguration

```env
OPENWEBUI_AUTHZ_ENABLED=true
OPENWEBUI_AUTHZ_BASE_URL=http://connector-controller:8080
OPENWEBUI_AUTHZ_SHARED_SECRET=change-me-authz-secret
OPENWEBUI_AUTHZ_FAIL_CLOSED=true
```

`OPENWEBUI_AUTHZ_SHARED_SECRET` sollte denselben Wert wie
`AUTHZ_API_SHARED_SECRET` verwenden. Das Secret authentifiziert nur die
technische Komponente. Es ersetzt keine Nutzeridentität.

## Warum OpenWebUI keine Seafile-Tokens bekommt

OpenWebUI ist eine nutzernahe Oberfläche. Dort ausgeführte Tools/Pipes können
von Admins bearbeitet, exportiert oder in Logs sichtbar werden. Seafile-Admin-
und Sync-Tokens bleiben deshalb im Connector-Core. Die Pipe bekommt nur:

- Connector-Proxy-URL
- Connector-Proxy-Secret
- Nutzerkontext
- Dataset-/Chat-Kontext

Die personenbezogene Berechtigung wird zentral geprüft, bevor RAGFlow
abgefragt wird.
