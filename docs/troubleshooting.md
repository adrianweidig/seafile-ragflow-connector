# Troubleshooting

## Connector findet keine Libraries

Prüfen:

- `SEAFILE_BASE_URL`
- `SEAFILE_ADMIN_TOKEN`
- Admin-Berechtigungen für `/api/v2.1/admin/libraries/`

## RAGFlow-Template nicht gefunden

Prüfen:

- `RAGFLOW_API_KEY`
- `RAGFLOW_TEMPLATE_DATASET_NAME`
- ob der API-Key zum erwarteten RAGFlow-User gehört

## Spezielle Dateiendungen werden übersprungen

Prüfen:

- `DENY_EXTENSIONS`
- `ALLOW_UNKNOWN_TEXT_FILES`
- `TEXT_EXTENSIONS`
- Klassifikationslogs für `detected_encoding` und `is_text`

## Dataset-Einstellungen geändert

Der Connector überschreibt bestehende Einstellungen nicht. Neue Upload-/Parse-
Operationen nutzen die aktuellen Dataset-Einstellungen, die aus RAGFlow gelesen
werden.
