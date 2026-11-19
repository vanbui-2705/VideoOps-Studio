# Module 6: Story Media Preparation and Preview Rendering

**Goal:** Consume `RENDER_PREVIEW` work for a prepared story, synthesize voice/subtitles, resolve stock or deterministic fallback visuals, render a validated 480p preview, persist complete artifact manifests, and enter `AWAITING_REVIEW`.

## Public seams

- `JobWorkspace`: contained, revision-scoped file creation and atomic promotion.
- `TtsProvider`: narration to timed voice/subtitle data.
- `StockMediaProvider`: scene keywords to a bounded downloadable candidate.
- `MediaProbe`: safe metadata validation for generated/downloaded media.
- `PreviewRenderer`: prepared media to browser-playable preview.
- `ArtifactManifestStore`: durable relative artifact metadata and reuse checks.
- `PreviewPreparationService`: idempotent orchestration across media adapters.
- `PreviewRenderHandler`: stale-work filtering and typed workflow events.

## Acceptance map

- [x] Media values enforce timing, relative path, checksum, ordering, and revision invariants.
- [x] Workspace rejects traversal/symlink escape and promotes `.part` files atomically.
- [x] Edge TTS adapter is behind a fake-testable port and emits valid UTF-8 SRT.
- [x] Pexels/Pixabay HTTP adapters enforce timeout, content type, size, and provenance.
- [x] Local generated background keeps preview generation available without stock keys/network.
- [x] FFmpeg renderer produces validated 480p H.264/AAC, `yuv420p`, `+faststart` previews with at most two threads.
- [x] Artifact manifests survive workflow commits without losing URI/checksum/metadata.
- [x] Retry reuses valid artifacts and content revisions remain isolated.
- [x] Preview worker claims only `RENDER_PREVIEW` and reaches `AWAITING_REVIEW` only after probe succeeds.
- [x] Unit, PostgreSQL integration, FFmpeg smoke, Ruff, Alembic, and security gates pass.

## Ordered vertical slices

1. Media domain values and safe workspace.
2. Subtitle serialization and TTS port/Edge adapter.
3. Stock candidates, bounded downloader, and generated fallback.
4. Media probe and FFmpeg preview renderer.
5. Artifact manifest repository and workflow preservation.
6. Preview service, event, handler, worker composition, and end-to-end journey.
7. Operations docs and broad verification.

## Scope boundary

Module 6 creates preview artifacts only. Remix ingestion, master rendering, publishing, and final purge remain later modules. Automated tests use fake TTS/HTTP providers; live network calls are excluded.
