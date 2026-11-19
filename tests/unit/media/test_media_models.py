from datetime import UTC, datetime

import pytest

from core.domain.errors import DomainValidationError
from core.domain.media_models import (
    ArtifactManifest,
    MediaInfo,
    SubtitleCue,
    subtitles_to_srt,
)


def test_subtitle_cues_serialize_utf8_text_with_monotonic_timing() -> None:
    cues = (
        SubtitleCue(1, 0, 1250, "Xin chào “Việt Nam” 👋"),
        SubtitleCue(2, 1250, 2500, "Dòng hai\\được giữ nguyên"),
    )

    rendered = subtitles_to_srt(cues)

    assert rendered == (
        "1\n00:00:00,000 --> 00:00:01,250\nXin chào “Việt Nam” 👋\n\n"
        "2\n00:00:01,250 --> 00:00:02,500\nDòng hai\\được giữ nguyên\n"
    )


def test_subtitle_sequence_rejects_overlap() -> None:
    with pytest.raises(DomainValidationError, match="overlap"):
        subtitles_to_srt(
            (SubtitleCue(1, 0, 1000, "one"), SubtitleCue(2, 999, 2000, "two"))
        )


def test_artifact_manifest_requires_relative_path_and_valid_checksum() -> None:
    info = MediaInfo(1000, "h264", 854, 480)
    valid = ArtifactManifest(
        artifact_id="preview:job:1",
        job_id="job-1",
        artifact_type="PREVIEW",
        relative_path="preview/preview.mp4",
        checksum="a" * 64,
        byte_size=123,
        content_revision=1,
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
        media_info=info,
    )

    assert valid.relative_path == "preview/preview.mp4"
    with pytest.raises(DomainValidationError, match="relative"):
        ArtifactManifest(
            artifact_id="bad",
            job_id="job-1",
            artifact_type="PREVIEW",
            relative_path="../escape.mp4",
            checksum="a" * 64,
            byte_size=1,
            content_revision=1,
            created_at=datetime(2026, 11, 17, tzinfo=UTC),
        )
    with pytest.raises(DomainValidationError, match="checksum"):
        ArtifactManifest(
            artifact_id="bad-hash",
            job_id="job-1",
            artifact_type="PREVIEW",
            relative_path="preview.mp4",
            checksum="not-a-hash",
            byte_size=1,
            content_revision=1,
            created_at=datetime(2026, 11, 17, tzinfo=UTC),
        )
