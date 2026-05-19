# Configuration

Configuration is provided through environment variables. Secrets must be supplied
through Portainer environment management or Docker secrets and must not be committed.

## File Policy

- `ALLOW_EXTENSIONS`: optional allow-list. Empty means extension is not a hard allow gate.
- `DENY_EXTENSIONS`: extensions that are always skipped.
- `TEXT_EXTENSIONS`: extensions treated as text/code hints.
- `ALLOW_UNKNOWN_TEXT_FILES`: accept unknown extensions when content is text.
- `DEFAULT_TEXT_INGESTION_STRATEGY`: default `text_projection`.

## Dataset Settings

- `DATASET_SETTINGS_SOURCE=ragflow_current`: use current target dataset settings.
- `RAGFLOW_REFRESH_DATASET_SETTINGS=true`: refresh before upload/parse batches.
- `REPARSE_ON_DATASET_SETTINGS_CHANGE=false`: do not silently reprocess all existing
  documents after an admin changes dataset settings.

