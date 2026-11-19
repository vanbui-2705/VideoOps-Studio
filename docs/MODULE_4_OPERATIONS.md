# Module 4 Operations

Channel Profiles are stored in PostgreSQL. Their credential fields are uppercase references only; provider values remain in the deployment environment or secret manager.

## Migration

```powershell
$env:DATABASE_URL = "postgresql+psycopg://..."
.venv\Scripts\python.exe -m alembic upgrade head
```

Revision `20261116_0002` creates `channel_profiles` and append-only `channel_profile_revisions`. Existing jobs intentionally retain a plain `channel_id` and their captured channel revision.

## Credential bundles

For `youtube_secret_ref=YT_TECH`, configure:

- `YT_TECH_YOUTUBE_CLIENT_ID`
- `YT_TECH_YOUTUBE_CLIENT_SECRET`
- `YT_TECH_YOUTUBE_REFRESH_TOKEN`

For `tiktok_secret_ref=TT_TECH`, configure:

- `TT_TECH_TIKTOK_SESSION`

The resolver is read-only. Values are never stored in profile JSON, audit entries, Gradio state, or logs. The UI reports only configured/missing status.

## Administration gate

`CHANNEL_ADMIN_ENABLED=false` is the safe default. Set it to `true` only for a trusted/private deployment with access control in front of Gradio. This flag enables mutations but is not authentication.

Module 4 does not implement OAuth callbacks, cloud secret writes, user accounts, or publishing. Those remain deployment/auth and Module 9 responsibilities.
