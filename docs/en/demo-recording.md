# OBS Demo Recording for Seafile, RAGFlow, and OpenWebUI

🌐 Languages: [Deutsch](../demo-recording.md) | **English**

This runbook describes the prepared visible demo path from Seafile through
RAGFlow to OpenWebUI. The default mode is intentionally non-mutating: it only
writes the demo file, plan, and summary. The real test-environment run requires
`--execute`; OBS recording additionally requires `--record`.

## Purpose

The recording should show:

- creating and showing an empty Seafile library,
- showing the related RAGFlow dataset,
- creating the RAGFlow chat and OpenWebUI pipe before uploading the file,
- uploading the demo file to Seafile only after that,
- checking synchronization, parsing, and multiple chunks in RAGFlow,
- using the automatically created pipe in OpenWebUI,
- comparing answer, preview, and original document,
- starting and stopping OBS recording through webhooks.

## OBS Configuration

The automation reads only process environment and never writes secrets to the
worktree.

| Variable | Purpose |
| --- | --- |
| `OBS_WEBHOOK_STATUS_URL` | optional status endpoint |
| `OBS_WEBHOOK_START_URL` | starts recording, required for `--record` |
| `OBS_WEBHOOK_STOP_URL` | stops recording, required for `--record` |
| `OBS_WEBHOOK_MARKER_URL` | optional marker endpoint for important steps |
| `OBS_WEBHOOK_SCENE_URL` | optional scene switch |
| `OBS_WEBHOOK_SCREENSHOT_URL` | reserved for later screenshot checks |
| `OBS_WEBHOOK_TOKEN` | optional webhook token, never printed |
| `OBS_WEBHOOK_TOKEN_HEADER` | optional header, default `Authorization` |
| `OBS_WEBHOOK_TOKEN_SCHEME` | optional scheme, default `Bearer` |
| `OBS_WEBHOOK_PAYLOAD_MODE` | `json` or `none`, default `json` |
| `OBS_SCENE_NAME` | optional OBS scene for the run |

If the webhook does not accept JSON payloads, set
`OBS_WEBHOOK_PAYLOAD_MODE=none`.

## Preparation Without Execution

Use this command while runtime issues still need to be fixed. It does not probe
production services, does not start recording, and does not mutate Seafile,
RAGFlow, or OpenWebUI:

```bash
uv run --extra dev python scripts/record_demo_workflow.py
```

With OBS configuration validation:

```bash
uv run --extra dev python scripts/record_demo_workflow.py --check-obs
```

The output is written below:

```text
output/demo-recording/<demo-id>/
```

It contains:

- `seafile-ragflow-openwebui-demo-<demo-id>.md`,
- `recording-summary.json`.

## Later Real Run

Run this only after the known runtime issues are fixed and the test environment
is ready:

```bash
uv run --extra dev python scripts/record_demo_workflow.py --execute --record --headed
```

To use a persistent Playwright profile with existing test logins:

```bash
uv run --extra dev python scripts/record_demo_workflow.py \
  --execute --record --headed \
  --profile-dir output/demo-recording/browser-profile
```

The real run uses local connector configuration from environment or `stack.env`.
Secrets are not logged. The run creates a uniquely named test library:

```text
Demo RAGFlow OpenWebUI Bibliothek <demo-id>
```

The technical RAGFlow dataset name remains connector-compatible and is derived
from the Seafile library name and real repo ID. The demo label in the summary
and markers is:

```text
Demo Dataset Seafile Sync <demo-id>
```

## Order

In execute mode, the script enforces this order:

1. Optionally validate OBS and start recording.
2. Open Seafile.
3. Create or reuse the test library.
4. Run connector discovery.
5. Ensure the RAGFlow dataset for the library.
6. Run OpenWebUI sync for exactly this library so the RAGFlow chat and
   OpenWebUI pipe exist before upload.
7. Upload the demo file to Seafile.
8. Run connector sync for the library.
9. Wait for RAGFlow parsing until timeout.
10. Validate retrieval against the dataset.
11. Open OpenWebUI so the pipe, answer, preview, and original can be visibly
    checked.
12. Set OBS markers and stop recording cleanly.

## Success Criteria

For the complete video run, visibly check:

- The Seafile library is empty before upload.
- The RAGFlow dataset and chat exist before upload.
- The file is visible in Seafile after upload.
- RAGFlow shows the file, sync status, and parsing status.
- Multiple chunks are visible; at least one chunk contains the demo marker.
- OpenWebUI shows the automatically created pipe.
- The question from `recording-summary.json` is asked and answered.
- Preview and original document contain the same demo marker and matching
  section headings.

## Failure Handling

If an error occurs after recording starts, the script calls the OBS stop
endpoint from a `finally` block. Errors are reported briefly; token values and
runtime secrets are never printed.
