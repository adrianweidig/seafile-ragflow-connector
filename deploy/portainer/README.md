# Portainer Stack

Dieser Ordner ist der Einstiegspunkt für Betreiber.

- `docker-compose.yml` definiert Controller, Worker, Reconciler, PostgreSQL,
  Redis, Volumes, Healthchecks und das optionale Dashboard-Portmapping.
- `stack.env.example` ist die Vorlage für Portainer-Environment-Variablen.
- `stack.env` ist eine lokale, nicht zu commitende Arbeitskopie für Tests.

Der Standardwert für `CONNECTOR_IMAGE` ist
`ghcr.io/adrianweidig/seafile-ragflow-connector:latest`. Für Offline-Betrieb
kann dort ein lokal geladenes Image oder eine interne Registry eingetragen
werden.

Wichtig: Seafile ist die Quelle der Wahrheit. Der Connector kann Zielartefakte
in RAGFlow und OpenWebUI löschen oder neu erzeugen, wenn Seafile-Libraries oder
Dateien verschwinden beziehungsweise Zielartefakte extern gelöscht wurden.
Seafile selbst wird durch diesen Stack nicht geändert.
