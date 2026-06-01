# Manual Seafile-RAGFlow-OpenWebUI Verification

🌐 Languages: [Deutsch](../manual-workflow-verification.md) | **English**

This runbook describes a reproducible test path from uploading a file in
Seafile to querying it through an OpenWebUI pipe. It is intended for local or
dedicated test environments. Do not use production libraries, production
RAGFlow datasets, or production OpenWebUI functions for this check.

## Automated Precheck

Run the local integration test before manual verification:

```bash
uv run pytest tests/integration/test_manual_workflow.py
```

The test uses SQLite and fake clients. It verifies that a uniquely named
Seafile test library and file are discovered, a RAGFlow dataset and document are
created, the RAGFlow chat binding is created, and OpenWebUI tool and pipe
valves receive the dataset ID, chat ID, and connector proxy configuration. It
also verifies that an unreachable OpenWebUI target is recorded as a visible
connector-state error.

## Prerequisites

- The connector is installed from this repository or running as a Compose or
  Portainer stack.
- Seafile is running in a test environment and is reachable from the connector
  container or local connector process.
- RAGFlow is running in the same test environment and is reachable from the
  connector.
- OpenWebUI is running only when the pipe path should be verified.
- Required tokens and API keys are stored only in local runtime configuration,
  never in the Git worktree.
- For TLS with an internal CA, CA bundles are mounted from the perspective of
  the relevant container and referenced in configuration.

## Required Configuration

For Seafile to RAGFlow, set at least these values:

| Variable | Purpose |
| --- | --- |
| `SEAFILE_BASE_URL` | Seafile URL from the connector perspective |
| `SEAFILE_ADMIN_TOKEN` | Seafile admin API token for library discovery |
| `SEAFILE_SYNC_USER_TOKEN` | Seafile API token for file downloads |
| `RAGFLOW_BASE_URL` | RAGFlow API URL from the connector perspective |
| `RAGFLOW_API_KEY` | RAGFlow target-user API key |
| `POSTGRES_PASSWORD` or `DATABASE_URL` | Connector state database |

For OpenWebUI, add:

| Variable | Purpose |
| --- | --- |
| `OPENWEBUI_INTEGRATION_ENABLED=true` | enables the OpenWebUI path |
| `OPENWEBUI_SYNC_MODE=sync` | writes connector-owned tool and pipe artifacts |
| `OPENWEBUI_BASE_URL` | OpenWebUI API URL from the connector perspective |
| `OPENWEBUI_ADMIN_API_KEY` | admin key for tool and function sync |
| `OPENWEBUI_PROXY_INTERNAL_BASE_URL` | connector proxy URL from OpenWebUI |
| `OPENWEBUI_PROXY_PUBLIC_BASE_URL` | browser URL for connector preview links |
| `OPENWEBUI_PROXY_SHARED_SECRET` | shared proxy secret, runtime only |

For direct Compose startup, use the untracked `connector.env` file:

```bash
cp connector.env.example connector.env
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml config --quiet
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml up -d
```

For local CLI execution without Compose, set the same variables in the process
environment. Alternatively use an untracked `stack.env`, because `Settings`
loads that file for local runs.

## Test Artifacts

Use these names so logs, Dashboard, RAGFlow, and OpenWebUI can be correlated:

| Artifact | Name |
| --- | --- |
| Seafile library | `Codex Workflow Check` |
| Seafile folder | `/manual-workflow-check` |
| Seafile file | `seafile-ragflow-openwebui-check.md` |
| Expected dataset pattern | `seafile__codex-workflow-check__...` |
| Expected OpenWebUI model | `Seafile · seafile__codex-workflow-check__...` |
| Expected tool ID | `ragflow_tool_seafile__codex_workflow_check__...` |
| Expected pipe ID | `ragflow_pipe_seafile__codex_workflow_check__...` |

The dataset suffix is derived from the real Seafile repo ID, so it is
environment-specific.

## Step 1: Upload the File to Seafile

1. Create a Seafile test library named `Codex Workflow Check`, or use a clearly
   isolated existing test library with that name.
2. Create the folder `/manual-workflow-check`.
3. Upload `seafile-ragflow-openwebui-check.md`.
4. Use this content:

   ```markdown
   # Codex Workflow Check

   Test question: Which system remains the source of truth?
   Answer anchor: Seafile remains the source of truth.
   ```

5. In Seafile, verify that the file is visible and the library is not encrypted
   or virtual if the default skip rules are active.

## Step 2: Check Live Dependencies

In the Compose stack:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml \
  exec -T connector-controller connector check-live --json
```

Direct local run, when variables are set in the process:

```bash
uv run connector check-live --json
```

Expected: `database=ok`, `redis=ok`, and at least one visible Seafile library.
If `ragflow_template_found=false` appears before the first sync, that is not
yet an error when `RAGFLOW_TEMPLATE_AUTO_CREATE=true` is enabled. After sync,
the template should be visible.

## Dashboard Path

When the stack runs through `connector-controller` with
`CONNECTOR_DASHBOARD_ENABLED=true`, the workflow can be started completely from
the dashboard:

1. Open the dashboard, switch to the **Workflow** tab, and run
   **Check libraries**.
2. The table lists only libraries visible to the current Seafile admin API key.
   Encrypted or virtual libraries remain visible depending on skip rules, but
   are not selectable.
3. Select the test library.
4. Keep **Synchronize RAGFlow dataset and documents** enabled when datasets and
   documents should be created or updated.
5. Keep **Create RAGFlow chat and OpenWebUI tool/pipe** enabled when the
   OpenWebUI path should be created for the selected libraries.
6. Optionally limit the Seafile path to `/manual-workflow-check`.
7. Run **Start selection**, then verify the **Sync runs**, **Systems**, and
   **OpenWebUI** tabs.

The standalone `connector dashboard` command still starts a status dashboard
without the runtime controller. Control is shown there as unavailable.

## Step 3: Trigger Sync to RAGFlow

In the Compose stack:

```bash
docker compose --env-file connector.env -f deploy/portainer/docker-compose.yml \
  exec -T connector-controller connector sync-once --json
```

Direct local run:

```bash
uv run connector sync-once --json
```

Expected:

- `libraries_seen` is at least `1`.
- `files_seen` is at least `1`.
- On the first run, `files_uploaded` is at least `1`.
- If OpenWebUI is enabled, the output also contains an `openwebui` block with
  `datasets_seen`, `tools_created` or `tools_reused`, and `pipes_created` or
  `pipes_reused`.

Connector logs should include `library.sync_started`, `file.uploaded`,
`dataset_id`, `repo_id`, and `sync_id`.

## Step 4: Check RAGFlow Dataset and Document

In RAGFlow, verify:

1. A dataset matching `seafile__codex-workflow-check__...` exists.
2. The dataset contains a document for the uploaded Markdown file. With text
   projection, the document name ends with `.md.txt`.
3. Document metadata contains `repo_id`, `source_path`, `source_sha256`,
   `document_name`, and `file_type`.
4. The parse or indexing status is completed or visibly in progress.

If the document is missing, first check connector logs for `file.skipped`,
`file.uploaded`, and `library.sync_failed`. Common causes are file size limit,
deny-extension policy, wrong Seafile download token, or an unreachable RAGFlow
API.

## Step 5: Check the OpenWebUI Pipe

When OpenWebUI is enabled, the sync can be run again explicitly:

```bash
uv run connector openwebui-sync-once --json
```

In OpenWebUI, verify:

1. A tool exists with the prefix `ragflow_tool_seafile__codex_workflow_check__`.
2. A pipe or function exists with the prefix
   `ragflow_pipe_seafile__codex_workflow_check__`.
3. The pipe is active.
4. The pipe valves contain the correct `DATASET_ID`, a `RAGFLOW_CHAT_ID`,
   `CONNECTOR_PROXY_BASE_URL`, and the runtime proxy secret. Do not copy secret
   values into tickets, logs, or documentation.
5. The model picker shows a model matching
   `Seafile · seafile__codex-workflow-check__...`.

The connector state can also be checked in the Dashboard under
Systems/OpenWebUI. The expected mapping status is `synced`, or `planned` for a
dry run.

## Step 6: Run a Test Query

In OpenWebUI, select the generated model and ask:

```text
Which system remains the source of truth according to the test file?
```

Expected: an answer referring to Seafile as the source of truth, with at least
one source or citation for `seafile-ragflow-openwebui-check.md`. If no source is
shown, check the pipe valves `SOURCE_DISPLAY_MODE`, `EMIT_CITATION_EVENTS`,
and the connector proxy URL.

## Common Failure Modes

| Symptom | Checks |
| --- | --- |
| `check-live` sees no libraries | `SEAFILE_BASE_URL`, admin token, network path from connector |
| File is skipped | deny/allow extensions, file size, `ALLOW_UNKNOWN_TEXT_FILES`, `file.skipped` logs |
| Dataset is missing | RAGFlow API key, template dataset, `library.sync_failed`, RAGFlow permissions |
| Document stays unparsed | RAGFlow parser worker, document status, RAGFlow logs |
| OpenWebUI sync is `failed` | admin key, tool/function API permissions, `OPENWEBUI_BASE_URL` |
| Pipe does not answer | `OPENWEBUI_PROXY_INTERNAL_BASE_URL`, proxy secret, CA bundle in OpenWebUI |
| Source links are missing | `OPENWEBUI_PROXY_PUBLIC_BASE_URL`, preview mode, Seafile file URL template |

## Cleanup

1. Delete the Seafile test library `Codex Workflow Check`.
2. Run connector sync again:

   ```bash
   uv run connector sync-once --json
   ```

3. If OpenWebUI is enabled, then run:

   ```bash
   uv run connector openwebui-sync-once --json
   ```

4. In RAGFlow, verify that the connector-owned dataset is removed when
   `DELETE_DATASET_WHEN_LIBRARY_DELETED=true` is active.
5. In OpenWebUI, verify that connector-owned tool and pipe artifacts are
   removed or marked as deleted.
6. If artifacts remain after an interrupted test, inspect
   `connector cleanup-orphans --json` first and run it with `--execute` only
   when the plan is clearly scoped to the test artifacts.

No production data is required. If a step would affect production services,
abort the run and use an isolated test environment.
