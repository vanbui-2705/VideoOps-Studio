# Module 6 Operations: Story Preview Media

Module 6 consumes durable `RENDER_PREVIEW` work. It creates voice audio, UTF-8 subtitles, scene visuals, and a browser-playable 480p preview before moving the job to `AWAITING_REVIEW`.

## Requirements

- FFmpeg and ffprobe must be on `PATH`, or configured through `FFMPEG_BINARY` and `FFPROBE_BINARY`.
- FFmpeg must provide `libx264`, AAC, and the `subtitles` filter.
- PostgreSQL must be migrated to the current head. Module 6 reuses the existing `artifacts` table and does not add a migration.
- `TEMP_DIR` must be writable and have at least `MEDIA_MIN_FREE_DISK_GB` free.

The worker performs these checks before leasing work.

## Stock configuration

Both providers are optional:

```dotenv
PEXELS_API_KEY=
PIXABAY_API_KEY=
```

When keys are missing, quota is exhausted, no result matches, or a provider fails, the pipeline uses deterministic generated backgrounds. Preview rendering therefore remains available without stock credentials or network access.

Downloads accept only allowlisted HTTPS provider hosts and configured image/video content types. Responses stream to `.part` files with a hard byte ceiling before atomic promotion. Provider download URLs and secret headers are not persisted.

## Runtime policy

Relevant settings are documented in `.env.example`:

- TTS connect/receive timeouts.
- Stock request timeout and maximum download bytes.
- Preview render timeout and duration tolerance.
- Media retry attempts and minimum free disk.

Workspaces are revision-scoped:

```text
temp/jobs/<safe-job-id>/revision-<content-revision>/
```

Database artifact manifests store relative paths, checksums, byte sizes, media metadata, and public source/license provenance. Media bytes remain on disk and are never stored in PostgreSQL.

## Run the worker

Apply migrations and configure `DATABASE_URL`, then run:

```powershell
.venv\Scripts\python.exe run_preview_worker.py
```

This process leases only `RENDER_PREVIEW`. Run `run_story_worker.py` separately for `PREPARE_STORY`.

## Preview profile

- Landscape: 854×480.
- Portrait: 270×480.
- H.264/AAC, 30 fps CFR, `yuv420p`, `ultrafast`, `+faststart`.
- At most two FFmpeg threads.
- Voice-over is primary; an available channel BGM is mixed at low volume with ducking.
- Subtitles use the frozen Channel Profile style and are burned into the preview.

Module 6 never renders a master and never publishes.

## Idempotency and recovery

- Artifact IDs include the content revision.
- Valid voice, subtitle, visual, and preview files are reused after worker or workflow-commit retry.
- Size and SHA-256 must still match the manifest before reuse.
- A corrupt or missing file is rebuilt.
- Historical manifests remain until a later purge module verifies physical deletion, preventing orphaned files after regeneration.
- Stale queue work is acknowledged without media side effects.

Expected failures become sanitized `PREVIEW_RENDER` failures with `ResumeAction.PREVIEW`. Raw stderr, absolute workspace paths, narration, API keys, and signed download URLs are excluded from persisted failures and logs.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/media -q
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
.venv\Scripts\python.exe -m pytest tests/integration/postgres -q
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
```

Automated tests use fake TTS and mock HTTP transports. The FFmpeg smoke test uses local synthetic audio and generated backgrounds, so it makes no external network calls.
