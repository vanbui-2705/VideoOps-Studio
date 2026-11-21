# Module 13 Deployment: Packaging, Containers, and CI

Module 13 packages VideoOps Studio as a Python 3.12 application, runs every service as a non-root container, provides a persistent PostgreSQL/media Docker Compose stack, and enforces migrations, lint, formatting, typing, tests, and compilation in CI.

## Local Python deployment

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m alembic upgrade head
python app.py
```

The application reads process environment variables; it does not parse `.env` itself. Load them with your process manager, shell, or Docker Compose.

## Docker Compose

Create `.env` from `.env.example` and replace every placeholder, especially `POSTGRES_PASSWORD`, database/application authentication, and provider credentials. Then:

```powershell
docker compose build
docker compose up -d
docker compose ps
```

The `migrate` service must complete successfully before the UI and workers start. PostgreSQL uses `postgres-data`; all media-producing and media-consuming services share `media-workspace` at `/app/temp`. Back up PostgreSQL according to your recovery objective. The media volume is deliberately ephemeral after verified purge and is not a substitute for a database backup.

The stack runs:

- UI on port 7860
- Story preparation worker
- Remix ingestion worker
- Serialized preview/master media worker
- Official publish/reconcile worker
- Verified purge worker
- Retention sweeper

Do not scale the media, publish, or purge worker beyond their configured concurrency guarantees without redesigning their resource limits. Never expose PostgreSQL publicly.

## Upgrade and rollback

1. Back up PostgreSQL and record the current image/commit.
2. Build the new image and run `python -m alembic upgrade head` once.
3. Start workers/UI and verify logs, health checks, queue progress, and one non-production job.
4. Application rollback is safe only when the old version understands the migrated schema. Test Alembic downgrade in staging; restore the database backup for destructive or incompatible rollbacks.

## CI and release gates

GitHub Actions provisions PostgreSQL 16 and FFmpeg, then runs:

```powershell
python -m alembic upgrade head
python -m alembic downgrade base
python -m alembic upgrade head
python -m ruff check .
python -m ruff format --check .
python -m mypy core ui config.py app.py
python -m pytest -q
python -m compileall -q core ui config.py app.py run_*_worker.py run_retention_sweeper.py
```

A release is not ready if any gate fails, if a non-local deployment starts without authentication, or if migration round-trip has not been tested against a disposable database.
