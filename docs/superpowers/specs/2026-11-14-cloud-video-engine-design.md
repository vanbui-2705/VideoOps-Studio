# Design Document: Cloud Video Auto-Creation & Push Engine

**Date:** 2026-11-14  
**Status:** In Review  
**Target Platform:** Hugging Face Spaces (Gradio Web UI) + Cloud Compute  

---

## 1. Intent & The Why
Provide a zero-cost, cloud-hosted automated video production pipeline that eliminates local machine resource consumption (CPU/GPU/bandwidth). The system ingests external assets directly to the cloud, creates long-form or short-form videos through two primary pipelines (AI Story/News & Remix/Compilation), provides a web review gate for manual approval, and automatically pushes approved videos to YouTube and TikTok.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals

- **Zero Local Footprint:** Video downloading, text-to-speech, asset fetching, rendering, and uploading run 100% on free cloud infrastructure (Hugging Face Spaces).
- **Dual Pipeline:**
  1. *AI Story/News Pipeline:* Text/topic -> Edge-TTS (Vietnamese/English) -> Stock video/image asset retrieval (Pexels/Pixabay) -> Auto subtitles (SRT) -> Video composite.
  2. *Remix/Curated Pipeline:* Remote video URLs (YouTube, TikTok, Facebook, etc.) -> Direct cloud download (`yt-dlp`) -> Clip extraction, audio adjustment, visual transformation -> Concatenation.
- **Review Gate:** Rendered video must be previewable in a web UI player before any public publishing occurs. Single-click approve/reject.
- **Multi-Platform Push:** Automated upload to YouTube (YouTube Data API v3) and TikTok (API/uploader) with customizable titles, descriptions, and tags.
- **Extensible Architecture:** Decoupled core engine enabling seamless integration with Telegram Bot or other webhook triggers in future phases.

### Non-Goals

- Full multi-track timeline video editor in the browser (this is an automated/templated pipeline, not Adobe Premiere / CapCut Web clone).
- Training custom AI video generation models locally.
- Paid cloud GPU usage (must remain operational within free tier limits).

### Anti-Goals

- Burning local PC resources for rendering or video transfers.
- Publishing unapproved videos automatically without human verification gate.
- Storing permanent video libraries on the cloud host (temporary storage only; videos cleaned up after publish/expiry to preserve free tier disk quota).

---

## 3. Constraints

- **Host Compute:** Hugging Face Spaces free tier (2 vCPU, 16 GB RAM, 50 GB temporary disk).
- **Execution Limits:** Video encoding must use optimized CPU FFmpeg presets (`ultrafast` / `superfast` for previews, `fast` for final output) to avoid CPU timeouts on long videos.
- **External Dependencies:** Free APIs and open-source libraries:
  - `edge-tts` (Microsoft Edge Text-to-Speech, free, unlimited, high-quality Vietnamese/multilingual voices).
  - `yt-dlp` for media ingestion.
  - Pexels / Pixabay free API keys for stock footage.
  - YouTube Data API v3 (free 10,000 daily quota units, ~6 video uploads/day).
  - TikTok upload mechanism.

---

## 4. Approaches Considered

1. **Approach A: Hugging Face Spaces + Gradio (Selected)**
   - *Architecture:* Self-contained Python container running 24/7. Gradio UI front-end + FFmpeg/yt-dlp backend.
   - *Pros:* 100% free, 24/7 live web URL accessible from phone and PC, built-in video player and approval flows, clean Python integration, easily connects to Telegram bot later.
   - *Cons:* CPU-only encoding (slower for 4K or ultra-long videos; mitigated by 1080p/720p presets).

2. **Approach B: Google Colab / Kaggle (Rejected)**
   - *Pros:* Free GPU (T4).
   - *Cons:* Ephemeral sessions (shuts down after inactivity), requires manual execution of notebook cells, poor UX for automated on-demand usage.

3. **Approach C: Vercel Web + GitHub Actions (Rejected)**
   - *Pros:* High CPU runner per build.
   - *Cons:* Complex two-way webhook coordination, GitHub Actions 2000 min/month quota limit, harder to inspect intermediate rendering progress.

---

## 5. Architectural Specifications

```text
+--------------------------------------------------------------------------+
|                        Gradio Web Interface (HF Space)                   |
|  [Tab 1: AI Story Video]    [Tab 2: Video Remix/Downloader]              |
|  [Tab 3: Review & Publish]  [Tab 4: Settings & API Keys]                 |
+-----------------------------------+--------------------------------------+
                                    |
                                    v
+--------------------------------------------------------------------------+
|                           Core Pipeline Engine                           |
|                                                                          |
|  +---------------------+  +---------------------+  +------------------+  |
|  | Module 1: Ingest    |  | Module 2: Edit/Mix  |  | Module 3: Review |  |
|  | - edge-tts          |  | - FFmpeg core       |  | - Web player     |  |
|  | - Pexels/Pixabay    |  | - Audio overlay/BGM |  | - Meta editor    |  |
|  | - yt-dlp downloader |  | - Subtitle burning  |  | - Approve / Edit |  |
|  +---------------------+  +---------------------+  +------------------+  |
+-----------------------------------+--------------------------------------+
                                    | (When Approved)
                                    v
+--------------------------------------------------------------------------+
|                        Module 4: Auto-Publish Engine                     |
|  - YouTube Data API v3 uploader                                          |
|  - TikTok uploader / webhook publisher                                   |
+--------------------------------------------------------------------------+
```

### Module 1: Asset Ingestion & Generation

- **Sub-module 1A (AI Story Creator):**
  - Inputs: Text script or prompt, voice selection (`vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`, `en-US-...`), visual keyword tags, orientation (16:9 horizontal vs 9:16 vertical).
  - Actions:
    1. Synthesizes voiceover via `edge-tts`, extracting timestamped word boundaries / SRT subtitles.
    2. Queries Pexels/Pixabay API using keywords, downloads matching stock video clips / high-res images directly into temporary workspace.
- **Sub-module 1B (Remix & Media Grabber):**
  - Inputs: List of source URLs, start/end timestamps per clip, playback speed multiplier, aspect ratio crop.
  - Actions:
    1. Direct-downloads source streams via `yt-dlp` at target resolution.
    2. Applies transform parameters (crop, scale, mirror flip for copyright masking if requested).

### Module 2: Editing & Composition Engine (FFmpeg)

- Standardized profiles:
  - Landscape: 1920x1080 @ 30fps, H.264 / AAC.
  - Portrait: 1080x1920 @ 30fps, H.264 / AAC.
- Steps:
  1. Concat/crossfade visual clips to match total audio duration.
  2. Mix voiceover audio track with optional background music (ducking BGM volume to -18dB when voice speaks).
  3. Burn subtitles into video frame using FFmpeg `subtitles` filter with custom font styling (yellow/white with black outline).
  4. Output intermediate master file into `outputs/` directory.

### Module 3: Review Gate (Gradio UI)

- Generates web-streamable MP4 preview.
- Displays preview in Gradio Video player component.
- Editable form fields: Video Title, Description, Tags, Category, Privacy status (Public, Unlisted, Private).
- Action buttons:
  - **[Approve & Publish]**: Enqueues upload task to Module 4.
  - **[Regenerate]**: Adjust settings and re-render.
  - **[Discard]**: Deletes temporary output files.

### Module 4: Multi-Platform Uploader & Zero-Retention Purge

- **YouTube:**
  - Uses `google-api-python-client` with OAuth2.
  - Setup flow: User generates `token.json` once locally or pastes OAuth credentials via Gradio Settings tab into HF Space persistent Secrets.
  - Resumable file upload chunks with retry logic and metadata setting.
- **TikTok:**
  - Dual support:
    1. Session cookie authentication (`cookies.txt` or session id input in Settings) for instant upload without needing TikTok Developer verification.
    2. Direct video download button as fail-safe if TikTok session expires.
- **Zero-Retention Purge:**
  - On HTTP 200 upload confirmation: master MP4, temporary video clips, audio tracks, and SRT files are immediately deleted from disk.
  - Only persistent record kept is a lightweight audit row (channel, title, URL, timestamp).
- Status logger displayed in Web UI with direct link to published video.

---

## 6. Resolved Builder Questions (Architect Decisions)

1. **Multi-Channel Management:** Supports unlimited channels via `channels/<channel_id>.json`. Each profile stores its own prompt format/tone, voice selection, BGM style, subtitle style, aspect ratio (16:9 vs 9:16), and tied YouTube/TikTok credentials.
2. **Script Input for AI Story:** Supports both:
   - Paste ready-made script text directly (default, fastest).
   - Optional LLM generation prompt (uses free Gemini/Groq API key if provided in settings). Prompt automatically formatted with the active channel's persona.
3. **Stock Video Fallback:** Uses Pexels free API. If API key missing, falls back to solid background / Ken Burns zoom on free Unsplash images.
4. **Storage & Cleanup:** Zero-retention policy on successful publish; automated 6-hour purge for any abandoned drafts.

---

## 7. Project Structure

```text
NewVideo_Push/
├── app.py                   # Main Gradio application entry point
├── requirements.txt         # Python dependencies
├── packages.txt             # System dependencies for HF Space (ffmpeg, fonts)
├── README.md                # HF Space metadata and usage guide
├── config.py                # Environment variables, API keys, paths
├── channels/                # Multi-channel profiles (JSON/YAML)
│   ├── tech_news.json
│   └── story_lofi.json
├── core/
│   ├── __init__.py
│   ├── channel_manager.py   # Multi-channel profile & prompt formatter
│   ├── pipeline.py          # Orchestrator & state machine
│   ├── tts_engine.py        # edge-tts wrapper & SRT generator
│   ├── stock_fetcher.py     # Pexels / Pixabay downloader
│   ├── downloader.py        # yt-dlp remote URL downloader
│   ├── ffmpeg_builder.py    # FFmpeg commands and composite pipeline
│   ├── state_manager.py     # Task state, zero-retention cleanup
│   └── uploader/
│       ├── __init__.py
│       ├── youtube.py       # YouTube Data API v3 uploader
│       └── tiktok.py        # TikTok uploader
└── assets/
    ├── bgm/                 # Royalty-free background music tracks
    └── fonts/               # Subtitle fonts (BeVietnamPro, Montserrat)
```

---

## 8. What is Left to the Builder

- Detailed FFmpeg filtergraph construction for smart crop and subtitle styling.
- Pexels/Pixabay API keyword auto-extraction logic from text script.
- Gradio UI layout aesthetics and tab arrangement.
- Token refresh persistence mechanism for YouTube OAuth on Hugging Face Spaces.
