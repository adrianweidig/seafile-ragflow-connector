# Zielzustand: Seafile-RAGFlow-Connector Test-/WSL-Docker-Stack

Diese Datei beschreibt den wiederverwendbaren Betriebszustand für die lokale
WSL-Docker-Umgebung. Sie ist kein Secret-Store. Tokens, Passwörter und API-Keys
stehen ausschließlich in der jeweiligen Runtime-Umgebung oder in lokalen
Betreiberdateien.

## Grundsatz

- Seafile ist die Quelle der Wahrheit.
- RAGFlow und OpenWebUI werden aus Seafile und dem Connector-Zustand aufgebaut.
- Entfernte Seafile-Libraries müssen in RAGFlow und OpenWebUI nachvollzogen
  werden.
- Extern gelöschte Zielartefakte werden bei Bedarf wieder aus Seafile aufgebaut.
- Docker-Volumes für Postgres, Redis, Seafile, RAGFlow und OpenWebUI werden bei
  Cleanup-Arbeiten nicht gelöscht.

## Laufende Kerncontainer

Der lokale Teststack läuft in WSL Docker im Netzwerk `ki_infra_seu_test`.

Pflichtdienste:

- `ki-test-seafile`
- `ki-test-ragflow`
- `ki-test-openwebui`
- `ki-test-https-edge`
- `seafile-ragflow-connector-demo-connector-postgres-1`
- `seafile-ragflow-connector-demo-connector-redis-1`
- `seafile-ragflow-connector-demo-connector-controller-1`
- `seafile-ragflow-connector-demo-connector-worker-1`
- `seafile-ragflow-connector-demo-connector-reconciler-1`

Lokale Zugriffspunkte:

- Seafile: `http://localhost:18081`
- RAGFlow UI: `http://localhost:19500`
- RAGFlow API: `http://localhost:19380`
- OpenWebUI: `http://localhost:13080`
- Connector-Dashboard: `http://localhost:18080`

Interne Connector-Ziele:

- `SEAFILE_BASE_URL=http://seafile`
- `RAGFLOW_BASE_URL=http://ragflow:9380`
- `OPENWEBUI_BASE_URL=http://openwebui:8080`
- `OPENWEBUI_PROXY_INTERNAL_BASE_URL=http://connector-controller:8080`
- `OPENWEBUI_PROXY_PUBLIC_BASE_URL=http://localhost:18080`
- `SEAFILE_DOWNLOAD_REWRITE_FROM=https://seafile.top.secret/seafhttp`
- `SEAFILE_DOWNLOAD_REWRITE_TO=http://seafile/seafhttp`

Für echte Sync-Tests darf `ALLOW_EXTENSIONS` nicht auf einen Smoke-Test-Wert wie
`.portainer-smoke-none` eingeschränkt sein. Leer bedeutet: keine zusätzliche
Allowlist, die Denylist bleibt aktiv.

## Erwarteter sauberer Artefaktzustand

Seafile:

- Nur bewusst aktive Libraries sind vorhanden.
- Neue Libraries werden vom Connector erkannt.

RAGFlow:

- `connector_template` bleibt als Template-Dataset erhalten.
- Pro aktiver Seafile-Library existiert genau ein Dataset mit Namen nach dem
  Muster `seafile__<library>__<repo-prefix>`.
- Legacy-Datasets ohne Bezug zu einer aktuellen Seafile-Library, etwa alte
  Sammeldatasets, sind keine Sollartefakte.

OpenWebUI:

- Pro synchronisiertem und geparstem RAGFlow-Dataset existiert ein Tool mit
  `ragflow_tool_...`.
- Pro synchronisiertem und geparstem RAGFlow-Dataset existiert eine Function
  beziehungsweise Pipe mit `ragflow_pipe_...`.
- Demo- oder Alt-Artefakte ohne aktuelle Seafile-Library sind keine
  Sollartefakte.

## Build und Update

Lokales Connector-Image bauen:

```bash
wsl docker build \
  -t seafile-ragflow-connector:tls-local \
  -f deploy/docker/Dockerfile .
```

Wenn der Compose-Stack wegen leerer Pflichtvariablen nicht sauber gerendert
werden kann, die drei Connector-Prozesscontainer mit gleicher Umgebung neu
starten und nur die korrigierten Runtime-Variablen überschreiben. Datenbank,
Redis und Volumes bleiben dabei erhalten.

## Betriebschecks

Laufende Container prüfen:

```bash
wsl docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
```

Connector-Livecheck:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector check-live
```

Einmaligen Sync inklusive OpenWebUI-Sync ausführen:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector sync-once --wait-parse-seconds 240
```

Erwartung:

- `libraries_seen` entspricht der Anzahl aktiver Seafile-Libraries.
- `files_skipped` ist für unterstützte Testdateien `0`.
- OpenWebUI meldet keine `failed`-Einträge.

## Altlasten bereinigen

Connector-eigene Orphans zuerst trocken prüfen:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector cleanup-orphans
```

Wenn die geplanten Deletes plausibel sind:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector cleanup-orphans --execute --run-sync --wait-parse-seconds 240
```

Demo-Artefakte zuerst trocken prüfen:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector demo-cleanup
```

Wenn ausschließlich Demo-Libraries und Demo-Zielartefakte betroffen sind:

```bash
wsl docker exec \
  seafile-ragflow-connector-demo-connector-controller-1 \
  connector demo-cleanup --execute
```

Docker-Hygiene ohne Volumes:

```bash
wsl docker container prune -f
wsl docker image prune -f
```

Nicht ausführen, solange Daten erhalten bleiben sollen:

```bash
wsl docker volume prune
```

## Abschlusskriterium

Die Umgebung gilt als arbeitsfähig, wenn:

- die Pflichtcontainer laufen,
- `connector check-live` Datenbank, Redis, Seafile und RAGFlow erreicht,
- ein `sync-once` Dateien aus Seafile ohne Policy-Skip verarbeitet,
- RAGFlow nur Template plus aktuelle Library-Datasets enthält,
- OpenWebUI nur passende `ragflow_tool_...`- und `ragflow_pipe_...`-Artefakte
  für aktuelle Datasets enthält,
- `connector cleanup-orphans` keine geplanten Deletes mehr ausgibt,
- gestoppte Container und dangling Images bereinigt sind,
- keine Volumes gelöscht wurden.
