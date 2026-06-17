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
