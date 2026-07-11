# Datenbankmigrationen

Dieser Ordner enthält Alembic-Migrationen für den dauerhaften Connector-State.

- `0001_initial_state.py` legt Libraries, Dateien, Jobs, Template-State und
  Dataset-Settings-Snapshots an.
- `0002_dashboard_state.py` ergänzt persistente Dashboard-Logs, Sync-Läufe und
  Änderungsereignisse.
- `0003_openwebui_integration_state.py` ergänzt OpenWebUI-Mappings und globalen
  OpenWebUI-Sync-State.
- `0004_acl_search_profiles.py` ergänzt ACL-Snapshots und Search-Profile.
- `0005_sync_job_deduplication.py` ergänzt atomische Deduplizierung aktiver Jobs.

Migrationen sind additiv zu behandeln. Bestehende Sync-Daten dürfen nicht
verworfen werden, weil PostgreSQL die Quelle für Idempotenz, Reparatur und
Audit-Historie ist.

`connector init-db` führt `alembic upgrade head` unter dem PostgreSQL-
Advisory-Lock aus. Vor produktiven Upgrades ist ein Datenbank-Backup zu
erstellen. Ein Rollback erfolgt bevorzugt durch Wiederherstellung dieses
Backups; Alembic-Downgrades sind nur nach Prüfung der jeweiligen Migration
einzusetzen, da spätere Revisionen bereits produktive Daten verwenden können.
