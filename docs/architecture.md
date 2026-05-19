# Architektur

Der Connector ist eine Sync-Control-Plane. Er patcht RAGFlow nicht und nutzt
WebDAV nicht als Kernmechanismus.

```text
Seafile API -> controller -> PostgreSQL state -> Redis jobs -> workers -> RAGFlow API
                         \-> reconciler ------------------------/
```

## Komponenten

| Komponente | Verantwortung |
| --- | --- |
| controller | Discovery-Loop, Dataset-Provisioning, Delta-Scheduling |
| worker | Download, Klassifikation, Artefakt-Erzeugung, Upload, Delete, Parse |
| reconciler | Reparatur abweichender Zustände zwischen Seafile, DB und RAGFlow |
| PostgreSQL | dauerhafter Sync-Zustand und Job-Historie |
| Redis | Queue, Retry-Verzögerung, Worker-Fan-out |

## Dataset-Einstellungen

`connector_template` wird nur beim Erzeugen eines RAGFlow-Datasets verwendet.
Danach sind die aktuellen RAGFlow-Einstellungen des Ziel-Datasets maßgeblich.
Dadurch kann ein Admin Chunking, Parser-Einstellungen oder Ingestion Pipeline
direkt in RAGFlow ändern, ohne den Connector neu zu konfigurieren.

## Datei-Ingestion

Der Connector behandelt Dateiendungen als Hinweise, nicht als vollständige
Policy. Unbekannte Dateien können akzeptiert werden, wenn sie als Text erkannt
werden. Code und textbasierte Spezialformate wie Ada-Dateien werden bei Bedarf
vor dem Upload in stabile Text-Artefakte überführt.
