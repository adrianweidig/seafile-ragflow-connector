# Troubleshooting

## Connector Finds No Libraries

Check:

- `SEAFILE_BASE_URL`
- `SEAFILE_ADMIN_TOKEN`
- admin permissions for `/api/v2.1/admin/libraries/`

## RAGFlow Template Not Found

Check:

- `RAGFLOW_API_KEY`
- `RAGFLOW_TEMPLATE_DATASET_NAME`
- whether the API key belongs to the expected RAGFlow user

## Special File Extensions Are Skipped

Check:

- `DENY_EXTENSIONS`
- `ALLOW_UNKNOWN_TEXT_FILES`
- `TEXT_EXTENSIONS`
- classification logs for `detected_encoding` and `is_text`

## Dataset Settings Changed

The connector does not overwrite existing settings. New upload/parse operations use
the current dataset settings observed from RAGFlow.

