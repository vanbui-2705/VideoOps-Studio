# Module 9 Operations: Official Multi-Platform Publishing

Module 9 consumes durable `PUBLISH_TARGET` and `RECONCILE_TARGET` work. It validates the frozen approval and current 1080p H.264/AAC master, resolves a versioned channel credential reference, and publishes through the official YouTube Data API v3 or TikTok Content Posting API. It never handles `PURGE_JOB` and never deletes media.

## Deploy

Apply the current migration and run the publish worker against the same PostgreSQL database and `TEMP_DIR` volume as the UI/media worker:

```powershell
python -m alembic upgrade head
python run_publish_worker.py
```

Run one replica (`PUBLISH_WORKER_CONCURRENCY=1`). Queue leases and logical idempotency keys prevent concurrent consumption and duplicate logical attempts.

## Credentials

For a channel profile using `youtube_secret_ref=YT_TECH`:

- `YT_TECH_YOUTUBE_CLIENT_ID`
- `YT_TECH_YOUTUBE_CLIENT_SECRET`
- `YT_TECH_YOUTUBE_REFRESH_TOKEN`

For `tiktok_secret_ref=TT_TECH`:

- `TT_TECH_TIKTOK_ACCESS_TOKEN`
- `TT_TECH_TIKTOK_OPEN_ID`

Use OAuth tokens/scopes issued for your own provider applications. The resolver is read-only. Tokens, client secrets, provider responses, and TikTok signed upload URLs are not stored in PostgreSQL or displayed in Gradio.

## Runtime settings

- `PUBLISH_REQUEST_TIMEOUT_SECONDS=30`
- `PUBLISH_MAX_ATTEMPTS=5`
- `PUBLISH_RETRY_BASE_SECONDS=2`
- `YOUTUBE_UPLOAD_CHUNK_BYTES=8388608` (must be a positive 256 KiB multiple)
- `YOUTUBE_MAX_CHUNK_RETRIES=5`
- `TIKTOK_API_BASE_URL=https://open.tiktokapis.com`
- `TIKTOK_STATUS_POLL_SECONDS=30`
- `TIKTOK_STATUS_MAX_POLLS=120`
- `PUBLISH_WORKER_CONCURRENCY=1`

YouTube uses resumable chunk uploads with bounded backoff. TikTok uses creator-info, FILE_UPLOAD initialization, chunked upload, and status-fetch endpoints. Cookie/session/browser automation is not supported.

## Recovery

- Each target/content/channel tuple has one SHA-256 logical idempotency key.
- `TargetPublishStarted` is committed before the provider call; the safe receipt is persisted before the success event.
- Interrupted `UPLOADING`, provider `PROCESSING`, and `UNKNOWN` outcomes reconcile before any new publish call.
- A confirmed receipt requires a provider video ID and a trusted HTTPS YouTube/TikTok URL.
- A target failure retains the master. In Review & Publish, refresh the job, inspect each target, then use **Retry / Reconcile** or **Bỏ qua target** with a reason.
- For a failed/unknown TikTok target, the UI exposes the checksum-validated current master as a manual fallback. Downloading it is not treated as publish success; explicitly skip the target only after the operator handles it.

When all targets are succeeded or explicitly skipped, the workflow schedules exactly one `PURGE_JOB`. The Module 10 worker writes the audit snapshot, deletes the job workspace, and verifies zero remaining bytes before completion.

## Verification

```powershell
python -m pytest tests/unit/application/test_publish_contracts.py tests/unit/application/test_publish_coordinator.py tests/unit/publish tests/unit/runtime/test_worker.py -q
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
python -m pytest tests/integration/postgres/test_publish_attempt_store.py tests/integration/postgres/test_publish_worker_journey.py -q
python -m pytest tests -q
python -m ruff check .
python -m ruff format --check .
python -m alembic heads
```
