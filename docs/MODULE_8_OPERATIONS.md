# Module 8 Operations: Review Gate and Master Rendering

Module 8 lets an operator inspect a validated 480p preview, edit metadata, request a new content revision, or approve the current revision. Approval freezes metadata, target platforms, content revision, and channel revision, then schedules a 1080p master. A successful master moves the job to `PUBLISHING` and creates durable `PUBLISH_TARGET` work; no platform upload occurs in this module.

## Runtime requirements

- PostgreSQL must be migrated to the current Alembic head.
- The UI and media worker must share `DATABASE_URL` and the same `TEMP_DIR` volume.
- FFmpeg and ffprobe must provide `libx264`, AAC, and the subtitles filter.
- Run exactly one `run_preview_worker.py` replica. `MEDIA_RENDER_CONCURRENCY` is intentionally fixed at `1`, which serializes preview and master FFmpeg work.
- Keep `MAX_FFMPEG_THREADS` at `2` or lower.

## Configuration

- `MASTER_RENDER_TIMEOUT_SECONDS=900`: hard timeout for master FFmpeg work.
- `MASTER_PRESET=superfast`: bounded encoding preset; other values are rejected at startup.
- `MASTER_CRF=23`: H.264 quality setting, accepted range 0–51.
- `MASTER_DURATION_TOLERANCE_MS=1000`: maximum allowed duration drift.
- `MEDIA_RENDER_CONCURRENCY=1`: required serialized render lane.

Start the UI and shared media worker:

```powershell
.venv\Scripts\python.exe app.py
.venv\Scripts\python.exe run_preview_worker.py
```

## Review procedure

1. Open **Review & Publish**, enter the job ID, and select **Tải / Làm mới**.
2. Verify video, audio, subtitles, metadata, content revision, and available targets.
3. Save metadata if needed. A revision conflict requires refreshing before another command.
4. Use **Dựng lại** with non-empty instructions to create a new content revision and preview.
5. Select at least one available target and choose **Duyệt & dựng master**.

Refresh is read-only. The facade accepts a preview only when its manifest belongs to the current job/revision and its contained file still matches byte size and SHA-256. Cancellation remains disabled until the purge worker exists.

## Master policy

- Story masters use original narration, subtitle, and visual source artifacts.
- Remix masters use retained source downloads and reapply frozen trim, speed, fit/crop, and mirror transforms in one 1080p composition pass.
- Preview files and 480p normalized Remix clips are never master inputs.
- Landscape is 1920x1080; portrait is 1080x1920.
- Output is H.264/AAC, 30 fps, `yuv420p`, `superfast`, CRF 23, `+faststart`, with at most two FFmpeg threads.
- ffprobe validation occurs before atomic `.part` promotion. Failed or invalid partial files are removed.
- A valid size/checksum/profile manifest is reused; missing or corrupt output is rebuilt.

## Recovery and scope boundary

Stale leased work is acknowledged without media side effects. Expected master failures persist a sanitized `MASTER_RENDER` failure with `ResumeAction.MASTER`; subprocess stderr, credentials, absolute paths, and source URLs are not persisted.

After success, inspect the job for `PUBLISHING`, one `MASTER` reference, and one pending `PUBLISH_TARGET` work item per selected target. Do not run an ad-hoc publisher or delete media. Module 9 owns publishing; Module 10 owns verified zero-retention purge.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/media/test_master_service.py tests/unit/media/test_master_adapters.py tests/unit/runtime/test_master_handler.py -q
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
.venv\Scripts\python.exe -m pytest tests/integration/postgres/test_master_worker_journey.py -q
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\alembic.exe heads
```
