# OBS-Demoaufnahme für Seafile, RAGFlow und OpenWebUI

🌐 Sprachen: **Deutsch** | [English](en/demo-recording.md)

Dieses Runbook beschreibt die vorbereitete Demoaufnahme für den sichtbaren
Ablauf von Seafile über RAGFlow bis OpenWebUI. Der Standardmodus ist bewusst
nicht mutierend: Er erzeugt nur Demo-Datei, Ablaufplan und Summary. Der echte
Lauf gegen die Testumgebung startet erst mit `--execute`; die OBS-Aufnahme
startet erst zusätzlich mit `--record`.

## Zweck

Die Aufnahme soll zeigen:

- neue Seafile-Bibliothek anlegen und leer zeigen,
- dazugehöriges RAGFlow-Dataset sichtbar machen,
- RAGFlow-Chat und OpenWebUI-Pipe vor dem Datei-Upload erzeugen,
- erst danach die Demo-Datei in Seafile hochladen,
- Synchronisation, Parsing und mehrere Chunks in RAGFlow prüfen,
- in OpenWebUI die automatisch erzeugte Pipe verwenden,
- Antwort, Preview und Originaldokument gegeneinander nachvollziehen,
- OBS-Aufnahme kontrolliert starten und stoppen.

## OBS-Konfiguration

Die Automation liest nur Prozess-Environment und schreibt keine Secrets in den
Arbeitsbaum.

| Variable | Zweck |
| --- | --- |
| `OBS_WEBHOOK_STATUS_URL` | optionaler Status-Endpunkt |
| `OBS_WEBHOOK_START_URL` | Start der Aufnahme, für `--record` erforderlich |
| `OBS_WEBHOOK_STOP_URL` | Stopp der Aufnahme, für `--record` erforderlich |
| `OBS_WEBHOOK_MARKER_URL` | optionaler Marker-Endpunkt für wichtige Schritte |
| `OBS_WEBHOOK_SCENE_URL` | optionaler Szenenwechsel |
| `OBS_WEBHOOK_SCREENSHOT_URL` | reserviert für spätere Screenshot-Prüfung |
| `OBS_WEBHOOK_TOKEN` | optionales Webhook-Token, wird nicht ausgegeben |
| `OBS_WEBHOOK_TOKEN_HEADER` | optionaler Header, Default `Authorization` |
| `OBS_WEBHOOK_TOKEN_SCHEME` | optionales Schema, Default `Bearer` |
| `OBS_WEBHOOK_PAYLOAD_MODE` | `json` oder `none`, Default `json` |
| `OBS_SCENE_NAME` | optionale OBS-Szene für den Lauf |

Wenn der Webhook keine JSON-Payload akzeptiert, setze
`OBS_WEBHOOK_PAYLOAD_MODE=none`.

## Vorbereitung ohne Ausführung

Dieser Befehl ist für die aktuelle Fehlersituation gedacht. Er prüft keine
produktiven Dienste, startet keine Aufnahme und verändert Seafile, RAGFlow oder
OpenWebUI nicht:

```bash
uv run --extra dev python scripts/record_demo_workflow.py
```

Mit OBS-Konfigurationsprüfung:

```bash
uv run --extra dev python scripts/record_demo_workflow.py --check-obs
```

Die Ausgabe liegt unter:

```text
output/demo-recording/<demo-id>/
```

Darin stehen:

- `seafile-ragflow-openwebui-demo-<demo-id>.md`,
- `recording-summary.json`.

## Späterer echter Lauf

Erst ausführen, wenn die bekannten Laufzeitfehler behoben sind und die
Testumgebung bereit ist:

```bash
uv run --extra dev python scripts/record_demo_workflow.py --execute --record --headed
```

Wenn ein Playwright-Profil mit bestehenden Test-Logins verwendet werden soll:

```bash
uv run --extra dev python scripts/record_demo_workflow.py \
  --execute --record --headed \
  --profile-dir output/demo-recording/browser-profile
```

Der echte Lauf nutzt die lokale Connector-Konfiguration aus Environment oder
`stack.env`. Secrets werden nicht geloggt. Der Ablauf legt eine eindeutig
benannte Testbibliothek an:

```text
Demo RAGFlow OpenWebUI Bibliothek <demo-id>
```

Der technische RAGFlow-Dataset-Name bleibt connector-konform und wird aus
Seafile-Bibliotheksname und echter Repo-ID gebildet. Das Demo-Label in Summary
und Marker lautet:

```text
Demo Dataset Seafile Sync <demo-id>
```

## Reihenfolge

Das Skript erzwingt im Ausführungsmodus diese Reihenfolge:

1. OBS optional validieren und Aufnahme starten.
2. Seafile-Seite öffnen.
3. Testbibliothek erzeugen oder wiederverwenden.
4. Connector-Discovery ausführen.
5. RAGFlow-Dataset für die Bibliothek sicherstellen.
6. OpenWebUI-Sync für genau diese Bibliothek ausführen, damit RAGFlow-Chat und
   OpenWebUI-Pipe vor dem Upload entstehen.
7. Demo-Datei nach Seafile hochladen.
8. Connector-Sync für die Bibliothek ausführen.
9. RAGFlow-Parsing bis zum Timeout prüfen.
10. Retrieval gegen das Dataset prüfen.
11. OpenWebUI öffnen, damit Pipe, Antwort, Preview und Original manuell sichtbar
    nachvollzogen werden können.
12. OBS-Marker setzen und Aufnahme kontrolliert stoppen.

## Erfolgskriterien

Für den vollständigen Videolauf müssen sichtbar geprüft werden:

- Seafile-Bibliothek ist leer, bevor die Datei hochgeladen wird.
- RAGFlow-Dataset und Chat existieren vor dem Upload.
- Datei ist nach dem Upload in Seafile sichtbar.
- RAGFlow zeigt Datei, Sync-Status und Parsingstatus.
- Mehrere Chunks sind sichtbar; mindestens ein Chunk enthält den Demo-Marker.
- OpenWebUI zeigt die automatisch erzeugte Pipe.
- Die Frage aus `recording-summary.json` wird gestellt und beantwortet.
- Preview und Originaldokument enthalten denselben Demo-Marker und passende
  Abschnittsüberschriften.

## Abbruchverhalten

Wenn nach Aufnahmestart ein Fehler auftritt, versucht das Skript im
`finally`-Block den OBS-Stopp-Endpunkt aufzurufen. Fehler werden knapp
gemeldet; Token-Werte und Runtime-Secrets werden nicht ausgegeben.
