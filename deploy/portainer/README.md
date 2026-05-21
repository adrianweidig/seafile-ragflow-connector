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

1. Connector-Image unter `Images` importieren oder sicherstellen, dass der
   Docker-Host es pullen kann.
2. Falls kein Internetzugriff besteht, auch `postgres:16` und `redis:7` als
   Images importieren.
3. Neuen Stack erstellen.
4. Inhalt von `docker-compose.yml` einfügen oder dieses Repo als Git-Stack
   verwenden.
5. Inhalt von `../../connector.env.example` in Portainer unter `Environment
   variables` importieren.
6. Alle `change-me` Werte und die Base-URLs ersetzen.
   Wenn interne Zertifikate genutzt werden, die CA-PEM-Datei in ein
   Host-Verzeichnis legen, `CONNECTOR_CERTS_HOST_DIR` auf dieses Verzeichnis
   und `CONNECTOR_CA_BUNDLE=/certs/<datei>.pem` setzen.
7. `CONNECTOR_IMAGE`, `POSTGRES_IMAGE` und `REDIS_IMAGE` an die in Portainer
   sichtbaren Image-Tags anpassen. Wenn lokale Images genutzt werden sollen,
   kann `*_IMAGE_PULL_POLICY=never` gesetzt werden.
8. Stack deployen und Logs von Controller, Worker und Reconciler prüfen.

Wichtig: Seafile ist die Quelle der Wahrheit. Der Connector kann Zielartefakte
in RAGFlow und OpenWebUI löschen oder neu erzeugen, wenn Seafile-Libraries oder
Dateien verschwinden beziehungsweise Zielartefakte extern gelöscht wurden.
Seafile selbst wird durch diesen Stack nicht geändert.
