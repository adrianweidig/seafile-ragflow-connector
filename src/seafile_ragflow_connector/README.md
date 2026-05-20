# Paketstruktur

Dieses Paket enthält den vollständigen Connector.

- `app/`: CLI, Runtime-Bootstrap, Logging und Prometheus-Metriken.
- `clients/`: HTTP-Clients für Seafile, RAGFlow und OpenWebUI.
- `config/`: Pydantic-Settings und Environment-Validierung.
- `dashboard/`: lesendes Admin-Dashboard, API-Endpunkte, Health und Audit-XLSX.
- `domain/`: reine Fachlogik für Dateiklassifikation, Namen und Templates.
- `jobs/`: persistente Job-Queue, Prioritäten, Worker und Redis-Signale.
- `openwebui/`: optionale Sync-Logik, Tool-/Pipe-Generatoren und Quellenmapping.
- `persistence/`: SQLAlchemy-Basis und Models.
- `sync/`: Discovery, Dataset-Provisioning, Upload, Delete, Parse und Repair.
- `utils/`: kleine Hilfsfunktionen für Hashing, Pfade, Retry und Redaction.

Die wichtigste Regel bleibt: Seafile ist die Quelle der Wahrheit. Änderungen in
RAGFlow oder OpenWebUI werden repariert oder synchronisiert, lösen aber keine
Schreibzugriffe nach Seafile aus.
