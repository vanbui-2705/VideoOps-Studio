"""CPU-bounded FFmpeg composition for approved 1080p masters."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.adapters.media.ffmpeg_preview import (
    _scene_color,
    _subtitle_filter,
    _visual_path,
)
from core.domain.channel_models import SubtitleStyle
from core.domain.errors import (
    MediaConfigurationError,
    MediaInvalidOutput,
    MediaTimeoutError,
)
from core.domain.media_models import PreparedScene, VisualAssetKind
from core.domain.models import RemixClipSnapshot


class FfmpegMasterRenderer:
    def __init__(
        self,
        binary: str = "ffmpeg",
        *,
        timeout_seconds: float = 900,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._binary = binary
        self._timeout = timeout_seconds
        self._runner = runner

    def render_story(
        self,
        *,
        voice_path: Path,
        subtitle_path: Path,
        scenes: tuple[PreparedScene, ...],
        source_paths: tuple[Path, ...],
        output_path: Path,
        aspect_ratio: str,
        subtitle_style: SubtitleStyle,
        bgm_path: Path | None,
        workspace_root: Path,
        preset: str,
        crf: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        if not scenes or len(source_paths) != len(scenes):
            raise MediaInvalidOutput("Story master requires prepared scenes")
        width, height = _master_dimensions(aspect_ratio)
        args = [self._binary, "-hide_banner", "-loglevel", "error", "-y"]
        filters: list[str] = []
        labels: list[str] = []
        for index, scene in enumerate(scenes):
            duration = (scene.end_ms - scene.start_ms) / 1000
            visual = scene.visual
            if visual.kind is VisualAssetKind.GENERATED_BACKGROUND:
                args.extend(
                    [
                        "-f",
                        "lavfi",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        f"color=c={_scene_color(scene.order)}:s={width}x{height}:r=30",
                    ]
                )
            elif visual.kind is VisualAssetKind.IMAGE:
                assert visual.relative_path is not None
                args.extend(
                    [
                        "-loop",
                        "1",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        _visual_path(visual.relative_path, workspace_root),
                    ]
                )
            else:
                assert visual.relative_path is not None
                args.extend(
                    [
                        "-stream_loop",
                        "-1",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        _visual_path(visual.relative_path, workspace_root),
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
        filters.append(f"[vcat]{_subtitle_filter(subtitle_path, subtitle_style)}[vout]")
        audio_map = _mix_audio(filters, voice_index, bgm_index)
        total_seconds = scenes[-1].end_ms / 1000
        _append_output(
            args,
            filters,
            audio_map,
            output_path,
            width,
            height,
            total_seconds,
            preset,
            crf,
        )
        _run_ffmpeg(
            self._runner,
            args,
            self._timeout,
            "Story master render",
            heartbeat,
        )

    def render_remix(
        self,
        *,
        sources: tuple[tuple[Path, RemixClipSnapshot, bool], ...],
        output_path: Path,
        aspect_ratio: str,
        bgm_path: Path | None,
        preset: str,
        crf: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        if not sources:
            raise MediaInvalidOutput("Remix master requires source clips")
        width, height = _master_dimensions(aspect_ratio)
        args = [self._binary, "-hide_banner", "-loglevel", "error", "-y"]
        filters: list[str] = []
        concat_inputs: list[str] = []
        total_seconds = 0.0
        input_index = 0
        for output_index, (path, clip, has_audio) in enumerate(sources):
            source_index = input_index
            args.extend(["-i", str(path)])
            input_index += 1
            duration = (clip.end_seconds - clip.start_seconds) / clip.speed
            total_seconds += duration
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
            filters.append(
                f"[{source_index}:v]{','.join(video_steps)}[v{output_index}]"
            )
            if has_audio:
                filters.append(
                    f"[{source_index}:a]atrim=start={clip.start_seconds:.3f}:"
                    f"end={clip.end_seconds:.3f},asetpts=PTS-STARTPTS,"
                    f"{_atempo_filter(clip.speed)}[a{output_index}]"
                )
            else:
                silent_index = input_index
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
                input_index += 1
                filters.append(
                    f"[{silent_index}:a]atrim=duration={duration:.3f},"
                    f"asetpts=PTS-STARTPTS[a{output_index}]"
                )
            concat_inputs.append(f"[v{output_index}][a{output_index}]")
        filters.append(
            "".join(concat_inputs) + f"concat=n={len(sources)}:v=1:a=1[vout][aremix]"
        )
        audio_map = "[aremix]"
        if bgm_path is not None:
            bgm_index = input_index
            args.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
            filters.extend(
                (
                    f"[{bgm_index}:a]volume=0.12[bgm]",
                    "[aremix][bgm]amix=inputs=2:duration=first[aout]",
                )
            )
            audio_map = "[aout]"
        _append_output(
            args,
            filters,
            audio_map,
            output_path,
            width,
            height,
            total_seconds,
            preset,
            crf,
        )
        _run_ffmpeg(
            self._runner,
            args,
            self._timeout,
            "Remix master render",
            heartbeat,
        )


def _master_dimensions(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "9:16":
        return 1080, 1920
    raise MediaConfigurationError("Master aspect ratio is unsupported")


def _mix_audio(filters: list[str], voice_index: int, bgm_index: int | None) -> str:
    if bgm_index is None:
        return f"{voice_index}:a:0"
    filters.extend(
        (
            f"[{bgm_index}:a]volume=0.12[bgm]",
            f"[bgm][{voice_index}:a]sidechaincompress=threshold=0.02:ratio=8[ducked]",
            f"[{voice_index}:a][ducked]amix=inputs=2:duration=first[aout]",
        )
    )
    return "[aout]"


def _append_output(
    args: list[str],
    filters: list[str],
    audio_map: str,
    output_path: Path,
    width: int,
    height: int,
    duration_seconds: float,
    preset: str,
    crf: int,
) -> None:
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            audio_map,
            "-t",
            f"{duration_seconds:.3f}",
            "-s",
            f"{width}x{height}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
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
