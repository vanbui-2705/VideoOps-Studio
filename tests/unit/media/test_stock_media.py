from pathlib import Path

import httpx
import pytest

from core.adapters.media.stock_http import (
    BoundedStockDownloader,
    PexelsStockProvider,
    PixabayStockProvider,
)
from core.adapters.media.workspace import JobWorkspace
from core.application.media_ports import StockSearchRequest
from core.domain.errors import MediaInvalidOutput


@pytest.mark.asyncio
async def test_pexels_selects_orientation_and_keeps_public_provenance() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "pexels-key"
        assert request.url.params["orientation"] == "portrait"
        return httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "id": 42,
                        "url": "https://www.pexels.com/video/42/",
                        "video_files": [
                            {
                                "link": "https://videos.pexels.com/video-files/42.mp4",
                                "file_type": "video/mp4",
                                "width": 1080,
                                "height": 1920,
                                "quality": "hd",
                            }
                        ],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        candidate = await PexelsStockProvider("pexels-key", client).search(
            StockSearchRequest(("AI", "future"), "9:16", 1)
        )

    assert candidate is not None
    assert candidate.provider == "pexels"
    assert candidate.provider_id == "42"
    assert candidate.width == 1080
    assert candidate.license_reference == "https://www.pexels.com/license/"
    assert "pexels-key" not in repr(candidate)


@pytest.mark.asyncio
async def test_pixabay_returns_none_when_no_video_matches() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"hits": []})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await PixabayStockProvider("pixabay-key", client).search(
            StockSearchRequest(("technology",), "16:9", 1)
        )

    assert result is None


@pytest.mark.asyncio
async def test_bounded_downloader_rejects_invalid_type_and_oversized_body(
    tmp_path: Path,
) -> None:
    workspace = JobWorkspace(tmp_path, "job", 1)

    async def invalid_type(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, text="bad")

    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid_type)) as client:
        downloader = BoundedStockDownloader(client, max_bytes=10)
        with pytest.raises(MediaInvalidOutput, match="content type"):
            await downloader.download(
                "https://videos.pexels.com/file.mp4",
                workspace,
                "visuals/scene-1.mp4",
            )

    async def too_large(request):
        return httpx.Response(
            200,
            headers={"content-type": "video/mp4", "content-length": "11"},
            content=b"x" * 11,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(too_large)) as client:
        downloader = BoundedStockDownloader(client, max_bytes=10)
        with pytest.raises(MediaInvalidOutput, match="large"):
            await downloader.download(
                "https://videos.pexels.com/file.mp4",
                workspace,
                "visuals/scene-1.mp4",
            )
    assert not workspace.part_path("visuals/scene-1.mp4").exists()
