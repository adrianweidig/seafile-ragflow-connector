# Recovery

## Worker Crash

Jobs are idempotent. Locks expire and jobs can be executed again.

## Redis Loss

PostgreSQL remains the recovery source. Queued or running jobs can be reconstructed
from durable job state.

## Seafile Outage

No delete decisions are made while Seafile is unreachable. Download and discovery
jobs retry.

## RAGFlow Outage

Upload, delete, parse, and status jobs retry with backoff. Discovery can continue
but should apply backpressure to avoid unbounded queues.

