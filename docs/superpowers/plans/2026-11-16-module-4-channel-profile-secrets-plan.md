# Module 4: Channel Profiles and Secret Resolver

**Goal:** Persist safe channel presets, expose them through `ChannelCatalog`/`ChannelReader`, and derive platform availability from read-only environment credential bundles without exposing secret values.

## Public seams

- `ChannelCatalog`: list/get/save safe profile views and enforce the administration gate.
- `ChannelReader`: provide Module 2 with immutable `ChannelSnapshot` values.
- `SecretResolver`: report safe availability and resolve internal credential values.
- `ChannelRepository`: persist profiles with optimistic concurrency and append-only revisions.
- UI channel handlers: translate catalog behavior into browser-safe values.

## Acceptance map

- [x] Typed profile values validate identifiers, templates, rendering, audio, metadata, and credential references.
- [x] Environment secrets are read-only, redacted, and only complete bundles enable a platform.
- [x] Alembic revision `20261116_0002` adds current profiles and append-only revision history.
- [x] PostgreSQL repository proves round-trip, stale/concurrent update rejection, transactionality, and safe audit data.
- [x] `DefaultChannelCatalog` implements the existing `ChannelReader` contract without changing `VideoWorkflow`.
- [x] Gradio lists/loads/saves profiles safely, remains import-safe without a database, and enforces read-only mode.
- [x] Full tests, Ruff, Alembic check, architecture boundaries, and secret-marker checks pass.

## Ordered implementation

1. Domain models and validation with unit tests.
2. Environment secret resolver and redaction tests.
3. Catalog application service, safe views, admin policy, and ChannelReader tests.
4. PostgreSQL schema/migration/repository with real concurrent integration tests.
5. UI handlers and dependency composition, retaining preview-mode startup.
6. Full verification and operations handoff.

## Decisions

- Credential references are uppercase environment prefixes; secret values never enter profile models or PostgreSQL.
- Environment resolution is read-only. This module does not write `.env` or cloud secret stores.
- Editing is disabled by default with `CHANNEL_ADMIN_ENABLED=false`; this flag is an operational gate, not authentication.
- Existing jobs keep their channel revision snapshot, so `jobs.channel_id` is not retrofitted with a foreign key.
- Production migration, authentication, OAuth, and publishing remain outside this module.
