from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.application.master_service import (
    MasterRenderConfig,
    MasterRenderRequest,
    MasterRenderService,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaInvalidOutput
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    ApprovalSnapshot,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    RemixClipSnapshot,
    RemixSnapshot,
    StorySnapshot,
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

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class MemoryManifests:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], ArtifactManifest] = {}

    def get(self, job_id: str, artifact_id: str) -> ArtifactManifest | None:
        return self.items.get((job_id, artifact_id))

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self.items[(manifest.job_id, manifest.artifact_id)] = manifest
        return manifest

    def list_for_revision(
        self, job_id: str, content_revision: int
    ) -> tuple[ArtifactManifest, ...]:
        return tuple(
            item
            for item in self.items.values()
            if item.job_id == job_id and item.content_revision == content_revision
        )


class Renderer:
    def __init__(self) -> None:
        self.story_calls = 0
        self.story_inputs = None
        self.remix_calls = 0
        self.remix_inputs = None

    def render_story(self, **kwargs) -> None:
        self.story_calls += 1
        self.story_inputs = kwargs
        kwargs["output_path"].write_bytes(b"story-master")

    def render_remix(self, **kwargs) -> None:
        self.remix_calls += 1
        self.remix_inputs = kwargs
        kwargs["output_path"].write_bytes(b"remix-master")


class Probe:
    def probe(self, path: Path) -> MediaInfo:
        return MediaInfo(4_000, "h264", 1920, 1080, "mp4", has_audio=True)


def _profile() -> ChannelProfile:
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(aspect_ratio="16:9"),
            AudioPreset("voice"),
        ),
        2,
        NOW,
        NOW,
    )


def _story() -> ScriptDraft:
    narration = "One scene narration"
    return ScriptDraft(
        "en-US",
        "Approved story",
        narration,
        (ScriptScene(1, narration, ("technology",)),),
        SuggestedMetadata("Approved story"),
        ScriptProvenance(
            StorySource.USER_SCRIPT,
            "story-v1",
            "a" * 64,
            "b" * 64,
            NOW,
        ),
    )


def _job() -> VideoJob:
    metadata = VideoMetadata(title="Approved")
    return VideoJob(
        "job-1",
        "request-1",
        "tech_vn",
        JobType.STORY,
        JobStatus.RENDERING_MASTER,
        JobPhase.MASTER_RENDER,
        4,
        1,
        metadata,
        NOW,
        NOW,
        channel_revision=2,
        approval_snapshot=ApprovalSnapshot(
            1,
            2,
            metadata,
            (Platform.YOUTUBE,),
            NOW,
        ),
        request_snapshot=StorySnapshot("One scene narration", None),
        prepared_story=_story(),
    )


def _remix_job() -> VideoJob:
    metadata = VideoMetadata(title="Approved Remix")
    return VideoJob(
        "job-1",
        "request-remix",
        "tech_vn",
        JobType.REMIX,
        JobStatus.RENDERING_MASTER,
        JobPhase.MASTER_RENDER,
        4,
        1,
        metadata,
        NOW,
        NOW,
        channel_revision=2,
        approval_snapshot=ApprovalSnapshot(
            1,
            2,
            metadata,
            (Platform.YOUTUBE,),
            NOW,
        ),
        request_snapshot=RemixSnapshot(
            (
                RemixClipSnapshot(
                    "https://media.example.com/video",
                    0,
                    4,
                    1,
                    1,
                    "fill",
                    True,
                ),
            ),
            True,
        ),
    )


def _manifest(
    workspace: JobWorkspace,
    *,
    artifact_id: str,
    artifact_type: str,
    relative_path: str,
    content: bytes,
    media_info: MediaInfo | None = None,
    metadata: dict | None = None,
) -> ArtifactManifest:
    path = workspace.final_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ArtifactManifest(
        artifact_id,
        "job-1",
        artifact_type,
        relative_path,
        hashlib.sha256(content).hexdigest(),
        len(content),
        1,
        NOW,
        media_info,
        metadata or {},
    )


def _service(tmp_path: Path):
    workspace = JobWorkspace(tmp_path, "job-1", 1)
    manifests = MemoryManifests()
    manifests.save(
        _manifest(
            workspace,
            artifact_id="voice:1",
            artifact_type="VOICE",
            relative_path="voice/narration.mp3",
            content=b"voice",
            media_info=MediaInfo(4_000, "mp3", has_audio=True),
        )
    )
    manifests.save(
        _manifest(
            workspace,
            artifact_id="subtitle:1",
            artifact_type="SUBTITLE",
            relative_path="subtitles/narration.srt",
            content=b"subtitle",
        )
    )
    manifests.save(
        _manifest(
            workspace,
            artifact_id="visual:1:1",
            artifact_type="VISUAL_SOURCE",
            relative_path="visuals/scene-1.mp4",
            content=b"visual",
            media_info=MediaInfo(6_000, "h264", 1920, 1080, "mp4", True),
            metadata={"kind": "VIDEO"},
        )
    )
    manifests.save(
        _manifest(
            workspace,
            artifact_id="preview:1",
            artifact_type="PREVIEW",
            relative_path="preview/preview.mp4",
            content=b"preview",
            media_info=MediaInfo(4_000, "h264", 854, 480, "mp4", True),
        )
    )
    renderer = Renderer()
    service = MasterRenderService(
        renderer=renderer,
        probe=Probe(),
        manifests=manifests,
        config=MasterRenderConfig(tmp_path),
        now=lambda: NOW,
    )
    return service, renderer, manifests, workspace


def test_story_master_uses_original_artifacts_and_reuses_valid_output(
    tmp_path: Path,
) -> None:
    service, renderer, manifests, workspace = _service(tmp_path)
    request = MasterRenderRequest(_job(), _profile())

    first = service.render(request)
    second = service.render(request)

    assert first == second
    assert first.artifact_id == "master:1"
    assert first.artifact_type == "MASTER"
    assert renderer.story_calls == 1
    assert renderer.story_inputs is not None
    assert renderer.story_inputs["voice_path"].name == "narration.mp3"
    assert renderer.story_inputs["subtitle_path"].name == "narration.srt"
    assert all(
        "preview" not in str(path) for path in renderer.story_inputs["source_paths"]
    )
    assert manifests.get("job-1", "master:1") == first

    workspace.final_path(first.relative_path).write_bytes(b"corrupt")
    rebuilt = service.render(request)

    assert rebuilt.artifact_id == "master:1"
    assert renderer.story_calls == 2


def test_remix_master_uses_downloaded_sources_not_preview_normalizations(
    tmp_path: Path,
) -> None:
    workspace = JobWorkspace(tmp_path, "job-1", 1)
    manifests = MemoryManifests()
    manifests.save(
        _manifest(
            workspace,
            artifact_id="source:1:1",
            artifact_type="VISUAL_SOURCE",
            relative_path="sources/source-1.mp4",
            content=b"original-source",
            media_info=MediaInfo(10_000, "h264", 1920, 1080, "mp4", True),
            metadata={"role": "source", "order": 1},
        )
    )
    manifests.save(
        _manifest(
            workspace,
            artifact_id="remix:1:1",
            artifact_type="VISUAL_SOURCE",
            relative_path="remix/clip-1.mp4",
            content=b"preview-normalization",
            media_info=MediaInfo(4_000, "h264", 854, 480, "mp4", True),
            metadata={"role": "normalized", "order": 1},
        )
    )
    manifests.save(
        _manifest(
            workspace,
            artifact_id="preview:1",
            artifact_type="PREVIEW",
            relative_path="preview/remix.mp4",
            content=b"preview",
            media_info=MediaInfo(4_000, "h264", 854, 480, "mp4", True),
        )
    )
    renderer = Renderer()
    service = MasterRenderService(
        renderer=renderer,
        probe=Probe(),
        manifests=manifests,
        config=MasterRenderConfig(tmp_path),
        now=lambda: NOW,
    )

    result = service.render(MasterRenderRequest(_remix_job(), _profile()))

    assert result.artifact_type == "MASTER"
    assert renderer.story_calls == 0
    assert renderer.remix_calls == 1
    assert renderer.remix_inputs is not None
    sources = renderer.remix_inputs["sources"]
    assert len(sources) == 1
    assert sources[0][0].name == "source-1.mp4"
    assert sources[0][1].mirror is True
    assert all("preview" not in str(source[0]) for source in sources)
    assert all("remix/clip" not in source[0].as_posix() for source in sources)


def test_failed_master_render_removes_partial_file(tmp_path: Path) -> None:
    service, renderer, _, workspace = _service(tmp_path)

    def fail(**kwargs):
        kwargs["output_path"].write_bytes(b"incomplete")
        raise MediaInvalidOutput("render failed")

    renderer.render_story = fail

    with pytest.raises(MediaInvalidOutput, match="render failed"):
        service.render(MasterRenderRequest(_job(), _profile()))

    assert not workspace.part_path("master/master.mp4").exists()
