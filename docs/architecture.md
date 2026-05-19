# Architecture

The connector is a control plane. It does not patch RAGFlow and does not use WebDAV
as the core sync mechanism.

```text
Seafile API -> controller -> PostgreSQL state -> Redis jobs -> workers -> RAGFlow API
                         \-> reconciler ------------------------/
```

## Components

| Component | Responsibility |
| --- | --- |
| controller | discovery loop, dataset provisioning, delta scheduling |
| worker | download, classify, prepare artifacts, upload, delete, parse |
| reconciler | repair divergent Seafile/DB/RAGFlow state |
| PostgreSQL | durable sync memory and job history |
| Redis | queue, retry delay, worker fan-out |

## Dataset Settings

`connector_template` is only used when a RAGFlow dataset is created. After that,
the target dataset's current RAGFlow settings are authoritative. This allows an
admin to change chunking, parser settings, or ingestion pipeline directly in RAGFlow
without reconfiguring the connector.

## File Ingestion

The connector treats file extensions as hints, not as the complete policy. Unknown
files can be accepted when they are detected as text. Code and special text formats
such as Ada files are projected into stable text artifacts before upload when needed.

