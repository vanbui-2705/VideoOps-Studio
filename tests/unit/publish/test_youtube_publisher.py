from datetime import UTC, datetime
from pathlib import Path

from core.adapters.publish.youtube import YoutubePublisher
from core.application.channel_ports import YoutubeCredential
from core.application.publish_ports import PublishRequest, PublishSucceeded
from core.domain.models import Platform, VideoMetadata

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class UploadRequest:
    def __init__(self):
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.calls == 1:
            return object(), None
        return None, {"id": "youtube-video-1"}


class Videos:
    def __init__(self, upload):
        self.upload = upload
        self.kwargs = None

    def insert(self, **kwargs):
        self.kwargs = kwargs
        return self.upload


class Client:
    def __init__(self):
        self.upload = UploadRequest()
        self.resource = Videos(self.upload)

    def videos(self):
        return self.resource


def test_youtube_publish_uses_frozen_metadata_and_resumable_chunks(tmp_path: Path):
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master")
    client = Client()
    media_calls = []
    heartbeats = []
    publisher = YoutubePublisher(
        client_factory=lambda credential: client,
        media_factory=lambda *args, **kwargs: (
            media_calls.append((args, kwargs)) or object()
        ),
        chunk_bytes=8 * 1024 * 1024,
        now=lambda: NOW,
    )
    request = PublishRequest(
        "job-1",
        Platform.YOUTUBE,
        "a" * 64,
        master,
        "b" * 64,
        6,
        VideoMetadata(
            title="Approved",
            description="Frozen description",
            tags=("one", "two"),
            category_id="28",
            privacy="private",
        ),
        YoutubeCredential("client", "secret", "refresh"),
    )

    outcome = publisher.publish(request, heartbeat=lambda: heartbeats.append(1))

    assert isinstance(outcome, PublishSucceeded)
    assert outcome.receipt.external_video_id == "youtube-video-1"
    assert outcome.receipt.public_url == (
        "https://www.youtube.com/watch?v=youtube-video-1"
    )
    assert client.resource.kwargs["body"] == {
        "snippet": {
            "title": "Approved",
            "description": "Frozen description",
            "tags": ["one", "two"],
            "categoryId": "28",
        },
        "status": {"privacyStatus": "private"},
    }
    assert media_calls[0][1]["chunksize"] == 8 * 1024 * 1024
    assert media_calls[0][1]["resumable"] is True
    assert len(heartbeats) == 2
