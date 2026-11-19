from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.application.media_ports import TtsResult
from core.application.preview_service import (
    PreparePreviewRequest,
    PreviewPreparationConfig,
    PreviewPreparationService,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaTransientError
from core.domain.media_models import ArtifactManifest, MediaInfo, SubtitleCue
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)

NOW = datetime(2026, 11, 17, tzinfo=UTC)


class FakeTts:
    def __init__(self):
        self.calls = 0

    async def synthesize(self, request):
        self.calls += 1
        return TtsResult(
            b"audio-bytes",
            (
                SubtitleCue(1, 0, 1000, "Đoạn một."),
                SubtitleCue(2, 1000, 2000, "Đoạn hai."),
            ),
        )


class FlakyTts(FakeTts):
    async def synthesize(self, request):
        self.calls += 1
        if self.calls == 1:
            raise MediaTransientError("temporary")
        return TtsResult(
            b"audio-bytes",
            (SubtitleCue(1, 0, 2000, "Đoạn một. Đoạn hai."),),
        )


class EmptyStock:
    def __init__(self):
        self.calls = 0

    async def search(self, request):
        self.calls += 1


class TransientStock(EmptyStock):
    async def search(self, request):
        self.calls += 1
        raise MediaTransientError("temporary stock failure")


class NeverDownloader:
    async def download(self, *args, **kwargs):
        raise AssertionError("fallback must not download")


class FakeProbe:
    def probe(self, path):
        if "preview" in path.name:
            return MediaInfo(2000, "h264", 854, 480, "mp4")
        return MediaInfo(2000, "mp3", format_name="mp3")


class FakeRenderer:
    def __init__(self):
        self.calls = 0
        self.scenes = ()

    def render(self, **kwargs):
        self.calls += 1
        self.scenes = kwargs["scenes"]
        kwargs["output_path"].write_bytes(b"preview-bytes")


class FailOnceRenderer(FakeRenderer):
    def render(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("render process crashed")
        self.scenes = kwargs["scenes"]
        kwargs["output_path"].write_bytes(b"preview-bytes")


class MemoryManifests:
    def __init__(self):
        self.items = {}

    def get(self, job_id, artifact_id):
        return self.items.get((job_id, artifact_id))

    def save(self, manifest: ArtifactManifest):
        self.items[(manifest.job_id, manifest.artifact_id)] = manifest
        return manifest

    def list_for_revision(self, job_id, content_revision):
        return tuple(
            sorted(
                (
                    item
                    for item in self.items.values()
                    if item.job_id == job_id
                    and item.content_revision == content_revision
                ),
                key=lambda item: item.artifact_id,
            )
        )


def _profile() -> ChannelProfile:
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(aspect_ratio="16:9"),
            AudioPreset("vi-VN-Nam", rate_percent=5),
        ),
        1,
        NOW,
        NOW,
    )


def _story() -> ScriptDraft:
    narration = "Đoạn một.\n\nĐoạn hai."
    return ScriptDraft(
        "vi-VN",
        "Story",
        narration,
        (
            ScriptScene(1, "Đoạn một.", ("AI",)),
            ScriptScene(2, "Đoạn hai.", ("future",)),
        ),
        SuggestedMetadata("Story"),
        ScriptProvenance(
            StorySource.USER_SCRIPT,
            "v1",
            "a" * 64,
            "b" * 64,
            NOW,
        ),
    )


@pytest.mark.asyncio
async def test_preview_service_falls_back_locally_and_reuses_valid_bundle(
    tmp_path: Path,
) -> None:
    tts = FakeTts()
    stock = EmptyStock()
    renderer = FakeRenderer()
    manifests = MemoryManifests()
    service = PreviewPreparationService(
        tts=tts,
        stock_providers=(stock,),
        downloader=NeverDownloader(),
        probe=FakeProbe(),
        renderer=renderer,
        manifests=manifests,
        config=PreviewPreparationConfig(temp_root=tmp_path),
        now=lambda: NOW,
    )
    request = PreparePreviewRequest("job-1", 1, _story(), _profile())

    first = await service.prepare(request)
    second = await service.prepare(request)

    assert first == second
    assert tts.calls == 1
    assert renderer.calls == 1
    assert stock.calls == 2
    assert [scene.start_ms for scene in renderer.scenes] == [0, 1000]
    assert renderer.scenes[-1].end_ms == 2000
    assert all(
        scene.visual.kind.value == "GENERATED_BACKGROUND" for scene in renderer.scenes
    )
    assert {item.artifact_type for item in first.artifacts} == {
        "VOICE",
        "SUBTITLE",
        "VISUAL_SOURCE",
        "PREVIEW",
    }


@pytest.mark.asyncio
async def test_preview_retry_reuses_completed_tts_and_visual_side_effects(
    tmp_path: Path,
) -> None:
    tts = FakeTts()
    stock = EmptyStock()
    renderer = FailOnceRenderer()
    service = PreviewPreparationService(
        tts=tts,
        stock_providers=(stock,),
        downloader=NeverDownloader(),
        probe=FakeProbe(),
        renderer=renderer,
        manifests=MemoryManifests(),
        config=PreviewPreparationConfig(temp_root=tmp_path),
        now=lambda: NOW,
    )
    request = PreparePreviewRequest("job-retry", 1, _story(), _profile())

    with pytest.raises(RuntimeError):
        await service.prepare(request)
    result = await service.prepare(request)

    assert result.artifacts
    assert renderer.calls == 2
    assert tts.calls == 1
    assert stock.calls == 2


@pytest.mark.asyncio
async def test_preview_service_retries_transient_tts_with_heartbeat(
    tmp_path: Path,
) -> None:
    tts = FlakyTts()
    heartbeats = []
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    service = PreviewPreparationService(
        tts=tts,
        stock_providers=(),
        downloader=NeverDownloader(),
        probe=FakeProbe(),
        renderer=FakeRenderer(),
        manifests=MemoryManifests(),
        config=PreviewPreparationConfig(temp_root=tmp_path, max_attempts=2),
        now=lambda: NOW,
        sleeper=sleep,
    )

    await service.prepare(
        PreparePreviewRequest("job-tts-retry", 1, _story(), _profile()),
        heartbeat=lambda: heartbeats.append(True),
    )

    assert tts.calls == 2
    assert sleeps == [1.0]
    assert heartbeats


@pytest.mark.asyncio
async def test_preview_service_bounds_stock_retry_then_uses_local_fallback(
    tmp_path: Path,
) -> None:
    stock = TransientStock()
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    service = PreviewPreparationService(
        tts=FakeTts(),
        stock_providers=(stock,),
        downloader=NeverDownloader(),
        probe=FakeProbe(),
        renderer=FakeRenderer(),
        manifests=MemoryManifests(),
        config=PreviewPreparationConfig(temp_root=tmp_path, max_attempts=2),
        now=lambda: NOW,
        sleeper=sleep,
    )

    result = await service.prepare(
        PreparePreviewRequest("job-stock-retry", 1, _story(), _profile())
    )

    assert result.artifacts
    assert stock.calls == 4
    assert sleeps == [1.0, 1.0]
