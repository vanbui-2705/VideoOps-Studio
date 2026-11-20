from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.adapters.persistence.artifact_manifest_store import (
    PostgresArtifactManifestStore,
)
from core.adapters.persistence.channel_repository import PostgresChannelRepository
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.adapters.secrets.environment import EnvironmentSecretResolver
from core.application.channel_catalog import DefaultChannelCatalog
from core.application.remix_service import RemixMediaConfig, RemixMediaService
from core.application.requests import RemixClip, RemixRequest
from core.application.video_workflow import (
    DefaultVideoWorkflow,
    DefaultWorkflowProcessor,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    VisualPreset,
)
from core.domain.media_models import MediaInfo
from core.domain.models import ArtifactKind, JobStatus, VideoMetadata, WorkKind
from core.runtime.preview_handler import PreviewRenderHandler
from core.runtime.remix_handler import RemixPreparationHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 19, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Ids:
    def new_job_id(self):
        return "remix-journey"


class Downloader:
    def download(self, url, workspace, relative_path, heartbeat=None):
        path = workspace.part_path(relative_path)
        path.write_bytes(b"source")
        return workspace.promote(relative_path)


class Processor:
    def normalize(self, **kwargs):
        kwargs["output_path"].write_bytes(b"normalized")


class Renderer:
    def render(self, **kwargs):
        kwargs["output_path"].write_bytes(b"preview")


class Probe:
    def probe(self, path):
        if "source-" in path.name:
            return MediaInfo(5000, "h264", 1280, 720, "mp4", True)
        return MediaInfo(4000, "h264", 854, 480, "mp4", True)


def test_remix_workers_reach_review_with_durable_artifacts(
    postgres_engine,
    tmp_path: Path,
) -> None:
    channels = PostgresChannelRepository(postgres_engine)
    channels.save(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(aspect_ratio="16:9"),
            AudioPreset("voice"),
        ),
        None,
        NOW,
    )
    store = PostgresWorkflowStore(postgres_engine)
    catalog = DefaultChannelCatalog(
        channels,
        EnvironmentSecretResolver({}),
        Clock(),
    )
    workflow = DefaultVideoWorkflow(store, catalog, Clock(), Ids())
    submitted = workflow.submit(
        RemixRequest(
            "remix-request",
            "tech_vn",
            (
                RemixClip(
                    "https://media.example.com/video",
                    0,
                    4,
                    1,
                    crop_mode="fill",
                    mirror=True,
                ),
            ),
            True,
            VideoMetadata(title="Remix"),
        )
    )
    manifests = PostgresArtifactManifestStore(postgres_engine)
    service = RemixMediaService(
        downloader=Downloader(),
        processor=Processor(),
        renderer=Renderer(),
        probe=Probe(),
        manifests=manifests,
        config=RemixMediaConfig(tmp_path),
        now=lambda: NOW,
    )
    queue = PostgresWorkQueue(postgres_engine)
    processor = DefaultWorkflowProcessor(store, Clock())
    prepare_worker = Worker(
        worker_id="remix-prepare",
        queue=queue,
        processor=processor,
        handlers={
            WorkKind.PREPARE_REMIX: RemixPreparationHandler(store, channels, service)
        },
    )
    preview_worker = Worker(
        worker_id="remix-preview",
        queue=queue,
        processor=processor,
        handlers={
            WorkKind.RENDER_PREVIEW: PreviewRenderHandler(
                store, channels, None, service
            )
        },
    )

    try:
        assert prepare_worker.run_once() is True
        assert preview_worker.run_once() is True
    finally:
        prepare_worker.close()
        preview_worker.close()

    completed = store.get(submitted.job_id)
    assert completed is not None
    assert completed.status is JobStatus.AWAITING_REVIEW
    assert {item.kind for item in completed.artifacts} == {
        ArtifactKind.VISUAL_SOURCE,
        ArtifactKind.PREVIEW,
    }
    assert manifests.get(submitted.job_id, "source:1:1") is not None
    assert manifests.get(submitted.job_id, "remix:1:1") is not None
    assert manifests.get(submitted.job_id, "preview:1") is not None
