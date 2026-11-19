from dataclasses import replace
from datetime import UTC, datetime

from core.adapters.persistence.artifact_manifest_store import (
    PostgresArtifactManifestStore,
)
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
    JobPhase,
    JobStatus,
    JobType,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)

NOW = datetime(2026, 11, 16, 8, tzinfo=UTC)


def _seed(engine) -> tuple[PostgresWorkflowStore, VideoJob]:
    job = VideoJob(
        "artifact-job",
        "artifact-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.RENDERING_PREVIEW,
        JobPhase.PREVIEW_RENDER,
        2,
        1,
        VideoMetadata(title="Preview"),
        NOW,
        NOW,
    )
    store = PostgresWorkflowStore(engine)
    store.create(job, WorkIntent(job.job_id, WorkKind.RENDER_PREVIEW, 1))
    return store, job


def test_manifest_round_trip_and_workflow_commit_preserves_details(
    postgres_engine,
) -> None:
    workflow, job = _seed(postgres_engine)
    manifests = PostgresArtifactManifestStore(postgres_engine)
    voice = ArtifactManifest(
        "voice:1",
        job.job_id,
        ArtifactKind.VOICE.value,
        "voice/narration.mp3",
        "a" * 64,
        100,
        1,
        NOW,
        MediaInfo(1000, "mp3", format_name="mp3"),
        {"provider": "edge-tts"},
    )
    preview = ArtifactManifest(
        "preview:1",
        job.job_id,
        ArtifactKind.PREVIEW.value,
        "preview/preview.mp4",
        "b" * 64,
        500,
        1,
        NOW,
        MediaInfo(1000, "h264", 854, 480, "mov,mp4"),
    )
    manifests.save(voice)
    manifests.save(preview)

    updated = replace(
        job,
        revision=3,
        artifacts=(
            ArtifactRef(voice.artifact_id, ArtifactKind.VOICE, 1),
            ArtifactRef(preview.artifact_id, ArtifactKind.PREVIEW, 1),
        ),
    )
    workflow.commit(WorkflowDecision(updated), expected_revision=2)

    assert manifests.get(job.job_id, voice.artifact_id) == voice
    assert manifests.get(job.job_id, preview.artifact_id) == preview
    assert manifests.list_for_revision(job.job_id, 1) == (preview, voice)

    regenerated = replace(updated, revision=4, content_revision=2, artifacts=())
    workflow.commit(WorkflowDecision(regenerated), expected_revision=3)

    assert manifests.get(job.job_id, preview.artifact_id) == preview
