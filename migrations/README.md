# Datenbankmigrationen

Dieser Ordner enthält Alembic-Migrationen für den dauerhaften Connector-State.

- `0001_initial_state.py` legt Libraries, Dateien, Jobs, Template-State und
  Dataset-Settings-Snapshots an.
- `0002_dashboard_state.py` ergänzt persistente Dashboard-Logs, Sync-Läufe und
  Änderungsereignisse.
- `0003_openwebui_integration_state.py` ergänzt OpenWebUI-Mappings und globalen
  OpenWebUI-Sync-State.

Migrationen sind additiv zu behandeln. Bestehende Sync-Daten dürfen nicht
verworfen werden, weil PostgreSQL die Quelle für Idempotenz, Reparatur und
Audit-Historie ist.
