"""Official TikTok Content Posting API adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.application.channel_ports import TikTokCredential
from core.application.publish_ports import (
    PublishFailed,
    PublishOutcome,
    PublishProcessing,
    PublishReceipt,
    PublishRequest,
    PublishSucceeded,
    PublishUnknown,
)
from core.domain.models import Platform


class TikTokPublisher:
    platform = Platform.TIKTOK

    def __init__(
        self,
        client: Any,
        *,
        api_base_url: str = "https://open.tiktokapis.com",
        status_poll_seconds: int = 30,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        parsed_base = urlparse(api_base_url)
        if (
            parsed_base.scheme != "https"
            or parsed_base.hostname != "open.tiktokapis.com"
            or parsed_base.username is not None
            or parsed_base.password is not None
            or parsed_base.port not in {None, 443}
            or status_poll_seconds < 1
        ):
            raise ValueError("TikTok publishing configuration is invalid")
        self._client = client
        self._base = api_base_url.rstrip("/")
        self._poll_seconds = status_poll_seconds
        self._now = now or (lambda: datetime.now(UTC))

    def publish(self, request: PublishRequest, *, heartbeat=None) -> PublishOutcome:
        credential = request.credential
        if not isinstance(credential, TikTokCredential):
            return PublishFailed("TIKTOK_CREDENTIAL_INVALID", False)
        try:
            creator = self._post("/v2/post/publish/creator_info/query/", credential, {})
            privacy = _privacy(request.metadata.privacy)
            options = creator.get("privacy_level_options", [])
            if privacy not in options:
                return PublishFailed("TIKTOK_PRIVACY_UNAVAILABLE", False)
            duration_ms = request.duration_ms
            maximum = int(creator.get("max_video_post_duration_sec") or 0)
            if duration_ms and maximum and duration_ms > maximum * 1000:
                return PublishFailed("TIKTOK_DURATION_EXCEEDED", False)

            size = request.master_size
            chunk_size = min(size, 10 * 1024 * 1024)
            chunks = max(1, (size + chunk_size - 1) // chunk_size)
            initialized = self._post(
                "/v2/post/publish/video/init/",
                credential,
                {
                    "post_info": {
                        "title": _caption(request),
                        "privacy_level": privacy,
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": chunks,
                    },
                },
            )
            publish_id = str(initialized.get("publish_id") or "").strip()
            upload_url = str(initialized.get("upload_url") or "").strip()
            if not publish_id or not _trusted_upload_url(upload_url):
                return PublishUnknown("TIKTOK_INIT_AMBIGUOUS", publish_id or None)
            self._upload(
                upload_url,
                request.master_path,
                size,
                chunk_size,
                heartbeat=heartbeat,
            )
            return self._status(credential, publish_id)
        except Exception:  # noqa: BLE001 - provider details must not escape
            return PublishUnknown("TIKTOK_UPLOAD_AMBIGUOUS")

    def reconcile(
        self,
        request: PublishRequest,
        provider_operation_id: str | None,
        *,
        heartbeat=None,
    ) -> PublishOutcome:
        if not isinstance(request.credential, TikTokCredential):
            return PublishFailed("TIKTOK_CREDENTIAL_INVALID", False)
        if not provider_operation_id:
            return PublishUnknown("TIKTOK_RECONCILIATION_REQUIRED")
        try:
            if heartbeat:
                heartbeat()
            return self._status(request.credential, provider_operation_id)
        except Exception:  # noqa: BLE001 - provider details must not escape
            return PublishUnknown("TIKTOK_STATUS_AMBIGUOUS", provider_operation_id)

    def _status(self, credential: TikTokCredential, publish_id: str) -> PublishOutcome:
        data = self._post(
            "/v2/post/publish/status/fetch/",
            credential,
            {"publish_id": publish_id},
        )
        status = str(data.get("status") or "")
        if status == "PUBLISH_COMPLETE":
            identifiers = data.get("publicaly_available_post_id") or []
            video_id = str(identifiers[0]).strip() if identifiers else ""
            if not video_id:
                return PublishUnknown("TIKTOK_POST_ID_MISSING", publish_id)
            return PublishSucceeded(
                PublishReceipt(
                    video_id,
                    f"https://www.tiktok.com/@video/video/{video_id}",
                    publish_id,
                    self._now(),
                )
            )
        if status == "FAILED":
            reason = str(data.get("fail_reason") or "").casefold()
            if reason in {"auth_removed", "access_token_invalid"}:
                return PublishFailed("TIKTOK_AUTH", False)
            return PublishFailed("TIKTOK_REJECTED", False)
        if status in {
            "PROCESSING_UPLOAD",
            "PROCESSING_DOWNLOAD",
            "SEND_TO_USER_INBOX",
        }:
            return PublishProcessing(
                publish_id,
                self._now() + timedelta(seconds=self._poll_seconds),
            )
        return PublishUnknown("TIKTOK_STATUS_UNKNOWN", publish_id)

    def _post(self, path: str, credential: TikTokCredential, payload: dict) -> dict:
        response = self._client.post(
            f"{self._base}{path}",
            headers={
                "Authorization": f"Bearer {credential.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        error = body.get("error", {})
        if error.get("code") not in {None, "ok"}:
            raise RuntimeError("TikTok request failed")
        return dict(body.get("data") or {})

    def _upload(
        self,
        upload_url: str,
        path: Path,
        size: int,
        chunk_size: int,
        *,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        with path.open("rb") as source:
            start = 0
            while start < size:
                content = source.read(min(chunk_size, size - start))
                end = start + len(content) - 1
                response = self._client.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(content)),
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                    content=content,
                )
                response.raise_for_status()
                if heartbeat:
                    heartbeat()
                start = end + 1


def _privacy(value: str) -> str:
    if value == "public":
        return "PUBLIC_TO_EVERYONE"
    return "SELF_ONLY"


def _caption(request: PublishRequest) -> str:
    tags = " ".join(f"#{tag.lstrip('#')}" for tag in request.metadata.tags)
    return f"{request.metadata.title} {tags}".strip()[:2200]


def _trusted_upload_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "open-upload.tiktokapis.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
    )
