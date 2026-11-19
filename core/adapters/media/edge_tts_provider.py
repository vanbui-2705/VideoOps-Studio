"""edge-tts adapter emitting provider-neutral audio bytes and subtitle cues."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.application.media_ports import TtsRequest, TtsResult
from core.domain.errors import (
    DomainValidationError,
    MediaInvalidOutput,
    MediaTransientError,
)
from core.domain.media_models import SubtitleCue


class EdgeTtsProvider:
    def __init__(
        self,
        communicator_factory: Callable[..., Any] | None = None,
        *,
        connect_timeout_seconds: int = 10,
        receive_timeout_seconds: int = 60,
    ) -> None:
        if communicator_factory is None:
            from edge_tts import Communicate

            communicator_factory = Communicate
        self._factory = communicator_factory
        self._connect_timeout = connect_timeout_seconds
        self._receive_timeout = receive_timeout_seconds

    async def synthesize(self, request: TtsRequest) -> TtsResult:
        rate = f"{request.rate_percent:+d}%"
        communicator = self._factory(
            text=request.narration,
            voice=request.voice,
            rate=rate,
            boundary="SentenceBoundary",
            connect_timeout=self._connect_timeout,
            receive_timeout=self._receive_timeout,
        )
        audio = bytearray()
        cues: list[SubtitleCue] = []
        try:
            async for chunk in communicator.stream():
                kind = chunk.get("type")
                if kind == "audio":
                    audio.extend(chunk.get("data", b""))
                elif kind in {"SentenceBoundary", "WordBoundary"}:
                    start_ms = int(chunk["offset"]) // 10_000
                    duration_ms = max(1, int(chunk["duration"]) // 10_000)
                    cues.append(
                        SubtitleCue(
                            len(cues) + 1,
                            start_ms,
                            start_ms + duration_ms,
                            str(chunk["text"]),
                        )
                    )
        except DomainValidationError as exc:
            raise MediaInvalidOutput("TTS timing output is invalid") from exc
        except Exception as exc:
            raise MediaTransientError("TTS provider request failed") from exc
        if not audio or not cues:
            raise MediaInvalidOutput("TTS output did not contain audio and timing")
        return TtsResult(bytes(audio), tuple(cues))
