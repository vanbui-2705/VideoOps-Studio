from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.application.remix_service import (
    PrepareRemixRequest,
    RemixMediaConfig,
    RemixMediaService,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaConfigurationError, MediaInvalidOutput
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import RemixClipSnapshot, RemixSnapshot

NOW = datetime(2026, 11, 19, tzinfo=UTC)


class MemoryManifests:
    def __init__(self) -> None:
        self.items = {}

    def get(self, job_id, artifact_id):
        return self.items.get((job_id, artifact_id))

    def save(self, manifest: ArtifactManifest):
        self.items[(manifest.job_id, manifest.artifact_id)] = manifest
        return manifest

    def list_for_revision(self, job_id, content_revision):
        return tuple(
            item
            for item in self.items.values()
            if item.job_id == job_id and item.content_revision == content_revision
        )


class Downloader:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, url, workspace, relative_path, heartbeat=None):
        self.calls += 1
        path = workspace.part_path(relative_path)
        path.write_bytes(b"source")
        return workspace.promote(relative_path)


class Processor:
    def __init__(self) -> None:
        self.calls = 0

    def normalize(self, **kwargs):
        self.calls += 1
        kwargs["output_path"].write_bytes(b"normalized")


class Renderer:
    def __init__(self) -> None:
        self.calls = 0
        self.clips = ()

    def render(self, **kwargs):
        self.calls += 1
        self.clips = kwargs["clips"]
        kwargs["output_path"].write_bytes(b"preview")


class Probe:
    def __init__(self, source_duration=10_000, source_has_video=True) -> None:
        self.source_duration = source_duration
        self.source_has_video = source_has_video

    def probe(self, path):
        if "source-" in path.name:
            if not self.source_has_video:
                return MediaInfo(
                    self.source_duration,
                    "aac",
                    format_name="mp4",
                    has_audio=True,
                )
            return MediaInfo(
                self.source_duration, "h264", 1920, 1080, "mp4", has_audio=True
            )
        return MediaInfo(4000, "h264", 854, 480, "mp4", has_audio=True)


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
        1,
        NOW,
        NOW,
    )


def _request() -> PrepareRemixRequest:
    return PrepareRemixRequest(
        "job-1",
        1,
        RemixSnapshot(
            (
                RemixClipSnapshot(
                    "https://media.example.com/video",
                    1.0,
                    5.0,
                    1,
                    1.0,
                    "fill",
                    False,
                ),
            ),
            True,
        ),
        _profile(),
    )


def _service(tmp_path: Path, probe=None):
    downloader = Downloader()
    processor = Processor()
    renderer = Renderer()
    manifests = MemoryManifests()
    service = RemixMediaService(
        downloader=downloader,
        processor=processor,
        renderer=renderer,
        probe=probe or Probe(),
        manifests=manifests,
        config=RemixMediaConfig(tmp_path),
        now=lambda: NOW,
    )
    return service, downloader, processor, renderer, manifests


def test_remix_service_prepares_renders_and_reuses_artifacts(tmp_path: Path) -> None:
    service, downloader, processor, renderer, manifests = _service(tmp_path)
    request = _request()

    prepared = service.prepare_sources(request)
    bundle = service.render_preview(request)
    prepared_again = service.prepare_sources(request)
    bundle_again = service.render_preview(request)

    assert prepared[0].metadata["role"] == "normalized"
    assert [item.artifact_type for item in bundle.artifacts] == [
        "VISUAL_SOURCE",
        "PREVIEW",
    ]
    assert prepared_again == prepared
    assert bundle_again == bundle
    assert downloader.calls == 1
    assert processor.calls == 1
    assert renderer.calls == 1
    source = manifests.get("job-1", "source:1:1")
    assert source.metadata["source_host"] == "media.example.com"
    assert "video" not in source.metadata


def test_remix_service_rejects_range_past_source_duration(tmp_path: Path) -> None:
    service, *_ = _service(tmp_path, Probe(source_duration=2000))

    with pytest.raises(MediaConfigurationError):
        service.prepare_sources(_request())


def test_remix_service_rejects_source_without_video(tmp_path: Path) -> None:
    service, _, processor, *_ = _service(tmp_path, Probe(source_has_video=False))

    with pytest.raises(MediaInvalidOutput, match="requires video"):
        service.prepare_sources(_request())

    assert processor.calls == 0


def test_remix_service_does_not_reuse_corrupt_artifact(tmp_path: Path) -> None:
    service, downloader, processor, *_ = _service(tmp_path)
    service.prepare_sources(_request())
    workspace = JobWorkspace(tmp_path, "job-1", 1)
    workspace.final_path("remix/clip-1.mp4").write_bytes(b"corrupt")

    service.prepare_sources(_request())

    assert downloader.calls == 1
    assert processor.calls == 2
