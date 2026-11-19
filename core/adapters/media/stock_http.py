"""Bounded native HTTP adapters for Pexels and Pixabay stock media."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from core.adapters.media.workspace import JobWorkspace
from core.application.media_ports import StockCandidate, StockSearchRequest
from core.domain.errors import (
    MediaConfigurationError,
    MediaInvalidOutput,
    MediaTransientError,
)

_ALLOWED_DOWNLOAD_HOSTS = (
    "videos.pexels.com",
    "images.pexels.com",
    "cdn.pixabay.com",
    "pixabay.com",
)
_ALLOWED_CONTENT_TYPES = {"video/mp4", "image/jpeg", "image/png"}


class PexelsStockProvider:
    name = "pexels"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, request: StockSearchRequest) -> StockCandidate | None:
        orientation = "portrait" if request.aspect_ratio == "9:16" else "landscape"
        try:
            response = await self._client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": " ".join(request.keywords),
                    "orientation": orientation,
                    "per_page": 5,
                },
                headers={"Authorization": self._api_key},
            )
            _raise_provider_status(response)
            videos = response.json().get("videos", [])
        except httpx.TimeoutException as exc:
            raise MediaTransientError("Stock provider timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaTransientError("Stock provider request failed") from exc
        if not videos:
            return None
        video = videos[0]
        files = [
            item
            for item in video.get("video_files", [])
            if item.get("file_type") == "video/mp4" and item.get("link")
        ]
        if not files:
            return None
        desired_portrait = request.aspect_ratio == "9:16"
        files.sort(
            key=lambda item: (
                (int(item.get("height") or 0) > int(item.get("width") or 0))
                == desired_portrait,
                int(item.get("height") or 0) * int(item.get("width") or 0),
            ),
            reverse=True,
        )
        selected = files[0]
        return StockCandidate(
            provider="pexels",
            provider_id=str(video["id"]),
            download_url=selected["link"],
            source_url=video.get("url", f"https://www.pexels.com/video/{video['id']}/"),
            license_reference="https://www.pexels.com/license/",
            media_type="video/mp4",
            width=int(selected["width"]),
            height=int(selected["height"]),
        )


class PixabayStockProvider:
    name = "pixabay"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, request: StockSearchRequest) -> StockCandidate | None:
        try:
            response = await self._client.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": self._api_key,
                    "q": " ".join(request.keywords),
                    "per_page": 5,
                },
            )
            _raise_provider_status(response)
            hits = response.json().get("hits", [])
        except httpx.TimeoutException as exc:
            raise MediaTransientError("Stock provider timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaTransientError("Stock provider request failed") from exc
        if not hits:
            return None
        hit = hits[0]
        variants = hit.get("videos", {})
        selected = (
            variants.get("medium") or variants.get("small") or variants.get("large")
        )
        if not selected or not selected.get("url"):
            return None
        return StockCandidate(
            provider="pixabay",
            provider_id=str(hit["id"]),
            download_url=selected["url"],
            source_url=hit.get(
                "pageURL", f"https://pixabay.com/videos/id-{hit['id']}/"
            ),
            license_reference="https://pixabay.com/service/license-summary/",
            media_type="video/mp4",
            width=int(selected["width"]),
            height=int(selected["height"]),
        )


class BoundedStockDownloader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_bytes: int,
        allowed_content_types: set[str] | None = None,
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes
        self._allowed_types = allowed_content_types or _ALLOWED_CONTENT_TYPES

    async def download(
        self,
        url: str,
        workspace: JobWorkspace,
        relative_path: str,
    ) -> Path:
        host = (urlparse(url).hostname or "").lower()
        if not any(
            host == item or host.endswith(f".{item}")
            for item in _ALLOWED_DOWNLOAD_HOSTS
        ):
            raise MediaInvalidOutput("Stock download host is not allowed")
        partial = workspace.part_path(relative_path)
        total = 0
        try:
            async with self._client.stream("GET", url) as response:
                _raise_provider_status(response)
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type not in self._allowed_types:
                    raise MediaInvalidOutput("Stock response content type is invalid")
                try:
                    declared = int(response.headers.get("content-length", "0") or 0)
                except ValueError as exc:
                    raise MediaInvalidOutput(
                        "Stock response length is invalid"
                    ) from exc
                if declared > self._max_bytes:
                    raise MediaInvalidOutput("Stock response is too large")
                with partial.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self._max_bytes:
                            raise MediaInvalidOutput("Stock response is too large")
                        output.write(chunk)
            if total == 0:
                raise MediaInvalidOutput("Stock response is empty")
            return workspace.promote(relative_path)
        except MediaInvalidOutput:
            workspace.remove_partial(relative_path)
            raise
        except httpx.HTTPError as exc:
            workspace.remove_partial(relative_path)
            raise MediaTransientError("Stock download failed") from exc


def _raise_provider_status(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise MediaConfigurationError("Stock provider credentials are invalid")
    if response.status_code == 429 or response.status_code >= 500:
        raise MediaTransientError("Stock provider is temporarily unavailable")
    if response.is_error:
        raise MediaInvalidOutput("Stock provider rejected the request")
