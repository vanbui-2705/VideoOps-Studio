from __future__ import annotations

import pytest

from core.adapters.persistence.mappers import job_from_dict, job_to_dict
from core.application.requests import RemixClip, RemixRequest
from core.application.video_workflow import DefaultVideoWorkflow
from core.domain.errors import DomainValidationError
from core.domain.models import VideoMetadata
from tests.unit.application.test_video_workflow import (
    FakeChannels,
    FakeWorkflowStore,
    FixedClock,
    FixedIds,
)


def _clip(**changes) -> RemixClip:
    values = {
        "url": "https://media.example.com/video/123",
        "start_seconds": 1.0,
        "end_seconds": 8.0,
        "order": 1,
        "speed": 1.0,
        "crop_mode": "fill",
        "mirror": False,
    }
    values.update(changes)
    return RemixClip(**values)


@pytest.mark.parametrize(
    "changes",
    (
        {"url": "https://127.0.0.1/video"},
        {"url": "https://user:secret@example.com/video"},
        {"speed": 0.1},
        {"speed": 5.0},
        {"crop_mode": "stretch"},
        {"order": 0},
    ),
)
def test_remix_clip_rejects_unsafe_or_unsupported_values(changes) -> None:
    with pytest.raises(DomainValidationError):
        _clip(**changes)


def test_remix_request_requires_contiguous_order() -> None:
    with pytest.raises(DomainValidationError):
        RemixRequest(
            "request-1",
            "tech_vn",
            (_clip(order=1), _clip(order=3)),
            True,
            VideoMetadata(title="Remix"),
        )


def test_remix_snapshot_round_trip_preserves_transform_settings() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    job = workflow.submit(
        RemixRequest(
            "request-remix-settings",
            "tech-vn",
            (_clip(crop_mode="fit", mirror=True, speed=1.25),),
            True,
            VideoMetadata(title="Remix"),
        )
    )

    restored = job_from_dict(job_to_dict(store.jobs[job.job_id]))

    snapshot = restored.request_snapshot
    assert snapshot is not None
    assert snapshot.clips[0].crop_mode == "fit"
    assert snapshot.clips[0].mirror is True
    assert snapshot.clips[0].speed == 1.25
