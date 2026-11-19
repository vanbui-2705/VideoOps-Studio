from __future__ import annotations

import pytest

from core.adapters.media.edge_tts_provider import EdgeTtsProvider
from core.application.media_ports import TtsRequest
from core.domain.errors import MediaTransientError


class FakeCommunicate:
    def __init__(self, chunks) -> None:
        self._chunks = chunks

    async def stream(self):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


@pytest.mark.asyncio
async def test_edge_tts_adapter_returns_audio_and_timed_unicode_cues() -> None:
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeCommunicate(
            [
                {"type": "audio", "data": b"ID3audio"},
                {
                    "type": "SentenceBoundary",
                    "offset": 0,
                    "duration": 12_500_000,
                    "text": "Xin chào Việt Nam 👋",
                },
                {
                    "type": "SentenceBoundary",
                    "offset": 12_500_000,
                    "duration": 7_500_000,
                    "text": "Tương lai bắt đầu.",
                },
            ]
        )

    result = await EdgeTtsProvider(factory).synthesize(
        TtsRequest("Xin chào Việt Nam 👋 Tương lai bắt đầu.", "vi-VN-Nam", 15)
    )

    assert result.audio_bytes == b"ID3audio"
    assert [(cue.start_ms, cue.end_ms) for cue in result.cues] == [
        (0, 1250),
        (1250, 2000),
    ]
    assert result.cues[0].text == "Xin chào Việt Nam 👋"
    assert captured["rate"] == "+15%"
    assert captured["boundary"] == "SentenceBoundary"


@pytest.mark.asyncio
async def test_edge_tts_adapter_redacts_provider_exception() -> None:
    provider = EdgeTtsProvider(
        lambda **kwargs: FakeCommunicate([RuntimeError("token=secret")])
    )

    with pytest.raises(MediaTransientError) as caught:
        await provider.synthesize(TtsRequest("Narration", "voice", 0))

    assert "secret" not in str(caught.value)
