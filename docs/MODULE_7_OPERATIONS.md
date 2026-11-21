# Module 7 Operations: Remix Media

Module 7 consumes durable `PREPARE_REMIX` work, downloads and normalizes each source, then uses the shared preview worker to create a browser-playable 480p Remix preview. A successful job moves to `AWAITING_REVIEW`.

## Requirements

- FFmpeg, ffprobe, and yt-dlp must be on `PATH`, or configured through `FFMPEG_BINARY`, `FFPROBE_BINARY`, and `YTDLP_BINARY`.
- FFmpeg must provide `libx264`, AAC, and the `subtitles` filter required by the shared media runtime.
- PostgreSQL must be migrated to the current head. Module 7 reuses existing job, work-item, artifact, and channel tables and does not add a migration.
- `TEMP_DIR` must be writable and have at least `MEDIA_MIN_FREE_DISK_GB` free.

The Remix preparation worker performs these checks before leasing work.

## Configuration

Relevant settings are documented in `.env.example`:

- `REMIX_DOWNLOAD_TIMEOUT_SECONDS`: hard timeout for one yt-dlp invocation.
- `REMIX_MAX_DOWNLOAD_BYTES`: maximum accepted bytes for one source.
- `REMIX_MAX_SOURCES`: maximum clips in one request.
- `REMIX_MAX_SOURCE_DURATION_SECONDS`: maximum duration of an individual downloaded source.
- `REMIX_DURATION_TOLERANCE_MS`: allowed probe/encode timing drift.
- `PREVIEW_RENDER_TIMEOUT_SECONDS`: timeout for clip normalization and preview FFmpeg calls.

Defaults permit at most 10 sources, 1 GiB per download, and two hours per source. Request speeds are limited to `0.25` through `4.0`.

## Run the workers

Apply migrations and configure `DATABASE_URL`, then run both processes:

```powershell
.venv\Scripts\python.exe run_remix_worker.py
.venv\Scripts\python.exe run_preview_worker.py
```

`run_remix_worker.py` leases only `PREPARE_REMIX`. It downloads, probes, and normalizes sources, then schedules `RENDER_PREVIEW`. The shared preview worker leases only `RENDER_PREVIEW` and dispatches Story or Remix rendering from the frozen job type.

## Input and output policy

- Clip order is contiguous and 1-based.
- Source URLs must use HTTP(S), contain no embedded credentials, and resolve only to public IP addresses.
- Playlists are disabled and source selection is limited to 1080p.
- Source clip ranges must fit inside probed duration.
- Audio-only sources are rejected. Video without audio receives a silent stereo track before concatenation.
- `fill` crops centrally after scaling; `fit` pads after scaling. Mirror and supported speed changes are applied before normalization.
- Landscape preview is 854x480; portrait preview is 270x480.
- Output is H.264/AAC, 30 fps, `yuv420p`, `ultrafast`, `+faststart`, using at most two FFmpeg threads.

Module 7 never renders a master and never publishes.

## Security and retention

The downloader uses an argument list and never invokes a shell. DNS validation runs before yt-dlp, output paths are revision-contained, and partial files are removed after timeout, process failure, invalid output, or size rejection.

Artifact metadata stores only the source hostname, not the raw URL or query string. Persisted worker failures contain sanitized codes/messages and exclude subprocess stderr, local absolute paths, credentials, and source URLs.

Media remains in the job workspace for Review Gate and safe retry. Final deletion is owned by the Module 10 zero-retention purge stage after publishing or cancellation.

## Idempotency and recovery

- Workspaces are isolated by job ID and content revision.
- Artifact IDs include the clip order and content revision.
- Size and SHA-256 must match the manifest before an artifact is reused.
- Missing or corrupt normalized clips and previews are rebuilt.
- Valid downloaded sources are reused when normalization retries.
- Stale queue work is acknowledged without downloading or rendering.

Expected preparation failures use `ResumeAction.PREPARE`; preview failures use `ResumeAction.PREVIEW`.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/media/test_remix_requests.py tests/unit/media/test_remix_service.py tests/unit/media/test_remix_adapters.py tests/unit/runtime/test_remix_handler.py -q
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
.venv\Scripts\python.exe -m pytest tests/integration/postgres -q
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\alembic.exe heads
```

Automated adapter tests use fake download runners and synthetic local media. They do not fetch third-party content.
