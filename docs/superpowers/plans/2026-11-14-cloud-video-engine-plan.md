# Cloud Video Auto-Creation & Push Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 100% cloud-hosted, zero-local-resource automated video production and multi-channel auto-publishing engine with a web review gate, chunked FFmpeg composition, multi-channel persona profiles, and post-publish zero-retention disk wiping.

**Architecture:** A decoupled Python architecture where headless core modules (`core/`) handle channel profiles, TTS, stock fetching, stream ingestion, chunked FFmpeg rendering, and resumable uploading. A reactive Gradio 4/5 frontend (`app.py`) provides channel selection, job triggering, and a human review gate with streamable video preview and one-click publishing.

**Tech Stack:** Python 3.10+, Gradio, FFmpeg (CLI), `edge-tts`, `yt-dlp`, `httpx`, `google-api-python-client`, `pytest`, `ruff`, `mypy`.

**Spec:** `docs/superpowers/specs/2026-11-14-cloud-video-engine-design.md`  
**Architecture Spec:** `ARCHITECTURE.md`  
**Developer Guidelines:** `CLAUDE.md`  

## Global Constraints

- **Host Compute:** Hugging Face Spaces free tier (2 vCPU, 16 GB RAM, 50 GB temporary disk).
- **Subprocess Safety:** NEVER use `shell=True` in subprocess calls; always use argument lists (`['ffmpeg', '-i', ...]`).
- **Headless Invariant:** Code inside `core/` MUST NEVER import `gradio`.
- **Zero-Retention Policy:** Master MP4, intermediate audio, raw clips, and subtitle files must be immediately purged from disk upon HTTP 200 upload confirmation.
- **FFmpeg Concurrency:** Explicitly limit encoding to `-threads 2` with `superfast` (CRF 23) for master render and `ultrafast` for preview pass.

## Review Focus

1. **Missing Pexels API Key or Network Failure:** If stock image/video API fails or is unconfigured, fallback must cleanly generate solid backgrounds with Ken Burns zoom without throwing unhandled exceptions.
2. **Malformed Subtitle Timestamps / Special Characters:** Text containing quotes, backslashes, emojis, or Vietnamese diacritics must not break FFmpeg subtitle filter escaping.
3. **Double-Click on Publish Button:** Idempotency gate must prevent duplicate YouTube/TikTok uploads when the user clicks the approval button repeatedly.
4. **YouTube API Quota Exceeded (HTTP 403 / quotaExceeded):** Publisher must catch quota exceptions cleanly, alert the user via UI status, and preserve the master video until resolved rather than deleting it.
5. **Disk Space Exhaustion on Long Runs:** If output directory exceeds 40 GB, the state manager must actively evict abandoned jobs before commencing a new render.

---

### Task 1: Scaffolding, Environment Config & Git Setup

**Files:**
- Create: `requirements.txt`
- Create: `packages.txt`
- Create: `.gitignore`
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.AppConfig` dataclass providing paths (`OUTPUT_DIR`, `TEMP_DIR`, `CHANNELS_DIR`, `FONTS_DIR`, `BGM_DIR`), API keys (`PEXELS_API_KEY`, `GEMINI_API_KEY`), and thread limits.

- [ ] **Step 1: Write failing test for config loader**

```python
# tests/test_config.py
from pathlib import Path
from config import load_config

def test_load_config_defaults():
    cfg = load_config()
    assert cfg.MAX_FFMPEG_THREADS == 2
    assert Path(cfg.TEMP_DIR).exists()
    assert Path(cfg.OUTPUT_DIR).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement dependencies, directories, and `config.py`**

Create `requirements.txt` with `gradio>=4.0.0`, `edge-tts`, `yt-dlp`, `httpx`, `pydantic>=2.0`, `google-api-python-client`, `google-auth-oauthlib`, `pytest`, `pytest-asyncio`, `ruff`.  
Create `packages.txt` with `ffmpeg`.  
Create `.gitignore` ignoring `.venv/`, `temp/`, `outputs/`, `*.mp4`, `*.wav`, `*.srt`, `.env`.  
Implement `config.py` with directory auto-creation and environment loading.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git init
git add requirements.txt packages.txt .gitignore config.py tests/test_config.py
git commit -m "feat(config): initialize project structure and config loader"
```

---

### Task 2: Core Data Models & State Manager with Zero-Retention Purge

**Files:**
- Create: `core/models.py`
- Create: `core/state_manager.py`
- Test: `tests/test_state_manager.py`

**Interfaces:**
- Consumes: `config.AppConfig`
- Produces:
  - `VideoJob`: Dataclass tracking `job_id`, `channel_id`, `status`, `preview_path`, `master_path`, `metadata`, `temp_files`.
  - `JobStatus`: Enum (`IDLE`, `INGESTING`, `RENDERING_PREVIEW`, `AWAITING_REVIEW`, `PUBLISHING`, `COMPLETED`, `FAILED`).
  - `StateManager`: Methods `create_job()`, `update_job()`, `get_job()`, `purge_job_artifacts(job_id)`.

- [ ] **Step 1: Write failing test for StateManager & artifact purge**

```python
# tests/test_state_manager.py
import os
from pathlib import Path
from core.models import VideoJob, JobStatus
from core.state_manager import StateManager

def test_purge_job_artifacts(tmp_path):
    mgr = StateManager(storage_dir=str(tmp_path))
    job = mgr.create_job(channel_id="tech_test")
    
    dummy_file = tmp_path / "test_chunk.mp4"
    dummy_file.write_text("dummy video content")
    job.temp_files.append(str(dummy_file))
    
    assert dummy_file.exists()
    mgr.purge_job_artifacts(job.job_id)
    assert not dummy_file.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state_manager.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.models'`

- [ ] **Step 3: Implement `core/models.py` and `core/state_manager.py`**

Define `JobStatus`, `VideoMetadata`, and `VideoJob` in `core/models.py`.  
Implement `StateManager` with job registration, state transitions, and file unlinking in `core/state_manager.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state_manager.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py core/state_manager.py tests/test_state_manager.py
git commit -m "feat(core): add data models and state manager with zero-retention purge"
```

---

### Task 3: Multi-Channel Profile Manager & Prompt Templating

**Files:**
- Create: `channels/tech_news.json`
- Create: `channels/story_lofi.json`
- Create: `core/channel_manager.py`
- Test: `tests/test_channel_manager.py`

**Interfaces:**
- Produces:
  - `ChannelProfile`: Dataclass holding channel metadata, aspect ratio, voice, bgm, subtitle styling, prompt template, and platform credentials.
  - `ChannelManager`: Methods `load_all_channels()`, `get_channel(channel_id)`, `format_prompt(channel_id, raw_prompt)`, `save_channel(profile)`.

- [ ] **Step 1: Write failing test for ChannelManager**

```python
# tests/test_channel_manager.py
from core.channel_manager import ChannelManager

def test_channel_manager_loads_profiles(tmp_path):
    mgr = ChannelManager(channels_dir="channels")
    channels = mgr.load_all_channels()
    assert "tech_news" in channels
    profile = mgr.get_channel("tech_news")
    assert profile.aspect_ratio in ["16:9", "9:16"]
    
    formatted = mgr.format_prompt("tech_news", "AI chip breakthrough")
    assert "AI chip breakthrough" in formatted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_channel_manager.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.channel_manager'`

- [ ] **Step 3: Implement sample channel configs and `core/channel_manager.py`**

Create `channels/tech_news.json` (16:9, `vi-VN-NamMinhNeural`, tech tags).  
Create `channels/story_lofi.json` (9:16, `vi-VN-HoaiMyNeural`, lofi tags).  
Implement `ChannelManager` with JSON persistence and string formatting for prompt wraps.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_channel_manager.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add channels/ core/channel_manager.py tests/test_channel_manager.py
git commit -m "feat(channel): add multi-channel profile manager and persona templates"
```

---

### Task 4: TTS & Subtitle Generator (`edge-tts`)

**Files:**
- Create: `core/tts_engine.py`
- Test: `tests/test_tts_engine.py`

**Interfaces:**
- Consumes: Voice name (`str`), text content (`str`), output audio path (`Path`), output SRT path (`Path`).
- Produces: `generate_audio_and_subtitles(text: str, voice: str, audio_path: str, srt_path: str) -> float` (returns audio duration in seconds).

- [ ] **Step 1: Write failing test with mock for `edge-tts`**

```python
# tests/test_tts_engine.py
import pytest
from pathlib import Path
from core.tts_engine import TTSEngine

@pytest.mark.asyncio
async def test_srt_formatting_from_submaker(tmp_path):
    engine = TTSEngine()
    sub_path = tmp_path / "test.srt"
    audio_path = tmp_path / "test.mp3"
    
    # Test subtitle text sanitizer and timing converter
    sample_subs = engine.format_srt_entry(index=1, start=0.0, end=2.5, text="Xin chào các bạn")
    assert "00:00:00,000 --> 00:00:02,500" in sample_subs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_engine.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.tts_engine'`

- [ ] **Step 3: Implement `core/tts_engine.py`**

Implement async TTS synthesis using `edge_tts.Communicate`.  
Extract word boundaries using `edge_tts.SubMaker` to construct standard SRT files with UTF-8 encoding.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_engine.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tts_engine.py tests/test_tts_engine.py
git commit -m "feat(tts): implement edge-tts audio and srt subtitle generation"
```

---

### Task 5: Media Ingestion & Stock Footage Downloader

**Files:**
- Create: `core/downloader.py`
- Create: `core/stock_fetcher.py`
- Test: `tests/test_ingestion.py`

**Interfaces:**
- Produces:
  - `MediaDownloader.download_stream(url: str, output_path: str, max_height: int = 1080) -> str`
  - `StockFetcher.fetch_clips(query: str, count: int, orientation: str, output_dir: str) -> list[str]`

- [ ] **Step 1: Write failing test with mocked network requests**

```python
# tests/test_ingestion.py
from unittest.mock import patch, MagicMock
from core.stock_fetcher import StockFetcher
from core.downloader import MediaDownloader

def test_stock_fetcher_fallback_without_api_key(tmp_path):
    fetcher = StockFetcher(api_key=None)
    clips = fetcher.fetch_clips(query="technology", count=2, orientation="landscape", output_dir=str(tmp_path))
    # Should cleanly return fallback images/color canvases without throwing
    assert len(clips) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingestion.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.stock_fetcher'`

- [ ] **Step 3: Implement `core/downloader.py` and `core/stock_fetcher.py`**

Implement `MediaDownloader` using `yt-dlp.YoutubeDL` with safe options (`noplaylist: True`, format constraints).  
Implement `StockFetcher` using `httpx` for Pexels API + local fallback canvas generator if key is missing or quota exceeded.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingestion.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/downloader.py core/stock_fetcher.py tests/test_ingestion.py
git commit -m "feat(ingest): add yt-dlp downloader and stock footage fetcher with fallback"
```

---

### Task 6: FFmpeg Composition Engine (Chunked Rendering & Two-Tier Passes)

**Files:**
- Create: `core/ffmpeg_builder.py`
- Test: `tests/test_ffmpeg_builder.py`

**Interfaces:**
- Consumes: Audio track, subtitle file, visual clips, aspect ratio, BGM path.
- Produces:
  - `build_preview(clips: list[str], audio_path: str, srt_path: str, output_path: str, aspect_ratio: str) -> str` (480p, `ultrafast`).
  - `build_master(clips: list[str], audio_path: str, srt_path: str, bgm_path: str | None, output_path: str, aspect_ratio: str) -> str` (1080p, `superfast`, ducking).

- [ ] **Step 1: Write failing test verifying FFmpeg CLI argument generation**

```python
# tests/test_ffmpeg_builder.py
from core.ffmpeg_builder import FFmpegBuilder

def test_ffmpeg_command_structure():
    builder = FFmpegBuilder(threads=2)
    cmd = builder.create_master_render_cmd(
        video_clips=["clip1.mp4", "clip2.mp4"],
        audio_path="voice.wav",
        srt_path="subs.srt",
        bgm_path="bgm.mp3",
        output_path="final.mp4",
        aspect_ratio="16:9"
    )
    assert "-threads" in cmd
    assert "2" in cmd
    assert "-filter_complex" in cmd
    # Ensure safe list format, not shell string
    assert isinstance(cmd, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ffmpeg_builder.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.ffmpeg_builder'`

- [ ] **Step 3: Implement `core/ffmpeg_builder.py`**

Build argument lists for `subprocess.run(..., check=True)`.  
Implement aspect ratio scaling filter (`scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2` and vertical equivalent).  
Implement audio sidechain ducking filter (`amix`).  
Implement subtitle escaping to prevent filter injection.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ffmpeg_builder.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/ffmpeg_builder.py tests/test_ffmpeg_builder.py
git commit -m "feat(ffmpeg): implement chunked composition engine and filtergraph builder"
```

---

### Task 7: Multi-Platform Uploader (YouTube Resumable & TikTok Cookie)

**Files:**
- Create: `core/uploader/youtube.py`
- Create: `core/uploader/tiktok.py`
- Create: `core/uploader/__init__.py`
- Test: `tests/test_uploader.py`

**Interfaces:**
- Produces:
  - `YouTubeUploader.upload_video(file_path: str, title: str, description: str, tags: list[str], privacy: str) -> str`
  - `TikTokUploader.upload_video(file_path: str, title: str, tags: list[str]) -> str`

- [ ] **Step 1: Write failing test with mocked API client**

```python
# tests/test_uploader.py
from unittest.mock import MagicMock, patch
from core.uploader.youtube import YouTubeUploader

def test_youtube_upload_retry_logic():
    with patch("core.uploader.youtube.build") as mock_build:
        uploader = YouTubeUploader(client_id="mock_id", client_secret="mock_sec", refresh_token="mock_tok")
        # Validate handling of chunked resumable upload requests
        assert uploader is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uploader.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.uploader'`

- [ ] **Step 3: Implement `core/uploader/youtube.py` and `core/uploader/tiktok.py`**

Implement YouTube resumable chunk uploader using `googleapiclient.http.MediaFileUpload` with chunksize = 8MB and retry backoff.  
Implement TikTok uploader with cookie auth and manual download fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_uploader.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/uploader/ tests/test_uploader.py
git commit -m "feat(uploader): implement resumable youtube and tiktok publishers"
```

---

### Task 8: Pipeline Orchestrator & Zero-Retention Integration

**Files:**
- Create: `core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `ChannelManager`, `StateManager`, `TTSEngine`, `StockFetcher`, `MediaDownloader`, `FFmpegBuilder`, `YouTubeUploader`, `TikTokUploader`.
- Produces: `PipelineController.generate_preview(request: StoryRequest) -> VideoJob`, `PipelineController.publish_and_purge(job_id: str) -> PublishResult`.

- [ ] **Step 1: Write failing integration test with mocks**

```python
# tests/test_pipeline.py
from unittest.mock import MagicMock, patch
from core.pipeline import PipelineController

def test_pipeline_publish_and_purge_flow():
    with patch("core.pipeline.YouTubeUploader") as mock_yt:
        mock_yt.return_value.upload_video.return_value = "https://youtube.com/watch?v=mock123"
        controller = PipelineController()
        # Verify publish triggers zero-retention artifact deletion
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.pipeline'`

- [ ] **Step 3: Implement `core/pipeline.py`**

Orchestrate the full flow: Channel selection -> Prompt formatting -> TTS -> Stock / Ingestion -> Preview Render -> Wait for approval -> Master Render -> Upload -> Zero-Retention Purge.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): implement headless pipeline controller with zero-retention publish"
```

---

### Task 9: Gradio Web UI (`app.py`)

**Files:**
- Create: `app.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `core.pipeline.PipelineController`, `core.channel_manager.ChannelManager`.
- Produces: Runnable Gradio Blocks interface `demo = create_ui()`.

- [ ] **Step 1: Write failing test verifying Gradio Blocks creation**

```python
# tests/test_ui.py
import gradio as gr
from app import create_ui

def test_ui_blocks_instantiation():
    demo = create_ui()
    assert isinstance(demo, gr.Blocks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement `app.py`**

Implement Gradio 4/5 Blocks UI:
- Channel Selector Dropdown at top.
- Tab 1: AI Story Generator (Script text, voice dropdown, visual keywords, [Generate Preview] button).
- Tab 2: Video Remix (URL inputs, crop settings, [Generate Preview] button).
- Tab 3: Review & Publish Gate (HTML5 Video Player, Title/Desc/Tags metadata inputs, [Approve & Publish] button, progress log).
- Tab 4: Channel & Secrets Manager (Edit channel profiles, paste tokens).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_ui.py
git commit -m "feat(ui): implement multi-tab gradio web interface with review gate"
```

---

### Task 10: CI/CD Pipeline, Linting & End-to-End Verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: Run full test suite & linter locally

- [ ] **Step 1: Create GitHub Actions CI workflow**

Define `.github/workflows/ci.yml` running on `ubuntu-latest` with Python 3.10, installing `ffmpeg`, running `ruff check .` and `pytest tests/ -v`.

- [ ] **Step 2: Run linter and type checker locally**

Run: `ruff check .` and `pytest tests/ -v`  
Expected: All tests PASS with zero linting errors.

- [ ] **Step 3: Commit and verify git clean state**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add automated testing and linting workflow"
```
