"""CPU-bounded FFmpeg preview rendering and ffprobe validation."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.domain.channel_models import SubtitleStyle
from core.domain.errors import MediaInvalidOutput, MediaTimeoutError
from core.domain.media_models import (
    MediaInfo,
    PreparedScene,
    VisualAssetKind,
)


class FfprobeMediaProbe:
    def __init__(
        self,
        binary: str = "ffprobe",
        *,
        timeout_seconds: float = 30,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._runner = runner

    def probe(self, path: Path) -> MediaInfo:
        try:
            result = self._runner(
                [
                    self._binary,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,duration",
                    "-show_entries",
                    "format=duration,format_name",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
                timeout=self._timeout,
            )
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired as exc:
            raise MediaTimeoutError("Media probe timed out") from exc
        except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
            raise MediaInvalidOutput("Media probe failed") from exc
        streams = data.get("streams", [])
        video = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        audio = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        selected = video or audio
        if selected is None:
            raise MediaInvalidOutput("Media has no supported stream")
        duration_value = data.get("format", {}).get("duration") or selected.get(
            "duration"
        )
        try:
            duration_ms = round(float(duration_value) * 1000)
        except (TypeError, ValueError) as exc:
            raise MediaInvalidOutput("Media duration is unavailable") from exc
        return MediaInfo(
            duration_ms=duration_ms,
            codec=str(selected.get("codec_name") or ""),
            width=int(video["width"]) if video and video.get("width") else None,
            height=int(video["height"]) if video and video.get("height") else None,
            format_name=data.get("format", {}).get("format_name"),
            has_audio=audio is not None,
        )


class FfmpegPreviewRenderer:
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
        voice_path: Path,
        subtitle_path: Path,
        scenes: tuple[PreparedScene, ...],
        output_path: Path,
        aspect_ratio: str,
        subtitle_style: object,
        bgm_path: Path | None,
        workspace_root: Path | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        if not scenes:
            raise MediaInvalidOutput("Preview requires at least one scene")
        if not isinstance(subtitle_style, SubtitleStyle):
            raise MediaInvalidOutput("Subtitle style is invalid")
        width, height = (270, 480) if aspect_ratio == "9:16" else (854, 480)
        args = [self._binary, "-hide_banner", "-loglevel", "error", "-y"]
        filters: list[str] = []
        labels: list[str] = []
        for index, scene in enumerate(scenes):
            duration = (scene.end_ms - scene.start_ms) / 1000
            visual = scene.visual
            if visual.kind is VisualAssetKind.GENERATED_BACKGROUND:
                color = _scene_color(scene.order)
                args.extend(
                    [
                        "-f",
                        "lavfi",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        f"color=c={color}:s={width}x{height}:r=30",
                    ]
                )
            elif visual.kind is VisualAssetKind.IMAGE:
                assert visual.relative_path is not None
                visual_path = _visual_path(visual.relative_path, workspace_root)
                args.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", visual_path])
            else:
                assert visual.relative_path is not None
                visual_path = _visual_path(visual.relative_path, workspace_root)
                args.extend(
                    [
                        "-stream_loop",
                        "-1",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        visual_path,
                    ]
                )
            label = f"v{index}"
            labels.append(f"[{label}]")
            filters.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps=30,trim=duration={duration:.3f},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
        voice_index = len(scenes)
        args.extend(["-i", str(voice_path)])
        bgm_index: int | None = None
        if bgm_path is not None:
            bgm_index = voice_index + 1
            args.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        filters.append("".join(labels) + f"concat=n={len(scenes)}:v=1:a=0[vcat]")
        subtitle_filter = _subtitle_filter(subtitle_path, subtitle_style)
        filters.append(f"[vcat]{subtitle_filter}[vout]")
        if bgm_index is not None:
            filters.extend(
                [
                    f"[{bgm_index}:a]volume=0.12[bgm]",
                    f"[bgm][{voice_index}:a]sidechaincompress=threshold=0.02:ratio=8[ducked]",
                    f"[{voice_index}:a][ducked]amix=inputs=2:duration=first[aout]",
                ]
            )
            audio_map = "[aout]"
        else:
            audio_map = f"{voice_index}:a:0"
        total_seconds = scenes[-1].end_ms / 1000
        args.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                audio_map,
                "-t",
                f"{total_seconds:.3f}",
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
                "-b:a",
                "128k",
                "-threads",
                "2",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(output_path),
            ]
        )
        if heartbeat:
            heartbeat()
        try:
            self._runner(
                args,
                check=True,
                capture_output=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaTimeoutError("Preview render timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise MediaInvalidOutput("Preview render failed") from exc
        if heartbeat:
            heartbeat()


def _scene_color(order: int) -> str:
    palette = ("0x14213d", "0x264653", "0x3a506b", "0x5f0f40")
    return palette[(order - 1) % len(palette)]


def _visual_path(relative_path: str, workspace_root: Path | None) -> str:
    if workspace_root is None:
        return relative_path
    resolved_root = workspace_root.resolve()
    resolved = (resolved_root / relative_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise MediaInvalidOutput("Visual path escapes the workspace")
    return str(resolved)


def _subtitle_filter(path: Path, style: SubtitleStyle) -> str:
    escaped = path.resolve().as_posix()
    for character in ("\\", ":", "'", ",", ";", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}")
    alignment = {"top": 8, "center": 5, "bottom": 2}[style.position]
    primary = _ass_color(style.primary_color)
    outline = _ass_color(style.outline_color)
    force_style = (
        f"FontName={style.font_family},FontSize={style.font_size},"
        f"PrimaryColour={primary},OutlineColour={outline},"
        f"Outline={style.outline_width},Alignment={alignment}"
    )
    return f"subtitles=filename='{escaped}':force_style='{force_style}'"


def _ass_color(value: str) -> str:
    red, green, blue = value[1:3], value[3:5], value[5:7]
    return f"&H00{blue}{green}{red}"
