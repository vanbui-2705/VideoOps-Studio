from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.adapters.persistence.database import create_database_engine
from core.adapters.persistence.mappers import job_from_dict, job_to_dict
from core.domain.models import (
    ApprovalSnapshot,
    ArtifactKind,
    ArtifactRef,
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    RemixClipSnapshot,
    RemixSnapshot,
    ResumeAction,
    TargetStatus,
    VideoJob,
    VideoMetadata,
)
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)


def test_complex_remix_job_round_trips_without_losing_domain_values() -> None:
    now = datetime(2026, 11, 16, 10, 30, tzinfo=UTC)
    metadata = VideoMetadata(
        title="Bản dựng",
        description="Mô tả",
        tags=("video", "ops"),
        privacy="unlisted",
    )
    job = VideoJob(
        job_id="job-remix",
        request_id="request-remix",
        channel_id="tech-vn",
        job_type=JobType.REMIX,
        status=JobStatus.FAILED,
        phase=JobPhase.PUBLISH,
        revision=8,
        content_revision=2,
        metadata_draft=metadata,
        created_at=now,
        updated_at=now,
        artifacts=(ArtifactRef("master-1", ArtifactKind.MASTER, 2),),
        channel_revision=4,
        approval_snapshot=ApprovalSnapshot(
            2,
            4,
            metadata,
            (Platform.YOUTUBE,),
            now,
        ),
        publish_targets=(
            PublishTarget(
                Platform.YOUTUBE,
                TargetStatus.UNKNOWN,
                last_error_code="PUBLISH_UNKNOWN",
            ),
        ),
        failure=JobFailure(
            "PUBLISH_UNKNOWN",
            JobPhase.PUBLISH,
            "Cần đối soát.",
            True,
            ResumeAction.PUBLISH,
            target_platform=Platform.YOUTUBE,
            diagnostic_ref="diag-1",
        ),
        request_snapshot=RemixSnapshot(
            (RemixClipSnapshot("https://example.test/a", 1.5, 5.0, 0, 1.25),),
            True,
        ),
        progress=85,
        available_targets=(Platform.YOUTUBE, Platform.TIKTOK),
        regeneration_instructions=("nhanh hơn",),
    )

    restored = job_from_dict(job_to_dict(job))

    assert restored == job
    assert replace(restored).request_snapshot == job.request_snapshot


def test_database_engine_normalizes_generic_postgres_url_to_psycopg() -> None:
    engine = create_database_engine(
        "postgresql://videoops:local-only@localhost:5432/videoops"
    )
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert "local-only" not in repr(engine)
    finally:
        engine.dispose()


def test_remote_database_requires_tls() -> None:
    with pytest.raises(ValueError, match="sslmode=require"):
        create_database_engine(
            "postgresql+psycopg://videoops:not-logged@db.example/videoops"
        )


def test_prepared_story_round_trips_in_job_snapshot() -> None:
    now = datetime(2026, 11, 17, 8, tzinfo=UTC)
    story = ScriptDraft(
        language="vi",
        title="Một câu chuyện",
        narration="Nội dung câu chuyện.",
        scenes=(ScriptScene(1, "Nội dung câu chuyện.", ("thành phố",)),),
        suggested_metadata=SuggestedMetadata("Một câu chuyện", tags=("truyen",)),
        provenance=ScriptProvenance(
            source=StorySource.USER_SCRIPT,
            prompt_version="v1",
            prompt_hash="a" * 64,
            input_hash="b" * 64,
            generated_at=now,
        ),
    )
    job = VideoJob(
        job_id="story-job",
        request_id="story-request",
        channel_id="tech-vn",
        job_type=JobType.STORY,
        status=JobStatus.RENDERING_PREVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=2,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Một câu chuyện"),
        created_at=now,
        updated_at=now,
        prepared_story=story,
    )

    assert job_from_dict(job_to_dict(job)) == job
