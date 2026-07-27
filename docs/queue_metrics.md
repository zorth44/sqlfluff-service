# DB Queue Metrics

Prometheus metrics for the DB-as-Queue worker (low-cardinality labels only).

## Gauges

| Metric | Description | Alert hint |
| --- | --- | --- |
| `sql_linting_pending_task_count` | PENDING tasks ready to claim | Sustained growth > 500 for 15m → scale workers |
| `sql_linting_in_progress_task_count` | IN_PROGRESS tasks | > 2× worker concurrency × active workers for 10m → stuck tasks |
| `sql_linting_oldest_pending_age_seconds` | Age of oldest claimable PENDING task | > 300s → backlog or worker outage |
| `sql_linting_active_worker_count` | RUNNING workers with fresh heartbeat | 0 for 2m → no consumers |

## Counters

| Metric | Description | Alert hint |
| --- | --- | --- |
| `sql_linting_expired_lease_count_total` | Leases reclaimed by sweep | Spike > 10/min → tasks too slow or lease too short |
| `sql_linting_retry_task_count_total` | Tasks reset to PENDING after failure | Rising steadily → upstream SQL/NFS issues |
| `sql_linting_permanent_failure_count_total` | Tasks marked FAILURE (max retries) | > 5% of completed tasks/hour → data quality or config |
| `sql_linting_lease_lost_count_total` | Processing abandoned after lease loss | Any sustained rate → shorten work or extend lease |

## Histograms

| Metric | Description | Alert hint |
| --- | --- | --- |
| `sql_linting_task_duration_seconds` | Task processing time | p95 > 600s → tune timeout or SQL size limits |
| `sql_linting_claim_duration_seconds` | DB claim latency | p95 > 1s → DB pool or index pressure |
| `sql_linting_job_expansion_duration_seconds` | ZIP/folder expansion time | p95 > 120s → NFS or archive size |

Gauges are refreshed by `collect_queue_gauges(db)` from the health/metrics endpoint and worker heartbeat.
