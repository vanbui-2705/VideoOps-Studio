# Module 11 Operations: Operator UI and Submission

Module 11 connects the four-tab Gradio interface to the application layer. Story and Remix forms now submit durable jobs, display the returned job ID, and refresh status without performing hidden mutations. Review and recovery actions use revision-aware commands.

## Operator flow

1. Select an active, enabled channel profile.
2. Submit an AI Story script/prompt or ordered Remix rows.
3. Keep the returned job ID; worker progress continues independently of the browser request.
4. Open **Review & Publish**, refresh the job, edit metadata or regenerate, then approve a frozen revision and target list.
5. For known failures, retry/reconcile or explicitly skip a target with a reason. Cancellation schedules verified purge.

Submission request IDs remain stable while a form submission is retried, so a browser retry cannot create duplicate jobs. After a successful submission, the handler rotates to a new request ID.

## UI boundaries

- The UI calls `JobSubmissionService`, `ReviewService`, and `ChannelCatalog`; it does not access SQLAlchemy, provider tokens, or filesystem internals.
- Refresh is read-only.
- Preview and manual-master paths are exposed only after manifest size/checksum and revision validation.
- Raw backend exceptions are converted to safe operator messages.
- Channel forms accept credential reference names only; they never display or persist secret values.

## Run

```powershell
$env:DATABASE_URL = "postgresql+psycopg://videoops:change-me@localhost:5432/videoops"
python -m alembic upgrade head
python app.py
```

Run the story, remix, media, publish, purge, and retention processes separately or use Docker Compose as described in [Module 13 deployment](MODULE_13_DEPLOYMENT.md).

## Verification

```powershell
python -m pytest tests/test_ui.py tests/unit/application/test_submission_service.py tests/unit/application/test_review_service.py -q
```
