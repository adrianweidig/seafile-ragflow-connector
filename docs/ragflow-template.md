# RAGFlow-Template

Der Connector sucht genau ein Dataset mit dem Namen aus
`RAGFLOW_TEMPLATE_DATASET_NAME`, standardmäßig `connector_template`.

Das Template wird nur für die Dataset-Erstellung verwendet. Bestehende Datasets
behalten ihre aktuellen RAGFlow-Einstellungen.

## Create-Payload-Whitelist

- `avatar`
- `description`
- `embedding_model`
- `permission`
- `chunk_method`
- `parser_config`
- `parse_type`
- `pipeline_id`

`name` wird immer vom Connector generiert.

Built-in Chunking (`chunk_method`, `parser_config`) und Ingestion-Pipeline-Modus
(`parse_type`, `pipeline_id`) dürfen nicht gemischt werden.
