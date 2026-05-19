from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


libraries_seen_total = Counter("seafile_libraries_seen_total", "Seafile libraries observed")
files_uploaded_total = Counter("seafile_files_uploaded_total", "Files uploaded to RAGFlow")
files_deleted_total = Counter("seafile_files_deleted_total", "RAGFlow documents deleted")
datasets_created_total = Counter("ragflow_datasets_created_total", "RAGFlow datasets created")
parse_started_total = Counter("ragflow_documents_parse_started_total", "RAGFlow parse requests started")
jobs_queued = Gauge("sync_jobs_queued", "Queued sync jobs")
jobs_failed = Counter("sync_jobs_failed_total", "Failed sync jobs")
job_duration_seconds = Histogram("sync_job_duration_seconds", "Sync job duration")

