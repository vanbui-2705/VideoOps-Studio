"""YouTube Data API v3 resumable publisher."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.application.channel_ports import YoutubeCredential
from core.application.publish_ports import (
    PublishFailed,
    PublishOutcome,
    PublishReceipt,
    PublishRequest,
    PublishSucceeded,
    PublishUnknown,
)
from core.domain.models import Platform


def _client(credential: YoutubeCredential):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=credential.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=credential.client_id,
        client_secret=credential.client_secret,
        scopes=("https://www.googleapis.com/auth/youtube.upload",),
    )
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def _media(path: str, **kwargs):
    from googleapiclient.http import MediaFileUpload

    return MediaFileUpload(path, mimetype="video/mp4", **kwargs)


class YoutubePublisher:
    platform = Platform.YOUTUBE

    def __init__(
        self,
        *,
        client_factory: Callable[[YoutubeCredential], Any] = _client,
        media_factory: Callable[..., Any] = _media,
        chunk_bytes: int = 8 * 1024 * 1024,
        max_chunk_retries: int = 5,
        retry_base_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            chunk_bytes <= 0
            or chunk_bytes % (256 * 1024) != 0
            or not 0 <= max_chunk_retries <= 10
            or retry_base_seconds < 0
        ):
            raise ValueError("YouTube upload configuration is invalid")
        self._client_factory = client_factory
        self._media_factory = media_factory
        self._chunk_bytes = chunk_bytes
        self._max_retries = max_chunk_retries
        self._retry_base = retry_base_seconds
        self._sleep = sleeper
        self._random = random_value
        self._now = now or (lambda: datetime.now(UTC))

    def publish(self, request: PublishRequest, *, heartbeat=None) -> PublishOutcome:
        if not isinstance(request.credential, YoutubeCredential):
            return PublishFailed("YOUTUBE_CREDENTIAL_INVALID", False)
        try:
            client = self._client_factory(request.credential)
            media = self._media_factory(
                str(request.master_path),
                chunksize=self._chunk_bytes,
                resumable=True,
            )
            upload = client.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": request.metadata.title,
                        "description": request.metadata.description,
                        "tags": list(request.metadata.tags),
                        "categoryId": request.metadata.category_id,
                    },
                    "status": {"privacyStatus": request.metadata.privacy},
                },
                media_body=media,
            )
        except Exception:  # noqa: BLE001 - provider construction is sanitized
            return PublishFailed("YOUTUBE_CONFIGURATION", False)

        retries = 0
        sent = False
        while True:
            try:
                sent = True
                _, response = upload.next_chunk()
                if heartbeat:
                    heartbeat()
                if response is None:
                    continue
                video_id = str(response.get("id") or "").strip()
                if not video_id:
                    return PublishUnknown("YOUTUBE_RECEIPT_MISSING")
                return PublishSucceeded(
                    PublishReceipt(
                        video_id,
                        f"https://www.youtube.com/watch?v={video_id}",
                        video_id,
                        self._now(),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - classify provider exceptions
                classification = _classify_error(exc)
                if classification == "TRANSIENT" and retries < self._max_retries:
                    delay = self._retry_base * (2**retries) + self._random()
                    retries += 1
                    self._sleep(delay)
                    continue
                if classification == "QUOTA":
                    return PublishFailed("YOUTUBE_QUOTA", False)
                if classification == "AUTH":
                    return PublishFailed("YOUTUBE_AUTH", False)
                if classification == "VALIDATION":
                    return PublishFailed("YOUTUBE_VALIDATION", False)
                if sent:
                    return PublishUnknown("YOUTUBE_UPLOAD_AMBIGUOUS")
                return PublishFailed("YOUTUBE_TRANSIENT", True)

    def reconcile(
        self,
        request: PublishRequest,
        provider_operation_id: str | None,
        *,
        heartbeat=None,
    ) -> PublishOutcome:
        if provider_operation_id:
            return PublishSucceeded(
                PublishReceipt(
                    provider_operation_id,
                    f"https://www.youtube.com/watch?v={provider_operation_id}",
                    provider_operation_id,
                    self._now(),
                )
            )
        return PublishUnknown("YOUTUBE_RECONCILIATION_REQUIRED")


def _classify_error(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    text = str(exc).casefold()
    if status in {500, 502, 503, 504, 429} or isinstance(
        exc, (TimeoutError, ConnectionError, OSError)
    ):
        return "TRANSIENT"
    if "quota" in text or "uploadlimit" in text:
        return "QUOTA"
    if status in {401, 403}:
        return "AUTH"
    if status is not None and 400 <= status < 500:
        return "VALIDATION"
    return "UNKNOWN"
