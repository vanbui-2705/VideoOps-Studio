# Module 10 Operations: Verified Purge and Retention

Module 10 is the only component allowed to remove job media. It consumes durable `PURGE_JOB` work, writes a sanitized audit snapshot before deletion, removes the complete job workspace without following links, and emits `PurgeCompleted` only after verifying that zero media bytes remain.

## Run

Apply migrations, then run one purge worker and one retention sweeper against the same PostgreSQL database and `TEMP_DIR` as the other processes:

```powershell
python -m alembic upgrade head
python run_purge_worker.py
python run_retention_sweeper.py
```

The sweeper is policy orchestration, not a second deletion path. It sends an idempotent `Cancel` command for expired jobs; the normal workflow then creates `PURGE_JOB` work.

## Retention policy

- Completed publishing is immediately eligible only when every frozen target is `SUCCEEDED` or explicitly `SKIPPED`.
- Cancelled jobs are eligible for purge.
- Unfinished drafts expire after `DRAFT_RETENTION_HOURS` (default 6).
- Known publish failures expire after `PUBLISH_FAILURE_RETENTION_HOURS` (default 24).
- A target in `UNKNOWN` is never swept automatically because the provider outcome must be reconciled first.
- PostgreSQL workflow and sanitized audit records are retained; revision-scoped media files are removed.

## Safety and recovery

- The purger is scoped to `TEMP_DIR/jobs/<job-id>` and rejects traversal or workspace escape.
- Symlinks and Windows junction/reparse points are unlinked, never traversed.
- Purge is idempotent: a missing workspace is a successful zero-byte result.
- `PURGE_SCAN_MAX_FILES` bounds each filesystem scan.
- Incomplete deletion is retried with bounded exponential delay. After `PURGE_MAX_ATTEMPTS`, the job fails with `PURGE_INCOMPLETE`; fix permissions or file locks, then issue the normal purge retry command.
- Never manually mark a job completed while media remains.

## Settings

```text
PURGE_WORKER_CONCURRENCY=1
PURGE_MAX_ATTEMPTS=5
PURGE_RETRY_BASE_SECONDS=5
DRAFT_RETENTION_HOURS=6
PUBLISH_FAILURE_RETENTION_HOURS=24
PURGE_SCAN_MAX_FILES=10000
RETENTION_SWEEP_INTERVAL_SECONDS=300
RETENTION_SWEEP_BATCH_SIZE=100
```

## Verification

```powershell
python -m pytest tests/unit/purge tests/unit/application/test_purge_coordinator.py tests/unit/application/test_retention_sweeper.py -q
python -m pytest tests/integration/postgres/test_purge_audit_store.py tests/integration/postgres/test_purge_worker_journey.py -q
```
