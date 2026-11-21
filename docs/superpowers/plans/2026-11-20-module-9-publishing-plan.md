# Module 9: Idempotent Multi-Platform Publishing

**Goal:** Publish the frozen approved master independently to YouTube and TikTok, preserve one logical publication per job/platform, and reconcile ambiguous outcomes without consuming Module 10 purge work.

## Confirmed interfaces

- `PublishCoordinator.execute(work, heartbeat)`: deep application interface for validation, start-before-I/O ordering, adapter selection, attempt persistence, and typed workflow outcomes.
- `Publisher.publish/reconcile`: provider-neutral seam with YouTube, TikTok, and fake adapters.
- `PublishAttemptStore`: durable logical-operation/checkpoint seam.
- `Worker`: accepts deferred handler results so asynchronous provider processing can safely retry the same leased item later.

## Vertical slices

- [x] Publish contracts and deterministic logical idempotency.
- [x] Durable publish attempt persistence and migration.
- [x] Coordinator validation, start-before-I/O, success/failure/unknown/deferred behavior.
- [x] YouTube resumable adapter.
- [x] TikTok official Content Posting adapter and manual fallback metadata.
- [x] Publish worker composition, configuration, and official credentials.
- [x] Per-target UI status/actions and operations documentation.
- [x] PostgreSQL journeys and broad verification.

## Acceptance map

- [x] Stale, corrupt, already-successful, or unapproved work performs no provider call.
- [x] Frozen metadata/channel revision and contained current master are the only publish inputs.
- [x] Started state and logical attempt exist before provider I/O.
- [x] Success receipts are durable before aggregate success; retries never duplicate success.
- [x] `UNKNOWN` and interrupted `UPLOADING` reconcile before publish.
- [x] YouTube uses bounded resumable chunks/backoff and returns a confirmed ID.
- [x] TikTok uses the official API, persists only safe `publish_id`, and defers processing.
- [x] No token, signed URL, cookie, raw response, or absolute path is persisted/logged.
- [x] Partial success retains master; all terminal targets enqueue but do not consume `PURGE_JOB`.
- [x] UI refresh is read-only and displays per-target results.
- [x] Unit, adapter, UI, PostgreSQL, Ruff, format, compile, Alembic, and diff checks pass.

## Scope boundary

No live upload occurs in tests. Module 9 never deletes media and does not implement a `PURGE_JOB` handler. TikTok cookie/browser automation is explicitly excluded.
