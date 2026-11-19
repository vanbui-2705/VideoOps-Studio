from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.adapters.persistence.channel_repository import PostgresChannelRepository
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.adapters.secrets.environment import EnvironmentSecretResolver
from core.application.channel_catalog import DefaultChannelCatalog, SaveChannelRequest
from core.application.requests import StoryRequest
from core.application.video_workflow import DefaultVideoWorkflow
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    MetadataDefaults,
    VisualPreset,
)
from core.domain.errors import (
    ChannelAlreadyExists,
    ChannelRevisionConflict,
)
from core.domain.models import Platform, VideoMetadata


def _draft(name: str = "Tech Việt Nam") -> ChannelDraft:
    return ChannelDraft(
        "tech_vn",
        name,
        "technology",
        "vi-VN",
        ContentPreset("persona", "informative", "Write about {input}"),
        VisualPreset("16:9", stock_keywords=("AI", "chips")),
        AudioPreset("vi-VN-NamMinhNeural", bgm_ref="tech-calm"),
        MetadataDefaults(hashtags=("AI", "Tech")),
        CredentialReferences("YT_TECH", "TT_TECH"),
    )


def test_profile_round_trip_and_optimistic_update(postgres_engine) -> None:
    repository = PostgresChannelRepository(postgres_engine)
    created_at = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    updated_at = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)

    created = repository.save(_draft(), None, created_at)
    updated = repository.save(_draft("Tech VN Updated"), 1, updated_at)

    assert created.revision == 1
    assert updated.revision == 2
    assert repository.get("tech_vn") == updated
    assert repository.list() == (updated,)
    with postgres_engine.connect() as connection:
        history_count = connection.scalar(
            text(
                "SELECT count(*) FROM channel_profile_revisions "
                "WHERE channel_id = 'tech_vn'"
            )
        )
    assert history_count == 2
    with pytest.raises(ChannelRevisionConflict):
        repository.save(_draft("Stale"), 1, updated_at)
    with pytest.raises(ChannelAlreadyExists):
        repository.save(_draft(), None, updated_at)


def test_two_concurrent_updates_allow_exactly_one_revision(postgres_engine) -> None:
    repository = PostgresChannelRepository(postgres_engine)
    now = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    repository.save(_draft(), None, now)

    def update(name: str):
        try:
            return repository.save(_draft(name), 1, now)
        except ChannelRevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ("Version A", "Version B")))

    assert sum(result is not None for result in results) == 1
    assert repository.get("tech_vn").revision == 2


def test_revision_history_failure_rolls_back_current_profile(postgres_engine) -> None:
    repository = PostgresChannelRepository(postgres_engine)
    now = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    original = repository.save(_draft(), None, now)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION fail_channel_history() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'history blocked'; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER fail_channel_history BEFORE INSERT ON "
                "channel_profile_revisions FOR EACH ROW EXECUTE FUNCTION "
                "fail_channel_history()"
            )
        )
    try:
        with pytest.raises(DBAPIError):
            repository.save(_draft("Must Roll Back"), 1, now)
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DROP TRIGGER fail_channel_history ON channel_profile_revisions")
            )
            connection.execute(text("DROP FUNCTION fail_channel_history()"))

    assert repository.get("tech_vn") == original


def test_database_snapshots_and_audit_never_contain_resolved_secret(
    postgres_engine,
) -> None:
    marker = "VIDEOOPS_TEST_SECRET_9f37"
    repository = PostgresChannelRepository(postgres_engine)
    catalog = DefaultChannelCatalog(
        repository,
        EnvironmentSecretResolver(
            {
                "YT_TECH_YOUTUBE_CLIENT_ID": "id",
                "YT_TECH_YOUTUBE_CLIENT_SECRET": marker,
                "YT_TECH_YOUTUBE_REFRESH_TOKEN": "refresh",
            }
        ),
        _Clock(),
        admin_enabled=True,
    )
    catalog.save(SaveChannelRequest(_draft(), actor_id="admin"))
    assert catalog.get_snapshot("tech_vn").available_targets == (Platform.YOUTUBE,)

    with postgres_engine.connect() as connection:
        payloads = connection.execute(
            text(
                "SELECT profile_snapshot::text FROM channel_profiles "
                "UNION ALL SELECT profile_snapshot::text FROM channel_profile_revisions "
                "UNION ALL SELECT audit_metadata::text FROM audit_entries"
            )
        ).scalars()

    assert all(marker not in payload for payload in payloads)


class _Clock:
    def now(self):
        return datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class _Ids:
    def new_job_id(self):
        return "job-channel-snapshot"


def test_catalog_supplies_available_targets_and_job_keeps_channel_revision(
    postgres_engine,
) -> None:
    repository = PostgresChannelRepository(postgres_engine)
    catalog = DefaultChannelCatalog(
        repository,
        EnvironmentSecretResolver(
            {
                "YT_TECH_YOUTUBE_CLIENT_ID": "id",
                "YT_TECH_YOUTUBE_CLIENT_SECRET": "secret",
                "YT_TECH_YOUTUBE_REFRESH_TOKEN": "refresh",
            }
        ),
        _Clock(),
        admin_enabled=True,
    )
    catalog.save(SaveChannelRequest(_draft()))
    workflow_store = PostgresWorkflowStore(postgres_engine)
    workflow = DefaultVideoWorkflow(workflow_store, catalog, _Clock(), _Ids())

    submitted = workflow.submit(
        StoryRequest(
            request_id="request-channel-snapshot",
            channel_id="tech_vn",
            script="Nội dung",
            metadata=VideoMetadata(title="Story"),
        )
    )
    catalog.save(SaveChannelRequest(_draft("Revision Two"), expected_revision=1))

    stored = workflow_store.get(submitted.job_id)
    assert stored is not None
    assert stored.channel_revision == 1
    assert stored.available_targets == (Platform.YOUTUBE,)
    assert catalog.get_snapshot("tech_vn").revision == 2


def test_repository_reads_the_exact_historical_revision(postgres_engine) -> None:
    repository = PostgresChannelRepository(postgres_engine)
    first_time = datetime(2026, 11, 17, 8, tzinfo=UTC)
    second_time = datetime(2026, 11, 17, 9, tzinfo=UTC)
    first = _draft(name="First profile")
    repository.save(first, None, first_time)
    second = replace(first, name="Second profile")
    repository.save(second, 1, second_time)

    historical = repository.get_revision("tech_vn", 1)

    assert historical is not None
    assert historical.revision == 1
    assert historical.draft.name == "First profile"
    assert historical.created_at == first_time
    assert historical.updated_at == first_time
    assert repository.get_revision("tech_vn", 99) is None
