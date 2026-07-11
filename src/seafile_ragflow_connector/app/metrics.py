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
jobs_running = Gauge("sync_jobs_running", "Running sync jobs")
jobs_oldest_queued_age_seconds = Gauge(
    "sync_jobs_oldest_queued_age_seconds",
    "Age of the oldest queued or retrying job",
)
jobs_failed = Counter("sync_jobs_failed_total", "Failed sync jobs")
jobs_deduplicated_total = Counter(
    "sync_jobs_deduplicated_total",
    "Semantically identical active jobs coalesced",
)
job_duration_seconds = Histogram("sync_job_duration_seconds", "Sync job duration")
upstream_latency_seconds = Histogram(
    "connector_upstream_latency_seconds",
    "Latency of bounded upstream operations",
    ["service", "operation"],
)
authz_denials_total = Counter(
    "connector_authz_denials_total",
    "Authorization denials",
    ["surface"],
)
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
