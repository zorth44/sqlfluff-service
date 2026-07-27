# Database Connection Pool

Pool size is selected by process role (`PROCESS_ROLE` or `WORKER_ROLE`, default `web`).

## Web (default)

- `pool_size = DATABASE_POOL_SIZE_WEB` or **10**
- `max_overflow = DATABASE_MAX_OVERFLOW_WEB` or **20**

## Worker

- `pool_size = DATABASE_POOL_SIZE_WORKER` or **`WORKER_CONCURRENCY + 2`**
- `max_overflow = DATABASE_MAX_OVERFLOW_WORKER` or **`WORKER_CONCURRENCY`**

Rationale: each worker thread may hold a connection during claim/process/renew; add headroom for heartbeat, lease sweep, and job expansion.

Set `PROCESS_ROLE=worker` in worker containers and `PROCESS_ROLE=web` (or unset) for the API process. Chosen values are logged at engine startup.
