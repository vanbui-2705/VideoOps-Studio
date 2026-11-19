# Module 5: AI Story and Native LLM Providers

**Goal:** Turn `PREPARE_STORY` work into a validated, durable `ScriptDraft`, bypassing providers for user scripts and using native Gemini/OpenAI structured output for prompts.

## Public seams

- `LlmProvider`: normalized async structured generation.
- `StoryScriptService`: deterministic script branch and bounded-retry prompt branch.
- `StoryGenerationStore`: durable result reuse by job/content revision/request hash.
- `StoryPreparationHandler`: obsolete-work detection, cache use, and typed workflow events.
- `WorkflowProcessor`: atomic `StoryPrepared` persistence plus `RENDER_PREVIEW` scheduling.
- `Worker`/`WorkQueue`: awaitable/no-op handlers and supported-kind claims.

## Acceptance map

- [x] Story domain values enforce size, scene, keyword, and provenance invariants.
- [x] User scripts make zero provider calls; prompts use the historical channel revision.
- [x] Gemini and OpenAI adapters normalize structured output and redact SDK errors.
- [x] Retry is bounded, deterministic in tests, and owned by the story service.
- [x] Migration `20261117_0003` and generation cache prevent repeat calls after commit retry.
- [x] `StoryPrepared` persists the draft and atomically schedules preview work.
- [x] Story workers claim only `PREPARE_STORY`; async and obsolete no-op paths are safe.
- [x] Full tests, Ruff, Alembic, architecture, and secret scans pass without live API calls.

## Ordered slices

1. Story domain models and serialization.
2. Provider-neutral contracts, error policy, and script/prompt service.
3. Native Gemini/OpenAI adapters behind fake-client contract tests.
4. Workflow event/aggregate changes and regeneration behavior.
5. PostgreSQL generation cache and migration.
6. Queue filtering, async worker support, and story handler.
7. Composition, integration journeys, operations docs, and broad verification.

## Decisions

- `LLM_PROVIDER=disabled` is the safe default; deployments opt into Gemini or OpenAI and provide an explicit model ID.
- The service owns provider retry; SDK retries are disabled where supported.
- Full prompts and raw SDK responses are ephemeral. Persistence keeps hashes, validated content, provenance, and usage only.
- A provider response is cached before workflow commit, so a later commit retry reuses content.
- No consumer web sessions, arbitrary endpoints, tools, publishing, or media generation are in scope.
