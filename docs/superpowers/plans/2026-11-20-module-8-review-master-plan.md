# Module 8: Review Gate and Master Rendering

**Goal:** Let an operator review a durable preview, freeze one approved content/metadata revision, render a validated 1080p master from original revision artifacts, and enter `PUBLISHING` without performing any platform upload.

## Public seams

- `VideoWorkflow.command`: revision-safe metadata, regenerate, and approve commands.
- `MasterRenderService.render`: one deep interface that validates approval/source artifacts, selects Story or Remix composition, and returns one durable master manifest.
- `MasterRenderer`: infrastructure-neutral master composition port implemented by the FFmpeg adapter.
- `MasterRenderHandler`: stale-work filtering and sanitized workflow events.
- `ReviewService`: UI-facing read/command facade that resolves only validated preview artifacts.

## Ordered vertical slices

- [x] Strengthen master event/revision invariants at the workflow seam.
- [x] Render and reuse Story masters from original voice/subtitle/visual artifacts.
- [x] Render and reuse Remix masters from downloaded source artifacts.
- [x] Add 1080p FFmpeg adapter, output validation, and local smoke coverage.
- [x] Add master handler and a serialized preview/master media worker.
- [x] Wire the Review Gate UI through a testable application facade.
- [x] Add PostgreSQL journey, operations docs, and broad verification.

## Acceptance map

- [x] Approval remains idempotent and freezes metadata, targets, content revision, and channel revision.
- [x] Review refresh is read-only; available targets and preview belong to the current revision.
- [x] Story master uses original voice/subtitle/visual artifacts, never the 480p preview.
- [x] Remix master uses retained downloads and frozen transforms, never preview/480p normalized clips.
- [x] Landscape output is 1920x1080; portrait output is 1080x1920.
- [x] Master is H.264/AAC, 30 fps, `yuv420p`, `superfast`, CRF 23, `+faststart`, with at most two threads.
- [x] Output is probed before atomic promotion and invalid partial files are removed.
- [x] Valid master manifests are reused; missing/corrupt masters are rebuilt.
- [x] Stale work has no media side effects; expected failures persist sanitized `MASTER_RENDER` failures with `ResumeAction.MASTER`.
- [x] Preview and master share one serialized render worker lane when concurrency is one.
- [x] Master success persists one MASTER ref, enters `PUBLISHING`, and creates one intent per pending target.
- [x] No publisher or purge side effect is introduced.
- [x] Unit, UI, FFmpeg smoke, PostgreSQL integration, Ruff, formatting, compile, Alembic, and diff checks pass.

## Scope boundary

Module 8 owns review commands, validated preview resolution, and master production. `PUBLISH_TARGET` work is durable output for Module 9 and remains unconsumed. Cancellation remains disabled in the UI until Module 10 can execute `PURGE_JOB`. Media is retained for later publishing/recovery.
