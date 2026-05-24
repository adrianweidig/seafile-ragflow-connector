# FAQ

## Ersetzt der Connector Seafile oder RAGFlow?

Nein. Seafile, RAGFlow und optional OpenWebUI bleiben externe Systeme. Der
Connector verwaltet Sync-State, Jobs, Uploads, Deletes, Reparaturen,
Dashboard-Status und optionale OpenWebUI-Artefakte.

## Was ist die Quelle der Wahrheit?

Seafile ist die Quelle der Wahrheit. Wenn Zielartefakte in RAGFlow oder
OpenWebUI fehlen oder driften, werden sie aus Seafile und dem lokalen
Connector-State repariert. Seafile wird nicht verändert, nur weil Zielsysteme
abweichen.

## Wofür wird `connector_template` genutzt?

Das RAGFlow-Dataset `connector_template` wird nur beim Erzeugen neuer
Library-Datasets genutzt. Danach bleiben die live gesetzten Einstellungen des
Ziel-Datasets maßgeblich.

## Muss OpenWebUI aktiviert werden?

Nein. OpenWebUI ist optional und standardmäßig deaktiviert. Erst mit
`OPENWEBUI_INTEGRATION_ENABLED=true` und einem passenden `OPENWEBUI_SYNC_MODE`
werden OpenWebUI-Clients, Jobs, Tools oder Pipes genutzt.

## Warum gibt es PostgreSQL und Redis?

PostgreSQL speichert den dauerhaften Connector-State. Redis übernimmt Queueing,
Retries und Backpressure für Worker-Prozesse.

## Ist das Dashboard geschützt?

Das Dashboard ist bewusst lesend und erzwingt keine eigene Authentifizierung.
Der Zugriff muss über Netzwerkexposition, Reverse Proxy oder Portbindung
gesteuert werden. Wer das Dashboard nicht erreichbar machen will, aktiviert es
nicht oder veröffentlicht den Port nicht.

## Darf `*_VERIFY_SSL=false` produktiv genutzt werden?

Nein. Diese Werte sind nur für Diagnose und Entwicklung gedacht. Für produktive
Umgebungen sollten Root-/Intermediate-CAs als PEM-Bundle eingebunden werden.

## Wie prüfe ich das Projekt lokal?

Der Standardcheck ohne Docker-Nebenwirkungen ist:

```bash
python scripts/verify.py --skip-compose
```

Wenn Docker Compose lokal sicher verfügbar ist:

```bash
python scripts/verify.py --with-compose
```
