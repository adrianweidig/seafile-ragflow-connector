# Architektur

Der Connector ist eine Sync-Control-Plane. Er patcht RAGFlow nicht und nutzt
WebDAV nicht als Kernmechanismus.
Seafile ist die einzige Quelle der Wahrheit: Zielsystem-Löschungen in RAGFlow
oder OpenWebUI lösen niemals Änderungen in Seafile aus, sondern werden durch
den nächsten Sync aus Seafile repariert.

```text
Seafile API -> controller -> PostgreSQL state -> Redis jobs -> workers -> RAGFlow API
                         \-> reconciler ------------------------/
                         \-> OpenWebUI sync -> OpenWebUI API
                         \-> HTTP proxy ----> RAGFlow API
```

## Komponenten

| Komponente | Verantwortung |
| --- | --- |
| controller | Discovery-Loop, Dataset-Provisioning, Delta-Scheduling |
| worker | Download, Klassifikation, Artefakt-Erzeugung, Upload, Delete, Parse |
| reconciler | Reparatur abweichender Zustände zwischen Seafile, DB und RAGFlow |
| PostgreSQL | dauerhafter Sync-Zustand und Job-Historie |
| Redis | Queue, Retry-Verzögerung, Worker-Fan-out |
| OpenWebUI sync | optionale idempotente Erzeugung von RAGFlow-Chats, OpenWebUI-Tools und Pipes |
| HTTP proxy | geschützte OpenWebUI-Function-Aufrufe ohne RAGFlow-Secrets im Function-Code |

## Delete- und Repair-Fluss

Wenn eine Library in Seafile verschwindet, markiert der Connector die Library
lokal als `deleted`, entfernt das zugehörige RAGFlow-Dataset und lässt den
OpenWebUI-Sync die dazugehörigen RAGFlow-Chats, Tools und Pipes löschen. Wenn
ein Dataset oder Dokument in RAGFlow ohne Seafile-Löschung verschwindet, erzeugt
der Connector Dataset und Dokumente beim nächsten Sync aus Seafile neu. Wenn
OpenWebUI-Tools oder -Pipes fehlen, werden eigene Artefakte idempotent erneut
angelegt.

## Dataset-Einstellungen

`connector_template` wird nur beim Erzeugen eines RAGFlow-Datasets verwendet.
Danach sind die aktuellen RAGFlow-Einstellungen des Ziel-Datasets maßgeblich.
Dadurch kann ein Admin Chunking, Parser-Einstellungen oder Ingestion Pipeline
direkt in RAGFlow ändern, ohne den Connector neu zu konfigurieren.

## OpenWebUI

Die OpenWebUI-Integration ist additiv. Für jede aktive Library mit
RAGFlow-Dataset speichert der Connector ein Mapping aus Dataset, RAGFlow-Chat,
OpenWebUI-Tool, OpenWebUI-Pipe und sichtbarem Modellnamen. Die Pipe erscheint in
OpenWebUI als eigenes Custom-Model. Tool und Pipe sind deterministisch benannt,
enthalten keine Admin-Secrets und nutzen ausschließlich den Connector-Proxy.

Quellen werden aus RAGFlow-Referenzen normalisiert und als OpenWebUI-Source- bzw.
Citation-Metadaten zurückgegeben. Wenn kein stabiler RAGFlow-Deep-Link
konfiguriert ist, kann der Connector signierte Kurzzeit-Preview-Links erzeugen,
die nur Metadaten und Auszüge anzeigen.

## Datei-Ingestion

Der Connector behandelt Dateiendungen als Hinweise, nicht als vollständige
Policy. Unbekannte Dateien können akzeptiert werden, wenn sie als Text erkannt
werden. Code und textbasierte Spezialformate wie Ada-Dateien werden bei Bedarf
vor dem Upload in stabile Text-Artefakte überführt.
