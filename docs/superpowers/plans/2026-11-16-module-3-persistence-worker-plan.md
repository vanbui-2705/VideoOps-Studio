# Module 3: PostgreSQL Persistence and Worker Plan

**Goal:** Persist Module 2 workflow aggregates atomically and execute their work intents through a PostgreSQL-backed lease queue.

**Public seams:** `WorkflowStore`, `WorkQueue`, mapper round-trip, and `Worker.run_once`.

## Acceptance map

- [x] PostgreSQL schema and Alembic migration create jobs, commands, transitions, work items, artifacts, publish targets, publish attempts, and audit entries.
- [x] `PostgresWorkflowStore` round-trips Story and Remix aggregates and atomically persists new work.
- [x] Request and command IDs are database-enforced idempotency keys; stale revisions raise `RevisionConflict`.
- [x] `PostgresWorkQueue` atomically claims with `FOR UPDATE SKIP LOCKED`, supports heartbeat, retry/backoff, dead-lettering, and expired-lease recovery.
- [x] Worker commits a typed workflow event before acknowledging work and never retries an unknown publish as a new publish.
- [x] PostgreSQL integration tests, full suite, Ruff, migration, and architecture boundary checks pass.

## Ordered tasks

1. Add safe configuration, dependencies, SQLAlchemy metadata, and Alembic bootstrap.
2. Implement serialization and PostgreSQL `WorkflowStore` with transaction/idempotency tests.
3. Add the `WorkQueue` application contract and PostgreSQL adapter with concurrency/lease tests.
4. Add worker runtime with fake-handler behavioral tests.
5. Run migration and broad verification; document disposable PostgreSQL operation and remaining module boundaries.

## Compatibility and rollback

`core/state_manager.py` remains available for the legacy UI/tests. Domain and application packages must not import SQLAlchemy or psycopg. Deployment and production migrations are outside this task; rollback is code rollback plus Alembic downgrade on a disposable/test database only.
