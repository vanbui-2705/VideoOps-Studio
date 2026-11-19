# Module 5 Operations: AI Story

Module 5 consumes durable `PREPARE_STORY` work. A supplied script is transformed locally and never calls an LLM. A prompt uses the frozen Channel Profile revision and native Gemini or OpenAI structured output.

## Migration

```powershell
$env:DATABASE_URL = "postgresql+psycopg://..."
.venv\Scripts\python.exe -m alembic upgrade head
```

Revision `20261117_0003` adds `story_generations`, keyed by job and content revision. It stores only the validated story, hashes, provenance and usage metadata—not the full prompt, API key or raw provider response.

Rollback is `.venv\Scripts\python.exe -m alembic downgrade 20261116_0002`. This removes the generation cache, so stop the story worker before rolling back.

## Provider configuration

The safe default is `LLM_PROVIDER=disabled`. User-supplied scripts still work in this mode; prompt-only jobs fail with a safe configuration error.

Gemini:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=<approved-gemini-model-id>
GEMINI_API_KEY=<secret>
```

OpenAI:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=<approved-openai-model-id>
OPENAI_API_KEY=<secret>
```

Only `disabled`, `gemini`, and `openai` are accepted. There is no arbitrary base URL, consumer web-cookie connector, or tool execution. Keep keys in deployment secrets; never put them in Channel Profiles or the database.

Policy knobs are documented in `.env.example`: timeout, output token ceiling, temperature, retry attempts, prompt version, narration bounds, scene count, and keywords per scene. Increment `LLM_PROMPT_VERSION` when the prompt contract intentionally changes.

## Run the worker

Apply migrations, configure `DATABASE_URL`, then run:

```powershell
.venv\Scripts\python.exe run_story_worker.py
```

This process leases only `PREPARE_STORY`. It cannot consume render or publish work. Provider retries are bounded in `StoryScriptService`; SDK retries are disabled so one layer owns retry behavior.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/unit -q
$env:TEST_DATABASE_URL = "postgresql+psycopg://videoops:videoops_test@localhost:55432/videoops_test"
.venv\Scripts\python.exe -m pytest tests/integration/postgres -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
```

Automated tests use fake provider clients and make no billable API calls. A live provider smoke test is intentionally manual and should use a disposable prompt, restricted key, low output limit, and non-production account.

## Failure and recovery

- Authentication, permission, refusal, truncation, malformed output, timeout, and rate-limit failures become sanitized workflow failures.
- Retryable provider failures are retried within the configured bound while the work lease is heartbeated.
- The validated result is cached before workflow commit. If commit is retried, the provider is not called again.
- Regeneration increments `content_revision`, clears `prepared_story`, and creates a distinct cache key.
- A request-hash mismatch at the same content revision is rejected as a conflict instead of silently reusing different inputs.

Module 5 stops at a validated `ScriptDraft` and `RENDER_PREVIEW` intent. TTS, stock retrieval, FFmpeg rendering, publishing and live deployment are later modules.
