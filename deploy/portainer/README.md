# Portainer Stack

Dieser Ordner ist der Einstiegspunkt für Betreiber.

- `docker-compose.yml` definiert Controller, Worker, Reconciler, PostgreSQL,
  Redis, Volumes, Healthchecks und das optionale Dashboard-Portmapping.
- `../../connector.env.example` ist die empfohlene einheitliche Vorlage für
  Portainer-Environment-Variablen.
- `stack.env.example` bleibt als Portainer-spezifische Referenz erhalten.
- `stack.env` ist eine lokale, nicht zu commitende Arbeitskopie für Tests.

Der Standardwert für `CONNECTOR_IMAGE` ist
`ghcr.io/adrianweidig/seafile-ragflow-connector:latest`. Für Offline-Betrieb
kann dort ein lokal geladenes Image oder eine interne Registry eingetragen
werden.

Portainer-Start:

1. Neuen Stack erstellen.
2. Inhalt von `docker-compose.yml` einfügen oder dieses Repo als Git-Stack
   verwenden.
3. Inhalt von `../../connector.env.example` in Portainer unter `Environment
   variables` importieren.
4. Alle `change-me` Werte und die Base-URLs ersetzen.
5. Stack deployen und Logs von Controller, Worker und Reconciler prüfen.

Wichtig: Seafile ist die Quelle der Wahrheit. Der Connector kann Zielartefakte
in RAGFlow und OpenWebUI löschen oder neu erzeugen, wenn Seafile-Libraries oder
Dateien verschwinden beziehungsweise Zielartefakte extern gelöscht wurden.
Seafile selbst wird durch diesen Stack nicht geändert.
