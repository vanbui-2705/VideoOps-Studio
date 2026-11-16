# CLAUDE.md - Developer & Agent Guidelines

## 1. Project Overview
`NewVideo_Push` is an automated, cloud-hosted video creation and distribution pipeline designed to run 24/7 on free cloud compute (Hugging Face Spaces / Linux CPU container). It ingests text or remote media, renders polished vertical/horizontal videos with FFmpeg, provides a web review gate, and auto-pushes to YouTube and TikTok.

---

## 2. Technical Stack
- **Runtime:** Python 3.10+
- **Web UI:** Gradio >= 4.0
- **Media Engine:** FFmpeg 6.x+ (CLI via `subprocess.run` / `asyncio.create_subprocess_exec`)
- **Speech Synthesis:** `edge-tts` (asynchronous neural TTS with subtitle markers)
- **Downloader:** `yt-dlp`
- **Asset Fetching:** `httpx` (async HTTP client with connection pooling)
- **Publishing:** `google-api-python-client`, `google-auth-oauthlib`

---

## 3. Directory Layout & Boundaries

```text
NewVideo_Push/
├── app.py                  # Gradio entry point (UI components & event binding only)
├── config.py               # Centralized configuration & environment loader
├── ARCHITECTURE.md         # System design and specifications
├── channels/               # Channel Profiles (JSON/YAML: tech, story, facts...)
├── core/                   # Core business logic (FRAMEWORK-AGNOSTIC)
│   ├── channel_manager.py  # Multi-channel profile manager & prompt templating
│   ├── pipeline.py         # Main orchestrator / state machine
│   ├── tts_engine.py       # edge-tts wrapper & SRT generator
│   ├── stock_fetcher.py    # Pexels / Pixabay media fetcher
│   ├── downloader.py       # yt-dlp safe wrapper
│   ├── ffmpeg_builder.py   # FFmpeg command builder & process executor
│   ├── state_manager.py    # Job tracking, idempotency, cleanup routine
│   └── uploader/
│       ├── youtube.py      # Resumable YouTube API v3 uploader
│       └── tiktok.py       # TikTok publisher / cookie session uploader
├── tests/                  # Unit and integration test suites
└── assets/
    ├── bgm/                # Bundled copyright-free audio loops
    └── fonts/              # Bundled open-source fonts (.ttf)
```

**Architecture Invariants:**
1. Code inside `core/` MUST NEVER import `gradio`. Keep the engine 100% headless so it can be called by CLI, Telegram Bot, or Celery workers.
2. The UI (`app.py`) only triggers `core.pipeline.PipelineController` methods and renders returned states.
3. **Zero-Retention Policy:** Immediately after upload confirmation (HTTP 200), master video and intermediate caches MUST be purged from disk. Only lightweight log entries are retained.

---

## 4. Agent Delivery Workflow

Use this closed loop for every implementation task. The lead agent owns the task from intake through verified handoff, even when specialist agents perform individual steps.

### 4.1 Intake and Acceptance Gate
1. Read the user's request, the relevant code and tests, `ARCHITECTURE.md`, and the applicable sections of `docs/TECHNICAL_DESIGN.md`. For work already covered by an active plan, also read that plan under `docs/superpowers/plans/`.
2. Inspect the repository state before editing. Preserve unrelated work and identify whether the requested behavior already exists.
3. Convert the request into observable acceptance criteria, including the expected success path, important failure paths, security/retention constraints, and the required verification level.
4. Resolve contradictions using this precedence: explicit user instruction, approved requirement/ADR, `CLAUDE.md` invariants, active technical design/plan, then current implementation. Surface any unresolved decision that materially changes the result before implementation.

**Gate:** The task has a bounded scope and checkable acceptance criteria. If either is missing, continue discovery or ask one focused question only when a safe assumption would materially change the result.

### 4.2 Task and Plan Gate
1. Break the work into small, dependency-ordered tasks. Track each task as `pending`, `in_progress`, `blocked`, or `completed`; only one implementation task should be `in_progress` at a time.
2. Keep a short plan in the active session for a localized change. Create or update a dated plan in `docs/superpowers/plans/` when the work spans multiple modules, changes architecture or persistence, requires migration/deployment coordination, or is likely to continue across sessions.
3. For every task, name the files or interfaces involved, the proof required, and any rollback or compatibility concern. Map specialist work to the existing agents when useful:

   - `backend-dev`: framework-agnostic pipeline and `core/` changes.
   - `frontend-dev`: Gradio UI and UI-only helpers.
   - `qa-tester`: test design, regression reproduction, and full verification.
   - `code-reviewer`: independent review against the spec and invariants.
   - `git-ci-ops`: CI, scoped commits, and repository operations after checks pass.

4. Keep one lead agent responsible for reconciling all outputs, updating the plan, and deciding whether each gate passed.

**Gate:** Every acceptance criterion maps to at least one implementation task and one verification action.

### 4.3 Baseline Gate
1. Run the narrowest relevant existing checks before editing when practical. Record pre-existing failures separately from failures caused by the task.
2. For a bug fix, reproduce the defect with a failing automated test first. For new behavior, add or identify tests at the public interface or adapter seam before implementation.
3. Confirm that required tools and dependencies are available. Missing external credentials or services should select a mock, fake, local smoke test, or an explicitly reported verification gap; they do not justify a false success claim.

**Gate:** The agent can demonstrate the current behavior and knows which command or observation will prove the change.

### 4.4 Implementation Loop
For each planned task:
1. Mark it `in_progress` and implement the smallest complete vertical slice that changes observable behavior.
2. Preserve the architecture invariants in this file. Update tests and documentation in the same slice when its interface, configuration, state model, or operator behavior changes.
3. Run the focused test or check for that slice immediately.
4. Inspect failures, fix the root cause, and rerun the focused check until it passes. If the solution invalidates the plan, update the plan and acceptance mapping before continuing.
5. Review the touched diff for accidental scope growth, secrets, unsafe paths/subprocesses, missing cleanup, and backward-compatibility issues. Then mark the task `completed`.

**Gate:** A task is completed only when its code, tests, and relevant documentation agree and its focused proof passes.

### 4.5 Verification and Review Gate
After all implementation tasks are complete, verify from narrow to broad:
1. Run focused tests for the changed behavior.
2. Run the full automated suite: `pytest tests/ -v`.
3. Run repository quality gates that are configured and available: `ruff check .`, `ruff format --check .`, and the single configured type checker. Do not introduce a second type checker just to satisfy this step.
4. Run an integration or local smoke test for the changed user journey. Mock external APIs in automated tests; use real services only when the task authorizes them and safe test credentials are available.
5. Review the final change against every acceptance criterion and applicable invariant. Trace failure, retry, idempotency, and cleanup paths for workflow changes.
6. Treat any failing required check, unaddressed review finding, or unexplained regression as a loop back to implementation, followed by the relevant focused and broad checks again.

For a documentation-only task, validate the changed instructions, references, and examples; run code gates only when the documentation changes executable commands, configuration, generated output, or runtime expectations.

**Gate:** All required checks pass, or each unavailable check is explicitly identified with its reason, risk, and the exact command/manual action needed to close it.

### 4.6 Deploy and Runtime Verification Gate
Deployment is an explicit authorization boundary:
1. If deployment was not requested, make no remote change. For a runtime-affecting task, stop at **deploy-ready** and provide the applicable commands, configuration, migration steps, and rollback notes; for a non-runtime task, mark deployment not applicable.
2. If deployment was requested, verify the target environment, identity/project, branch or artifact, secrets/configuration, migration compatibility, resource limits, and rollback path before making changes.
3. Prefer staging or preview deployment first. Run health checks and one safe end-to-end smoke path, while confirming logs contain no secrets and disk/cleanup behavior remains bounded.
4. Promote to production only within the requested scope. Record the deployed revision/artifact and configuration changes without exposing secret values.
5. If health or smoke checks fail, collect sanitized diagnostics and execute the prepared rollback when it is safe and authorized. Return to the implementation loop; redeploy only after the failed gate is proven fixed.

**Gate:** The requested environment is healthy on the intended revision and the critical smoke path passes. A successful build or upload alone is not a successful deployment.

### 4.7 Completion and Handoff Gate
Finish with a concise evidence-based handoff containing:
- what changed and which acceptance criteria it satisfies;
- files/interfaces affected;
- tests, quality checks, and smoke checks actually run with their results;
- deployment status: not requested, deploy-ready, deployed, or rolled back;
- remaining risks, external verification gaps, and follow-up tasks.

Never mark the overall task complete while a required task is `pending`, `in_progress`, or silently blocked. "Done" means implemented, verified, reviewed, and—only when requested—deployed and smoke-tested.

**Gate:** The handoff contains enough evidence for another developer to reproduce the verification and continue any explicitly listed follow-up without rediscovering the task.

---

## 5. Engineering Standards & Best Practices

### 5.1 Strict Typing & Data Models
- Use Python standard `dataclasses` or `pydantic.BaseModel` for all inter-module data transfer.
- All function signatures must have full type hints (`def execute(job: VideoJob) -> JobResult:`).
- Run `mypy` or `pyright` without type errors.

### 5.2 Security & Process Safety
- **NEVER use `shell=True`** in `subprocess` calls. Always use argument lists (`['ffmpeg', '-i', ...]`) to prevent command injection.
- Validate and sanitize all external URLs and user inputs before passing to `yt-dlp` or file systems.
- Never write credentials, tokens, or cookies to persistent log files or console stdout.

### 5.3 Resource & Ephemeral Disk Conservation
- Target environment has **2 vCPU** and **50 GB shared disk**.
- Always set FFmpeg concurrency: `-threads 2`.
- Prefer presets: `superfast` (crf 23) for production, `ultrafast` for draft previews.
- Enforce cleanup: invoke `state_manager.cleanup_job(job_id)` on completion or failure.
- Auto-purge: Delete downloaded chunks immediately after chunk composition. Delete rendered master video immediately after successful YouTube/TikTok upload.

### 5.4 Error Handling & Resilience
- External network requests (Pexels, YouTube, TikTok) must have explicit timeouts (`timeout=30.0`) and exponential backoff retry logic.
- Wrap all FFmpeg subprocess executions in an exception handler that captures `stderr` output for fast debugging.

---

## 6. Development & Testing Commands

### Setup Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run Application Locally
```bash
python app.py
```

### Run Tests
```bash
# Run unit tests (with external calls mocked)
pytest tests/ -v

# Run fast sanity check on FFmpeg command builders
pytest tests/test_ffmpeg_builder.py -v
```

### Code Quality & Linting
```bash
ruff check .
ruff format .
mypy core/
```

---

## 7. Commit Conventions
Follow Conventional Commits:
- `feat(tts): add subtitle timestamp alignment via edge-tts`
- `fix(ffmpeg): resolve audio ducking filtergraph crash on mono BGM`
- `perf(render): use ultrafast preset for web preview pass`
- `docs: update deployment guidelines for Hugging Face Spaces`
