# Manueller Seafile-RAGFlow-OpenWebUI-Prüfablauf

🌐 Sprachen: **Deutsch** | [English](en/manual-workflow-verification.md)

Dieses Runbook beschreibt einen reproduzierbaren Testablauf vom Upload einer
Datei in Seafile bis zur Abfrage über eine OpenWebUI-Pipe. Es ist für lokale
oder dedizierte Testumgebungen gedacht. Produktive Bibliotheken, produktive
RAGFlow-Datasets und produktive OpenWebUI-Funktionen werden dafür nicht
verwendet.

## Automatisierter Vorlauf

Vor einer manuellen Prüfung muss der lokale Integrationstest grün sein:

```bash
uv run pytest tests/integration/test_manual_workflow.py
```

Der Test nutzt SQLite und Fake-Clients. Er prüft, dass eine eindeutige
Seafile-Testbibliothek mit Datei erkannt wird, daraus ein RAGFlow-Dataset und
Dokument entstehen, die RAGFlow-Chat-Bindung erzeugt wird und OpenWebUI Tool
und Pipe die Dataset-ID, Chat-ID und Connector-Proxy-Konfiguration bekommen.
Zusätzlich wird ein nicht erreichbares OpenWebUI als sichtbarer Fehler im
Connector-State gespeichert.

## Voraussetzungen

- Der Connector ist aus diesem Repository installiert oder als Compose-/Portainer-
  Stack gestartet.
- Seafile läuft in einer Testumgebung und ist aus dem Connector-Container oder
  lokalen Connector-Prozess erreichbar.
- RAGFlow läuft in derselben Testumgebung und ist aus dem Connector erreichbar.
- OpenWebUI läuft nur dann, wenn die Pipe-Strecke geprüft werden soll.
- Die benötigten Tokens und API-Keys liegen ausschließlich in der lokalen
  Runtime-Konfiguration, nicht im Git-Arbeitsbaum.
- Für TLS mit interner CA sind die CA-Bundles aus Sicht des jeweiligen
  Containers gemountet und in der Konfiguration gesetzt.

## Benötigte Konfiguration

Für Seafile zu RAGFlow sind mindestens diese Werte gesetzt:

| Variable | Zweck |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile-URL aus Sicht des Connectors |
| `SEAFILE_ADMIN_TOKEN` | Seafile Admin-API-Token für Library-Discovery |
| `SEAFILE_SYNC_USER_TOKEN` | Seafile API-Token für Datei-Downloads |
| `RAGFLOW_BASE_URL` | RAGFlow-API-URL aus Sicht des Connectors |
| `RAGFLOW_API_KEY` | RAGFlow API-Key des Zielusers |
| `POSTGRES_PASSWORD` oder `DATABASE_URL` | Connector-State-Datenbank |

Für OpenWebUI zusätzlich:

| Variable | Zweck |
| --- | --- |
| `OPENWEBUI_INTEGRATION_ENABLED=true` | aktiviert die OpenWebUI-Strecke |
| `OPENWEBUI_SYNC_MODE=sync` | schreibt eigene Tool-/Pipe-Artefakte |
| `OPENWEBUI_BASE_URL` | OpenWebUI-API-URL aus Sicht des Connectors |
| `OPENWEBUI_ADMIN_API_KEY` | Admin-Key für Tool-/Function-Sync |
| `OPENWEBUI_PROXY_INTERNAL_BASE_URL` | Connector-Proxy-URL aus Sicht von OpenWebUI |
| `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | Browser-URL für Connector-Preview-Links |
| `OPENWEBUI_PROXY_SHARED_SECRET` | gemeinsames Proxy-Secret, nur in der Runtime |

Bei direktem Compose-Start wird die ungetrackte Datei `connector.env` genutzt:

```bash
cp connector.env.example connector.env
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml config --quiet
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml up -d
```

Bei lokaler CLI-Ausführung ohne Compose müssen dieselben Variablen im Prozess
gesetzt sein. Alternativ kann eine ungetrackte `stack.env` verwendet werden,
weil `Settings` diese Datei lokal einliest.

## Testartefakte

Verwende diese Namen, damit Logs, Dashboard, RAGFlow und OpenWebUI eindeutig
korrelierbar sind:

| Artefakt | Name |
| --- | --- |
| Seafile-Bibliothek | `Codex Workflow Check` |
| Seafile-Ordner | `/manual-workflow-check` |
| Seafile-Datei | `seafile-ragflow-openwebui-check.md` |
| Erwartetes Dataset-Muster | `RAG_codex_workflow_check_...` |
| Erwartetes OpenWebUI-Modell | `Seafile · RAG_codex_workflow_check_...` |
| Erwartete Tool-ID | `ragflow_tool_rag_codex_workflow_check_...` |
| Erwartete Pipe-ID | `ragflow_pipe_rag_codex_workflow_check_...` |

Der Dataset-Suffix wird aus der echten Seafile-Repo-ID abgeleitet und ist daher
umgebungsspezifisch.

## Schritt 1: Datei in Seafile hochladen

1. In Seafile eine Testbibliothek `Codex Workflow Check` anlegen oder eine klar
   isolierte bestehende Testbibliothek mit diesem Namen verwenden.
2. Den Ordner `/manual-workflow-check` anlegen.
3. Die Datei `seafile-ragflow-openwebui-check.md` hochladen.
4. Diesen Inhalt verwenden:

   ```markdown
   # Codex Workflow Check

   Testfrage: Welches System bleibt die Quelle der Wahrheit?
   Antwortanker: Seafile bleibt die Quelle der Wahrheit.
   ```

5. In Seafile prüfen, dass die Datei sichtbar ist und die Bibliothek nicht
   verschlüsselt oder virtuell ist, falls die Default-Skip-Regeln aktiv sind.

## Schritt 2: Live-Abhängigkeiten prüfen

Im Compose-Stack:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml \
  exec -T connector-controller connector check-live --json
```

Direkt lokal, wenn die Variablen im Prozess gesetzt sind:

```bash
uv run connector check-live --json
```

Erwartet wird `database=ok`, `redis=ok` und mindestens eine sichtbare
Seafile-Library. Wenn `ragflow_template_found=false` vor dem ersten Sync
erscheint, ist das bei aktivem `RAGFLOW_TEMPLATE_AUTO_CREATE=true` noch kein
Fehler; nach dem Sync sollte das Template sichtbar sein.

## Dashboard-Variante

Wenn der Stack über `connector-controller` mit `CONNECTOR_DASHBOARD_ENABLED=true`
läuft, kann der Prüfablauf vollständig im Dashboard gestartet werden:

1. Dashboard öffnen, zum Tab **Prüfablauf** wechseln und
   **Bibliotheken prüfen** ausführen.
2. Die Tabelle zeigt nur Bibliotheken, die der aktuelle Seafile-Admin-API-Key
   sehen kann. Verschlüsselte oder virtuelle Bibliotheken sind abhängig von den
   Skip-Regeln sichtbar, aber nicht auswählbar.
3. Die Testbibliothek auswählen.
4. **RAGFlow-Dataset und Dokumente synchronisieren** aktiv lassen, wenn Dataset
   und Dokumente erzeugt oder aktualisiert werden sollen.
5. **RAGFlow-Chat und OpenWebUI-Tool/Pipe erzeugen** aktiv lassen, wenn die
   OpenWebUI-Strecke für die ausgewählten Bibliotheken erzeugt werden soll.
6. Optional den Seafile-Pfad auf `/manual-workflow-check` begrenzen.
7. **Auswahl starten** ausführen und danach die Tabs **Sync-Läufe**,
   **Systeme** und **OpenWebUI** prüfen.

Der reine Befehl `connector dashboard` startet weiterhin nur ein
Status-Dashboard ohne Runtime-Controller. Die Steuerung ist dort sichtbar als
nicht verfügbar.

## Schritt 3: Synchronisierung nach RAGFlow auslösen

Im Compose-Stack:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml \
  exec -T connector-controller connector sync-once --json
```

Direkt lokal:

```bash
uv run connector sync-once --json
```

Erwartet:

- `libraries_seen` ist mindestens `1`.
- `files_seen` ist mindestens `1`.
- Beim ersten Lauf ist `files_uploaded` mindestens `1`.
- Wenn OpenWebUI aktiviert ist, enthält die Ausgabe zusätzlich den Block
  `openwebui` mit `datasets_seen`, `tools_created` oder `tools_reused` und
  `pipes_created` oder `pipes_reused`.

Im Connector-Log müssen Einträge mit `library.sync_started`,
`file.uploaded`, `dataset_id`, `repo_id` und `sync_id` sichtbar sein.

## Schritt 4: RAGFlow-Dataset und Dokument prüfen

In RAGFlow prüfen:

1. Ein Dataset mit dem Muster `RAG_codex_workflow_check_...` existiert.
2. Das Dataset enthält ein Dokument für die hochgeladene Markdown-Datei. Bei
   Text-Projektion endet der Dokumentname auf `.md.txt`.
3. Die Dokument-Metadaten enthalten `repo_id`, `source_path`,
   `source_sha256`, `document_name` und `file_type`.
4. Der Parse-/Indexierungsstatus ist abgeschlossen oder sichtbar in Arbeit.

Falls das Dokument fehlt, zuerst Connector-Logs für `file.skipped`,
`file.uploaded` und `library.sync_failed` prüfen. Häufige Ursachen sind
Dateigrößenlimit, Deny-Extension, falscher Seafile-Download-Token oder eine
nicht erreichbare RAGFlow-API.

## Schritt 5: OpenWebUI Pipe prüfen

Wenn OpenWebUI aktiviert ist, kann der Sync separat erneut gestartet werden:

```bash
uv run connector openwebui-sync-once --json
```

In OpenWebUI prüfen:

1. Es gibt ein Tool mit dem Präfix
   `ragflow_tool_rag_codex_workflow_check_`.
2. Es gibt eine Pipe beziehungsweise Function mit dem Präfix
   `ragflow_pipe_rag_codex_workflow_check_`.
3. Die Pipe ist aktiv.
4. Die Pipe-Valves enthalten die richtige `DATASET_ID`, eine `RAGFLOW_CHAT_ID`,
   `CONNECTOR_PROXY_BASE_URL` und das Runtime-Proxy-Secret. Secret-Werte nicht
   in Tickets, Logs oder Dokumentation kopieren.
5. Im Modellpicker erscheint ein Modell nach dem Muster
   `Seafile · RAG_codex_workflow_check_...`.

Der Connector-State ist zusätzlich im Dashboard unter Systeme/OpenWebUI
prüfbar. Erwartet ist eine Mapping-Zeile mit `sync_status=synced` oder bei
Dry-Run `planned`.

## Schritt 6: Testabfrage ausführen

In OpenWebUI das erzeugte Modell auswählen und fragen:

```text
Welches System bleibt laut Testdatei die Quelle der Wahrheit?
```

Erwartet wird eine Antwort mit Bezug auf Seafile als Quelle der Wahrheit sowie
mindestens eine Quelle im deutschen Abschnitt `Nachweise` zur Datei
`seafile-ragflow-openwebui-check.md`. Wenn die Antwort keine Quelle zeigt,
prüfen, ob die Pipe-Valves `SOURCE_DISPLAY_MODE=audit`,
`SOURCE_MARKDOWN_MODE=audit`, `APPEND_SOURCE_OVERVIEW=true` und die
Connector-Proxy-URL korrekt gesetzt sind.

## Typische Fehlerbilder

| Fehlerbild | Prüfpunkte |
| --- | --- |
| `check-live` sieht keine Libraries | `SEAFILE_BASE_URL`, Admin-Token, Netzwerkpfad aus Connector-Sicht |
| Datei wird übersprungen | Deny-/Allow-Extensions, Dateigröße, `ALLOW_UNKNOWN_TEXT_FILES`, Logs `file.skipped` |
| Dataset fehlt | RAGFlow API-Key, Template-Dataset, `library.sync_failed`, RAGFlow-Rechte |
| Dokument bleibt ungeparst | RAGFlow-Parser-Worker, Dokumentstatus, RAGFlow-Logs |
| OpenWebUI-Sync ist `failed` | Admin-Key, Tool-/Function-API-Rechte, `OPENWEBUI_BASE_URL` |
| Pipe antwortet nicht | `OPENWEBUI_PROXY_INTERNAL_BASE_URL`, Proxy-Secret, CA-Bundle im OpenWebUI-Container |
| Quellenlinks fehlen | `OPENWEBUI_PROXY_PUBLIC_BASE_URL`, Preview-Modus, Seafile-Datei-URL-Template |

## Aufräumen

1. Die Seafile-Testbibliothek `Codex Workflow Check` löschen.
2. Danach den Connector-Sync erneut ausführen:

   ```bash
   uv run connector sync-once --json
   ```

3. Wenn OpenWebUI aktiviert ist, anschließend:

   ```bash
   uv run connector openwebui-sync-once --json
   ```

4. In RAGFlow prüfen, dass das connector-eigene Dataset entfernt wurde, sofern
   `DELETE_DATASET_WHEN_LIBRARY_DELETED=true` aktiv ist.
5. In OpenWebUI prüfen, dass die connector-eigenen Tool-/Pipe-Artefakte entfernt
   oder als gelöscht markiert sind.
6. Falls Artefakte durch einen abgebrochenen Test übrig bleiben, erst
   `connector cleanup-orphans --json` prüfen und nur bei eindeutigem Plan mit
   `--execute` ausführen.

Produktive Daten werden dabei nicht benötigt. Wenn ein Schritt produktive
Dienste betreffen würde, den Lauf abbrechen und eine isolierte Testumgebung
verwenden.
