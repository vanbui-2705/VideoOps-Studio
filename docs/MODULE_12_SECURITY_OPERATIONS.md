# Module 12 Operations: Security, Audit, and Observability

Module 12 adds fail-closed application authentication for non-local deployments, default-deny role authorization at application-service boundaries, searchable append-only audit records, redacted structured logging, and bounded health/metrics primitives.

## Deployment modes

- `local`: no Gradio login; use only on a trusted loopback workstation.
- `private`: login required.
- `public`: login required; place TLS and network controls in front of the application.

Both non-local modes require `APP_AUTH_USERNAME` and an `APP_AUTH_PASSWORD` of at least 12 characters. Startup fails when these are absent. `TRUST_PROXY_AUTH=true` is rejected because trusted-header authentication is not implemented.

```text
DEPLOYMENT_MODE=private
APP_AUTH_USERNAME=operator
APP_AUTH_PASSWORD=<secret from deployment environment>
APP_AUTH_ROLES=OPERATOR,REVIEWER
TRUST_PROXY_AUTH=false
```

Do not commit passwords, OAuth tokens, refresh tokens, cookies, or database credentials. Basic application authentication must be transported over HTTPS outside local mode.

## Roles

| Role | Allowed capabilities |
| --- | --- |
| `OPERATOR` | Submit, read, cancel |
| `REVIEWER` | Read, edit/regenerate, approve, recover publishing |
| `ADMIN` | Read, manage channel profiles, query audit |

Roles are additive and all unspecified actions are denied. Sensitive review commands carry the authenticated principal ID into the workflow audit row. Purge snapshots are attributed to the system and contain only safe metadata and provider receipts.

## Audit and logs

`AuditQueryService` requires `ADMIN` and bounds pages to 100 records. Queries can filter by job, actor type/ID, action, channel, platform, and time range. Audit storage must not contain raw credentials or provider payloads.

`SecretRedactionFilter` masks bearer headers, common secret/password/token fields, cookies, and passwords embedded in database URLs. Logging a secret is still a defect; redaction is defense in depth.

Health checks are explicitly registered local checks. Metric labels are restricted to bounded values (`phase`, `platform`, `kind`, `result`); job IDs and other high-cardinality labels are rejected.

## Incident checklist

1. Disable the affected provider credential in the deployment secret store.
2. Rotate the credential and database/application password if exposure is possible.
3. Query audit by actor, job, action, and time window.
4. Reconcile `UNKNOWN` publish targets before retrying or purging media.
5. Preserve PostgreSQL audit records; do not copy logs containing suspected secrets into tickets without review.

## Verification

```powershell
python -m pytest tests/unit/application/test_security.py tests/unit/application/test_audit_query.py tests/unit/runtime/test_log_redaction.py tests/unit/runtime/test_health_metrics.py tests/test_ui.py -q
```
