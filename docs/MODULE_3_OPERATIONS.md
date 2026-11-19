# Module 3 Operations

Module 3 uses PostgreSQL through SQLAlchemy's synchronous psycopg driver. Supabase is supported through its PostgreSQL connection string; use SSL as required by the hosted project and never place the URL in source control.

## Local disposable database

```powershell
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m pytest tests\integration\postgres -v
```

Stop it when finished:

```powershell
docker compose -f docker-compose.test.yml down
```

The test service stores PostgreSQL data in `tmpfs`; removing the container discards it. SQLite is intentionally unsupported because it cannot prove PostgreSQL locking, JSONB, or `SKIP LOCKED` behavior.

## Production-ready migration procedure

1. Back up the target PostgreSQL database.
2. Set `DATABASE_URL` in the deployment secret manager. Hosted/Supabase URLs should require TLS and use a small connection pool.
3. Run `.venv\Scripts\python.exe -m alembic upgrade head` as a one-off release step.
4. Start API/UI processes, then worker processes with distinct `WORKER_ID` values.
5. Verify logs contain work/job IDs but no connection strings or credentials.

No production migration or deployment is performed by Module 3 implementation work.

## Boundaries left for later modules

- Module 4 owns channel profiles and credential references.
- Module 5 owns LLM story generation handlers.
- Module 6 owns story TTS/stock/preview handlers and artifact manifests.
- Module 9 owns publish attempts, provider idempotency, and reconciliation of `UNKNOWN` outcomes.
