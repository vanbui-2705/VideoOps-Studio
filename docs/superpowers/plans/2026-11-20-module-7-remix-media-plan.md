# Module 7: Remix Ingestion and Preview Rendering

**Goal:** Consume `PREPARE_REMIX` work, download and validate ordered public media sources, normalize requested clip ranges, render a validated 480p preview, persist revision-safe artifact manifests, and enter `AWAITING_REVIEW`.

## Public seams

- `RemixRequest` and `RemixClip`: validated user intent and copyright confirmation.
- `RemixSourceDownloader`: bounded remote-source ingestion into a contained workspace.
- `RemixClipProcessor`: trim, speed, crop/fit, mirror, audio, and profile normalization.
- `RemixPreviewRenderer`: ordered clip composition and optional channel BGM.
- `RemixMediaService`: idempotent orchestration across download, probe, transform, and render adapters.
- `RemixPreparationHandler`: stale-work filtering for `PREPARE_REMIX`.
- `PreviewRenderHandler`: story/remix dispatch for shared `RENDER_PREVIEW` work.
- `build_remix_worker`: process composition that leases only remix preparation work.

## Acceptance map

- [x] Requests require copyright confirmation, public HTTP(S) URLs, valid time ranges, supported speed/crop values, and contiguous 1-based ordering.
- [x] Remix transform settings survive the immutable request snapshot persistence round trip.
- [x] yt-dlp receives an argument list, disables playlists, limits source resolution/bytes/time, and writes only inside the revision workspace.
- [x] DNS resolution rejects non-public destinations before yt-dlp starts; credentials and raw source URLs are not persisted in artifact metadata.
- [x] Failed and oversized downloads remove partial files.
- [x] Sources are probed before processing; audio-only, over-duration, and out-of-range inputs are rejected.
- [x] FFmpeg normalizes clips to 480p H.264/AAC, 30 fps, `yuv420p`, at most two threads, with fill/fit, speed, mirror, and silent-audio fallback support.
- [x] Preview rendering preserves request order, supports optional contained BGM, emits `+faststart`, and validates duration/profile before promotion.
- [x] Source, normalized, and preview manifests include revision-scoped IDs, relative paths, checksums, byte sizes, media metadata, and sanitized provenance.
- [x] Retry reuses valid artifacts, rebuilds corrupt artifacts, and ignores stale queue work.
- [x] Durable PostgreSQL workers move a remix job through ingestion and preview into `AWAITING_REVIEW`.
- [x] Unit, PostgreSQL integration, local FFmpeg smoke, Ruff, formatting, and Alembic-head checks pass.

## Ordered vertical slices

1. Remix request validation and durable snapshot mapping.
2. Public-source validation and bounded yt-dlp adapter.
3. FFmpeg clip normalization and preview composition.
4. Artifact-safe remix service with idempotent reuse.
5. Workflow events, preparation/preview handlers, and worker composition.
6. PostgreSQL journey, local media smoke, operations docs, and broad verification.

## Scope boundary

Module 7 creates Remix preview artifacts only. It does not render a master, publish to any platform, or purge approved media. The existing Gradio Remix workspace remains a non-submitting shell until the UI is composed with `VideoWorkflow`; that integration is outside this worker slice.
