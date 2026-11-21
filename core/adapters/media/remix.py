"""Bounded yt-dlp ingestion and CPU-safe FFmpeg remix rendering."""

from __future__ import annotations

import ipaddress
import socket
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.adapters.media.workspace import JobWorkspace
from core.domain.errors import (
    MediaConfigurationError,
    MediaInvalidOutput,
    MediaTimeoutError,
    MediaTransientError,
)
from core.domain.models import RemixClipSnapshot


def _system_resolver(hostname: str) -> tuple[str, ...]:
    try:
        return tuple(
            dict.fromkeys(
                str(item[4][0])
                for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            )
        )
    except socket.gaierror as exc:
        raise MediaTransientError("Remix source host could not be resolved") from exc


def validate_public_source_url(
    url: str,
    resolver: Callable[[str], Iterable[str]] = _system_resolver,
) -> None:
    """Reject credentials and any destination resolving outside public IP space."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise MediaConfigurationError("Remix source URL is invalid")
    addresses = tuple(resolver(parsed.hostname))
    if not addresses:
        raise MediaTransientError("Remix source host could not be resolved")
    try:
        if any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise MediaConfigurationError("Remix source host is not public")
    except ValueError as exc:
        raise MediaConfigurationError("Remix source resolution is invalid") from exc


class YtDlpSourceDownloader:
    """Download one public source to a revision-contained atomic path."""

    def __init__(
        self,
        binary: str = "yt-dlp",
        *,
        timeout_seconds: float = 300,
        max_bytes: int = 1024 * 1024 * 1024,
        runner: Callable[..., Any] = subprocess.run,
        resolver: Callable[[str], Iterable[str]] = _system_resolver,
    ) -> None:
        if timeout_seconds <= 0 or max_bytes <= 0:
            raise MediaConfigurationError("Remix download limits are invalid")
        self._binary = binary
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._runner = runner
        self._resolver = resolver

    def download(
        self,
        url: str,
        workspace: JobWorkspace,
        relative_path: str,
        heartbeat: Callable[[], None] | None = None,
    ) -> Path:
        validate_public_source_url(url, self._resolver)
        partial = workspace.part_path(relative_path)
        workspace.remove_partial(relative_path)
        args = [
            self._binary,
            "--no-playlist",
            "--no-part",
            "--socket-timeout",
            "30",
            "--max-filesize",
            str(self._max_bytes),
            "--format",
            "best[height<=1080][ext=mp4]/best[height<=1080]",
            "--output",
            str(partial),
            url,
        ]
        if heartbeat:
            heartbeat()
        try:
            self._runner(
                args,
                check=True,
                capture_output=True,
                timeout=self._timeout,
            )
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise MediaInvalidOutput("Remix source download produced no media")
            if partial.stat().st_size > self._max_bytes:
                raise MediaConfigurationError("Remix source exceeds the size limit")
            output = workspace.promote(relative_path)
        except subprocess.TimeoutExpired as exc:
            workspace.remove_partial(relative_path)
            raise MediaTimeoutError("Remix source download timed out") from exc
        except subprocess.CalledProcessError as exc:
            workspace.remove_partial(relative_path)
            raise MediaTransientError("Remix source download failed") from exc
        except OSError as exc:
            workspace.remove_partial(relative_path)
            raise MediaConfigurationError("Remix downloader is unavailable") from exc
        except Exception:
            workspace.remove_partial(relative_path)
            raise
        if heartbeat:
            heartbeat()
        return output


class FfmpegRemixProcessor:
    """Trim and normalize one source clip into the common preview profile."""

    def __init__(
        self,
        binary: str = "ffmpeg",
        *,
        timeout_seconds: float = 300,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._runner = runner

    def normalize(
        self,
        *,
        source_path: Path,
        output_path: Path,
        clip: RemixClipSnapshot,
        aspect_ratio: str,
        has_audio: bool,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        width, height = _preview_dimensions(aspect_ratio)
        duration = (clip.end_seconds - clip.start_seconds) / clip.speed
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
            if clip.crop_mode == "fill"
            else f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        video_steps = [
            f"trim=start={clip.start_seconds:.3f}:end={clip.end_seconds:.3f}",
            f"setpts=(PTS-STARTPTS)/{clip.speed:g}",
            scale,
        ]
        if clip.mirror:
            video_steps.append("hflip")
        video_steps.extend(("fps=30", "format=yuv420p"))
        filters = [f"[0:v]{','.join(video_steps)}[vout]"]
        args = [
            self._binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
        ]
        if has_audio:
            filters.append(
                f"[0:a]atrim=start={clip.start_seconds:.3f}:end={clip.end_seconds:.3f},"
                f"asetpts=PTS-STARTPTS,{_atempo_filter(clip.speed)}[aout]"
            )
            audio_map = "[aout]"
        else:
            args.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
            )
            audio_map = "1:a:0"
        args.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                audio_map,
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-threads",
                "2",
                "-f",
                "mp4",
                str(output_path),
            ]
        )
        _run_ffmpeg(
            self._runner,
            args,
            self._timeout,
            "Remix clip normalization",
            heartbeat,
        )


class FfmpegRemixPreviewRenderer:
    """Concatenate normalized clips in request order into one web preview."""

    def __init__(
        self,
        binary: str = "ffmpeg",
        *,
        timeout_seconds: float = 300,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._runner = runner

    def render(
        self,
        *,
        clips: tuple[Path, ...],
        output_path: Path,
        aspect_ratio: str,
        bgm_path: Path | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        if not clips:
            raise MediaInvalidOutput("Remix preview requires at least one clip")
        width, height = _preview_dimensions(aspect_ratio)
        args = [self._binary, "-hide_banner", "-loglevel", "error", "-y"]
        for clip in clips:
            args.extend(["-i", str(clip)])
        inputs = "".join(f"[{index}:v][{index}:a]" for index in range(len(clips)))
        filters = [f"{inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]"]
        audio_map = "[aout]"
        if bgm_path is not None:
            args.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
            filters.extend(
                (
                    f"[{len(clips)}:a]volume=0.12[bgm]",
                    "[aout][bgm]amix=inputs=2:duration=first[mixed]",
                )
            )
            audio_map = "[mixed]"
        args.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                audio_map,
                "-s",
                f"{width}x{height}",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-threads",
                "2",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(output_path),
            ]
        )
        _run_ffmpeg(
            self._runner,
            args,
            self._timeout,
            "Remix preview render",
            heartbeat,
        )


def _preview_dimensions(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 854, 480
    if aspect_ratio == "9:16":
        return 270, 480
    raise MediaConfigurationError("Remix aspect ratio is unsupported")


def _atempo_filter(speed: float) -> str:
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={value:g}" for value in factors)


def _run_ffmpeg(
    runner: Callable[..., Any],
    args: list[str],
    timeout: float,
    operation: str,
    heartbeat: Callable[[], None] | None,
) -> None:
    if heartbeat:
        heartbeat()
    try:
        runner(args, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaTimeoutError(f"{operation} timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise MediaInvalidOutput(f"{operation} failed") from exc
    except OSError as exc:
        raise MediaConfigurationError("FFmpeg is unavailable") from exc
    if heartbeat:
        heartbeat()
