from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

libraries_seen_total = Counter("seafile_libraries_seen_total", "Seafile libraries observed")
files_uploaded_total = Counter("seafile_files_uploaded_total", "Files uploaded to RAGFlow")
files_deleted_total = Counter("seafile_files_deleted_total", "RAGFlow documents deleted")
datasets_created_total = Counter("ragflow_datasets_created_total", "RAGFlow datasets created")
parse_started_total = Counter(
    "ragflow_documents_parse_started_total",
    "RAGFlow parse requests started",
)
jobs_queued = Gauge("sync_jobs_queued", "Queued sync jobs")
jobs_failed = Counter("sync_jobs_failed_total", "Failed sync jobs")
job_duration_seconds = Histogram("sync_job_duration_seconds", "Sync job duration")
openwebui_sync_runs_total = Counter("openwebui_sync_runs_total", "OpenWebUI sync runs")
openwebui_artifacts_created_total = Counter(
    "openwebui_artifacts_created_total",
    "OpenWebUI artifacts created",
    ["artifact_type"],
)
openwebui_artifacts_updated_total = Counter(
    "openwebui_artifacts_updated_total",
    "OpenWebUI artifacts updated",
    ["artifact_type"],
)
openwebui_sync_failures_total = Counter(
    "openwebui_sync_failures_total",
    "OpenWebUI sync failures",
)
openwebui_mappings = Gauge("openwebui_dataset_mappings", "OpenWebUI dataset mappings")
openwebui_drifted_artifacts = Gauge(
    "openwebui_drifted_artifacts",
    "OpenWebUI mappings requiring manual repair",
)
openwebui_api_latency_seconds = Histogram("openwebui_api_latency_seconds", "OpenWebUI API latency")
