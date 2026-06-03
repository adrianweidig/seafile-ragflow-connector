# OBS Demo Recording for Seafile, RAGFlow, and OpenWebUI

🌐 Languages: [Deutsch](../demo-recording.md) | **English**

This runbook describes the prepared visible demo path from Seafile through
RAGFlow to OpenWebUI. The default mode is intentionally non-mutating: it only
writes the demo file, plan, and summary. The real test-environment run requires
`--execute`; OBS recording additionally requires `--record`.

The primary recording must be an OBS-generated `.mkv`. Browser videos,
Playwright WebM files, or isolated OpenWebUI chat recordings are diagnostic
artifacts only and do not satisfy the demo requirement.

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
| `OBS_WEBHOOK_SCREENSHOT_URL` | OBS source screenshot for visible marker validation |
| `OBS_WEBHOOK_TOKEN` | optional webhook token, never printed |
| `OBS_WEBHOOK_TOKEN_HEADER` | optional header, default `Authorization` |
| `OBS_WEBHOOK_TOKEN_SCHEME` | optional scheme, default `Bearer` |
| `OBS_WEBHOOK_PAYLOAD_MODE` | `json` or `none`, default `json` |
| `OBS_RECORDING_OUTPUT_DIR` | local OBS output directory used to find the MKV |
| `OBS_RECORDING_EXPECTED_EXTENSION` | expected extension, default `.mkv` |
| `OBS_RECORDING_FORMAT` | alternative format hint, `mkv` becomes `.mkv` |
| `OBS_SCENE_NAME` | optional OBS scene for the run |
| `OBS_SCREENSHOT_WIDTH` / `OBS_SCREENSHOT_HEIGHT` | screenshot size for marker validation, default `1920x1080` |

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

- `demo-seafile-ragflow-openwebui-workflow-<demo-id>.md`,
- `recording-summary.json`.

With an OBS screenshot webhook, the run directory also contains
`obs-screenshots/`. These PNGs must show the browser phases; the desktop,
terminal, or a static wrong application window counts as failed visual
validation.

## Real Run

Run this only when the test environment is ready and the OBS webhook is
reachable. For local Windows/WSL demos, the Seafile download URL must be
rewritten to a host reachable from Windows, for example:

```powershell
$env:SEAFILE_REWRITE_DOWNLOAD_URLS = "true"
$env:SEAFILE_DOWNLOAD_REWRITE_FROM = "https://seafile.top.secret/seafhttp"
$env:SEAFILE_DOWNLOAD_REWRITE_TO = "http://127.0.0.1:18080/seafhttp"
```

The visible run should minimize other windows and place the browser on the
OBS-captured area:

```bash
uv run --extra dev python scripts/record_demo_workflow.py \
  --execute --record --headed --minimize-other-windows \
  --browser-window-x 0 --browser-window-y 0 \
  --browser-window-width 1920 --browser-window-height 1080 \
  --obs-output-dir "C:\Users\adria\Videos"
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
Demo OBS Seafile RAGFlow OpenWebUI <demo-id>
```

The technical RAGFlow dataset name remains connector-compatible and is derived
from the Seafile library name and real repo ID. The demo label in the summary
and markers is:

```text
Demo OBS Dataset Seafile Sync <demo-id>
```

The OBS recording name is:

```text
demo-seafile-ragflow-openwebui-full-workflow-<demo-id>.mkv
```

## Order

In execute mode, the script enforces this order:

1. Prepare the demo browser window.
2. Open Seafile, place the visible browser window, and validate it with an
   OBS screenshot.
3. Optionally validate OBS and start recording.
4. Create or reuse the test library.
5. Open the library and verify through API that it is empty before upload.
6. Run connector discovery.
7. Ensure the RAGFlow dataset for the library.
8. Create and visibly open the RAGFlow chat or assistant before upload.
9. Upload the demo file to Seafile only after that.
10. Run connector sync for the library.
11. Wait for RAGFlow parsing until timeout.
12. Validate retrieval against the dataset and mark the chunk evidence.
13. Run OpenWebUI sync for exactly this library so the RAGFlow chat and
   OpenWebUI pipe are created after successful parsing.
14. Open OpenWebUI, select the pipe, ask the question, and wait for the answer.
15. Open the source preview.
16. Open the original file.
17. Set OBS markers and stop recording cleanly.
18. Find the generated `.mkv` in the OBS output directory and verify its size.

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
- `recording-summary.json` reports `erfüllt` for every required point; otherwise
  the script does not finish successfully.
- `checks.obs_recording.artifact` reports `valid: true`, `extension_ok: true`,
  and a size greater than 0.

## Failure Handling

If an error occurs after recording starts, the script calls the OBS stop
endpoint from a `finally` block. Errors are reported briefly; token values and
runtime secrets are never printed.
