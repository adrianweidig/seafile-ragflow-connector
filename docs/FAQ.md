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
Ziel-Datasets maßgeblich. Fehlt es, legt der Connector es mit
`RAGFLOW_TEMPLATE_AUTO_CREATE=true` automatisch mit DeepDOC-, Seiten- und
Metadaten-Defaults an.

## Muss OpenWebUI aktiviert werden?

Nein. OpenWebUI ist optional und standardmäßig deaktiviert. Erst mit
`OPENWEBUI_INTEGRATION_ENABLED=true` und einem passenden `OPENWEBUI_SYNC_MODE`
werden OpenWebUI-Clients, Jobs, Tools oder Pipes genutzt.

## Warum gibt es PostgreSQL und Redis?

PostgreSQL speichert den dauerhaften Connector-State. Redis übernimmt Queueing,
Retries und Backpressure für Worker-Prozesse.

## Ist das Dashboard geschützt?

Ja, wenn `CONNECTOR_DASHBOARD_AUTH_USERNAME` und
`CONNECTOR_DASHBOARD_AUTH_PASSWORD` gesetzt sind. Dann schützt HTTP Basic Auth
die Weboberfläche, die Status-API und die Dashboard-Workflow-Steuerung. Die
OpenWebUI-Proxy-Endpunkte nutzen weiterhin ihr separates
`OPENWEBUI_PROXY_SHARED_SECRET`.

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
