"""ffmpeg_ops -- thin subprocess wrapper over ``ffmpeg``/``ffprobe``.

Every function here shells out to the real binaries (resolved via PATH
by default, or an explicit path passed by the caller) and does nothing
else: no path validation, no domain knowledge of episodes/scenes/
dialogue lines. Callers (e.g.
:class:`~app.core.services.episode_audio_preview_service.EpisodeAudioPreviewService`)
own that context; this module only knows how to probe an audio file
and how to concatenate audio files with generated silence between
them.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class FfmpegError(Exception):
    """``ffmpeg``/``ffprobe`` could not be run, or exited non-zero."""


@dataclass(frozen=True)
class AudioStreamProbe:
    """The first audio stream's format info, as reported by ``ffprobe``."""

    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str | None
    duration_seconds: float
    bit_rate: int | None


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as err:
        raise FfmpegError(f"{cmd[0]!r} not found (is it on PATH?): {err}") from err
    if completed.returncode != 0:
        raise FfmpegError(
            f"{cmd[0]} exited {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed


def probe_audio(path: Path, *, ffprobe_path: str = "ffprobe") -> AudioStreamProbe:
    """Return the first audio stream's format info for the file at ``path``.

    Raises:
        FfmpegError: ``ffprobe`` could not be run, exited non-zero, or
            the file has no audio stream.
    """
    completed = _run(
        [
            ffprobe_path, "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ]
    )
    data = json.loads(completed.stdout)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise FfmpegError(f"No audio stream found in {path}")
    stream = streams[0]
    fmt = data.get("format", {})
    duration_raw = fmt.get("duration", stream.get("duration"))
    if duration_raw is None:
        raise FfmpegError(f"ffprobe reported no duration for {path}")
    bit_rate_raw = fmt.get("bit_rate")

    return AudioStreamProbe(
        codec_name=stream["codec_name"],
        sample_rate=int(stream["sample_rate"]),
        channels=int(stream["channels"]),
        channel_layout=stream.get("channel_layout"),
        duration_seconds=float(duration_raw),
        bit_rate=int(bit_rate_raw) if bit_rate_raw is not None else None,
    )


def run_ffmpeg(
    args: Sequence[str], *, ffmpeg_path: str = "ffmpeg", timeout: float | None = None
) -> None:
    """Run ``ffmpeg`` with ``args`` (excluding the binary name itself).

    Raises:
        FfmpegError: ``ffmpeg`` could not be run or exited non-zero.
    """
    _run([ffmpeg_path, *args], timeout=timeout)


def concat_audio_with_gaps(
    input_paths: Sequence[Path],
    gap_seconds: Sequence[float],
    output_path: Path,
    *,
    sample_rate: int = 44100,
    channels: int = 1,
    bitrate: str = "128k",
    ffmpeg_path: str = "ffmpeg",
    timeout: float | None = None,
) -> None:
    """Concatenate ``input_paths`` in order into one MP3 at ``output_path``.

    A generated silence segment of ``gap_seconds[i]`` seconds is
    inserted between ``input_paths[i]`` and ``input_paths[i + 1]`` --
    exactly one gap per boundary, never a gap before the first clip or
    after the last one. ``gap_seconds`` must therefore have exactly
    ``len(input_paths) - 1`` entries.

    Every clip (real and generated silence) is normalized to
    ``sample_rate``/``channels`` before concatenation, in a single
    deterministic ``ffmpeg`` invocation -- so the process either
    produces the whole file correctly or fails outright, never a
    partial/inconsistent result.

    Raises:
        ValueError: ``input_paths`` is empty, or ``gap_seconds`` has
            the wrong length.
        FfmpegError: ``ffmpeg`` could not be run or exited non-zero.
    """
    if len(input_paths) == 0:
        raise ValueError("input_paths must not be empty")
    if len(gap_seconds) != len(input_paths) - 1:
        raise ValueError(
            f"gap_seconds must have exactly {len(input_paths) - 1} entries "
            f"for {len(input_paths)} input_paths, got {len(gap_seconds)}"
        )

    channel_layout = "mono" if channels == 1 else "stereo"
    args: list[str] = ["-y"]
    filter_parts: list[str] = []
    labels: list[str] = []
    input_index = 0

    for i, clip_path in enumerate(input_paths):
        args += ["-i", str(clip_path)]
        label = f"a{input_index}"
        filter_parts.append(
            f"[{input_index}:a]aformat=sample_rates={sample_rate}:"
            f"channel_layouts={channel_layout}[{label}]"
        )
        labels.append(label)
        input_index += 1

        if i < len(gap_seconds):
            args += [
                "-f", "lavfi",
                "-t", f"{gap_seconds[i]:.6f}",
                "-i", f"anullsrc=r={sample_rate}:cl={channel_layout}",
            ]
            label = f"a{input_index}"
            filter_parts.append(f"[{input_index}:a]anull[{label}]")
            labels.append(label)
            input_index += 1

    concat_inputs = "".join(f"[{label}]" for label in labels)
    filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(labels)}:v=0:a=1[out]"

    args += [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(output_path),
    ]
    run_ffmpeg(args, ffmpeg_path=ffmpeg_path, timeout=timeout)
