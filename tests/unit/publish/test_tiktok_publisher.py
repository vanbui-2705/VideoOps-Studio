from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.adapters.publish.tiktok import TikTokPublisher
from core.application.channel_ports import TikTokCredential
from core.application.publish_ports import PublishProcessing, PublishRequest
from core.domain.models import Platform, VideoMetadata

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http failure")


class Client:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("creator_info/query/"):
            return Response(
                {
                    "data": {
                        "privacy_level_options": ["SELF_ONLY"],
                        "max_video_post_duration_sec": 300,
                    },
                    "error": {"code": "ok"},
                }
            )
        if url.endswith("video/init/"):
            return Response(
                {
                    "data": {
                        "publish_id": "publish-safe-1",
                        "upload_url": "https://open-upload.tiktokapis.com/signed-secret",
                    },
                    "error": {"code": "ok"},
                }
            )
        return Response(
            {
                "data": {"status": "PROCESSING_UPLOAD"},
                "error": {"code": "ok"},
            }
        )

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return Response({}, 200)


def test_tiktok_publish_uses_official_file_flow_and_defers_processing(tmp_path: Path):
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master")
    client = Client()
    publisher = TikTokPublisher(
        client,
        status_poll_seconds=30,
        now=lambda: NOW,
    )
    request = PublishRequest(
        "job-1",
        Platform.TIKTOK,
        "a" * 64,
        master,
        "b" * 64,
        6,
        VideoMetadata(title="Approved", tags=("one",), privacy="private"),
        TikTokCredential("access-token", "open-id"),
    )

    outcome = publisher.publish(request)

    assert outcome == PublishProcessing("publish-safe-1", NOW + timedelta(seconds=30))
    assert [method for method, _, _ in client.calls] == ["POST", "POST", "PUT", "POST"]
    init_payload = client.calls[1][2]["json"]
    assert init_payload["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init_payload["source_info"]["source"] == "FILE_UPLOAD"
    assert all(
        "signed-secret" not in str(kwargs.get("json", ""))
        for _, _, kwargs in client.calls
    )


def test_tiktok_rejects_lookalike_api_host_before_credentials_can_be_sent():
    with pytest.raises(ValueError, match="configuration"):
        TikTokPublisher(Client(), api_base_url="https://open.tiktokapis.com.evil.test")
