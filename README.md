# VideoOps Studio

VideoOps Studio is a cloud-oriented video production pipeline for creating AI Story and Remix previews on resource-constrained infrastructure. It combines a durable PostgreSQL workflow, isolated workers, FFmpeg media processing, and a Gradio operator interface.

The current implementation reaches the human Review Gate: Story and Remix jobs can be prepared, rendered as validated 480p previews, and persisted with revision-safe artifact manifests. Master rendering, platform publishing, and final purge workers remain roadmap items.

## Current capabilities

| Area | Status |
| --- | --- |
| Durable workflow, state machine, leased work queue | Implemented |
| Versioned channel profiles and environment-backed secret references | Implemented |
| AI Story preparation from supplied scripts | Implemented |
| Gemini/OpenAI prompt-to-story adapters | Implemented |
| Edge TTS, subtitles, stock media, and generated fallback visuals | Implemented |
| Story preview rendering | Implemented |
| Public URL validation and bounded yt-dlp ingestion | Implemented |
| Remix trim, speed, crop/fit, mirror, audio normalization, and preview | Implemented |
| Gradio workspace and channel administration UI | Shell implemented; production workflow callbacks are still locked |
| Master rendering, YouTube/TikTok publishing, zero-retention purge | Planned |

## Architecture

```mermaid
flowchart LR
    UI[Gradio operator UI] --> APP[Application services]
    APP --> DB[(PostgreSQL)]
    DB --> SQ[Story worker]
    DB --> RQ[Remix worker]
    SQ --> PW[Preview worker]
    RQ --> PW
    PW --> FS[Revision-scoped media workspace]
    PW --> DB
    DB --> REVIEW[Awaiting Review]
```

Core business logic is framework-independent. Gradio stays in `ui/`; domain and application code under `core/` do not import it. Long-running work is persisted before workers claim it, so UI requests do not need to remain open while media is processed.

## Requirements

- Python 3.10 or newer.
- PostgreSQL 14 or newer; PostgreSQL 16 is used by the integration suite.
- FFmpeg and ffprobe with H.264 (`libx264`) and AAC support.
- yt-dlp for Remix source ingestion.
- Docker, optional, for the local PostgreSQL integration suite.

The target runtime is intentionally conservative: two FFmpeg threads, bounded downloads, revision-isolated workspaces, and no media bytes stored in PostgreSQL.

## Quick start

Clone and install the project:

```powershell
git clone https://github.com/vanbui-2705/VideoOps-Studio.git
cd VideoOps-Studio
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux or macOS, activate the environment with `source .venv/bin/activate`.

Start an ephemeral local PostgreSQL instance:

```powershell
docker compose -f docker-compose.test.yml up -d --wait
$env:DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
python -m alembic upgrade head
```

Launch the UI:

```powershell
python app.py
```

Gradio prints the local URL after startup. The current UI supports workspace inspection and channel-profile administration; Story/Remix submission and Review/Publish buttons remain disabled until the UI is composed with `VideoWorkflow`.

## Configuration

[`.env.example`](.env.example) documents every supported setting. The application currently reads process environment variables directly; it does not automatically load a local `.env` file.

Minimum worker configuration:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@host:5432/videoops"
$env:FFMPEG_BINARY = "ffmpeg"
$env:FFPROBE_BINARY = "ffprobe"
$env:YTDLP_BINARY = "yt-dlp"
```

Optional integrations:

- `LLM_PROVIDER=gemini` with `GEMINI_API_KEY` and `LLM_MODEL`.
- `LLM_PROVIDER=openai` with `OPENAI_API_KEY` and `LLM_MODEL`.
- `PEXELS_API_KEY` and `PIXABAY_API_KEY` for stock media. Generated backgrounds remain available without them.
- Channel credential bundles are resolved from environment variables. Secret values are never stored in channel profiles.

Keep `CHANNEL_ADMIN_ENABLED=false` on public deployments. It is an operational gate for profile mutation, not an authentication system.

## Run the workers

Run each process in its own terminal with the same database configuration and access to the same media workspace.

AI Story preparation:

```powershell
python run_story_worker.py
```

Remix download and normalization:

```powershell
python run_remix_worker.py
```

Shared Story/Remix preview rendering:

```powershell
python run_preview_worker.py
```

The workers lease only their supported work kinds:

```text
PREPARE_STORY  -> run_story_worker.py
PREPARE_REMIX  -> run_remix_worker.py
RENDER_PREVIEW -> run_preview_worker.py
```

## Media profiles

- Landscape preview: 854x480.
- Portrait preview: 270x480.
- H.264/AAC, 30 fps, `yuv420p`, `ultrafast`, and `+faststart`.
- At most two FFmpeg threads.
- Remix sources are limited to public HTTP(S) destinations and 1080p input selection.
- Download byte, source-count, source-duration, render-time, and disk-space limits are configurable.

Valid artifacts are reused only when file size and SHA-256 still match their manifests. Missing or corrupt outputs are rebuilt.

## Testing

Run the fast suite:

```powershell
python -m pytest tests -q
python -m ruff check .
python -m ruff format --check .
```

Run PostgreSQL integration tests:

```powershell
docker compose -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
python -m pytest tests/integration/postgres -q
docker compose -f docker-compose.test.yml down
```

The integration fixture migrates, truncates, and reuses `TEST_DATABASE_URL`. Never point it at a database containing data you need.

## Repository layout

```text
core/domain/                 Domain values, state machine, and policies
core/application/            Workflow use cases and infrastructure-neutral ports
core/adapters/               PostgreSQL, media, secret, and provider adapters
core/runtime/                Durable worker handlers and worker loop
core/llm/                    LLM contracts and provider adapters
ui/                          Gradio-only views and handlers
migrations/                  Alembic PostgreSQL migrations
tests/                       Unit, integration, and local media smoke tests
docs/                        Requirements, design, plans, and operations guides
```

## Documentation

- [Business requirements](docs/BA_BUSINESS_REQUIREMENTS.md)
- [Technical design](docs/TECHNICAL_DESIGN.md)
- [Architecture review](docs/ARCHITECTURE_REVIEW.md)
- [Module 3 operations](docs/MODULE_3_OPERATIONS.md)
- [Module 4 operations](docs/MODULE_4_OPERATIONS.md)
- [Module 5 operations](docs/MODULE_5_OPERATIONS.md)
- [Module 6 operations](docs/MODULE_6_OPERATIONS.md)
- [Module 7 operations](docs/MODULE_7_OPERATIONS.md)

## Security notes

- Subprocess adapters use argument lists and never enable `shell=True`.
- Remix URLs reject embedded credentials, private/non-global resolved IPs, and unsafe schemes before yt-dlp runs.
- Workspace paths are revision-contained and reject traversal or symlink escape.
- Persisted failures and artifact metadata exclude API keys, raw signed URLs, and subprocess stderr.
- Publishing and verified zero-retention cleanup are not implemented yet; do not treat the current Review Gate as a production publishing pipeline.
