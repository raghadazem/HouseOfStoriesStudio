"""EpisodeAudioPreviewService -- Milestone 10 Phase 2: render one real
dialogue-only preview MP3 for an Episode.

Consumes :class:`~app.core.services.episode_audio_assembly_service.EpisodeAudioAssemblyService`'s
read-model report (Phase 1) and turns it into an actual file on disk
via :mod:`app.core.ffmpeg_ops` -- concatenating each validated final
voice clip in scene/line order, with a generated silence gap between
consecutive lines (the same-scene/scene-boundary gap policy Phase 1
already predicts against, so the real render matches that prediction).

Deliberately narrow scope: no TTS/provider calls, no DB writes, no
``GenerationJob``/``EpisodeAudioRender`` rows. This service only reads
already-approved data and writes one audio file; every field on
:class:`PreviewRenderResult` is measured from the real files ffmpeg
touched, never invented.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core import ffmpeg_ops
from app.core.services.episode_audio_assembly_service import (
    DEFAULT_SAME_SCENE_GAP_SECONDS,
    DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
    EpisodeAudioAssemblyService,
)
from app.core.services.exceptions import AudioRenderError

TARGET_SAMPLE_RATE = 44100
TARGET_CHANNELS = 1
TARGET_BITRATE = "128k"


@dataclass(frozen=True)
class PreviewRenderResult:
    """What actually happened, measured from the real output file --
    never predicted or copied from the DB."""

    episode_id: uuid.UUID
    output_path: Path
    clip_count: int
    same_scene_gap_count: int
    scene_boundary_gap_count: int
    total_clip_duration_seconds: float
    total_gap_seconds: float
    expected_duration_seconds: float
    measured_duration_seconds: float
    codec_name: str
    sample_rate: int
    channels: int
    bit_rate: int | None
    file_size_bytes: int

    @property
    def duration_delta_seconds(self) -> float:
        return self.measured_duration_seconds - self.expected_duration_seconds


class EpisodeAudioPreviewService:
    """Renders a real dialogue-only preview MP3 for one Episode."""

    def __init__(
        self,
        assembly_service: EpisodeAudioAssemblyService | None = None,
        config: AppConfig | None = None,
        same_scene_gap_seconds: float = DEFAULT_SAME_SCENE_GAP_SECONDS,
        scene_boundary_gap_seconds: float = DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        self._config = config or get_config()
        self._assembly_service = assembly_service or EpisodeAudioAssemblyService(
            config=self._config,
            same_scene_gap_seconds=same_scene_gap_seconds,
            scene_boundary_gap_seconds=scene_boundary_gap_seconds,
        )
        self._same_scene_gap = same_scene_gap_seconds
        self._scene_boundary_gap = scene_boundary_gap_seconds
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path

    def render_preview(
        self, session: Session, episode_id: uuid.UUID, output_path: Path
    ) -> PreviewRenderResult:
        """Render ``output_path`` and return measurements of the real result.

        Raises:
            AudioRenderError: The episode is not assembly-ready (some
                spoken line has no valid final take), or ``ffmpeg``/
                ``ffprobe`` failed.
        """
        report = self._assembly_service.build_report(session, episode_id)
        if not report.is_assembly_ready:
            raise AudioRenderError(
                f"Episode {episode_id} is not assembly-ready: "
                f"{len(report.invalid_sources)} invalid source(s) of "
                f"{report.spoken_line_count} spoken line(s)."
            )

        sources = report.sources
        input_paths: list[Path] = []
        for source in sources:
            # is_assembly_ready already guarantees every source resolved
            # to a real file; this can never actually fire, but a
            # rendered file silently pointed at "None" is not an
            # acceptable failure mode for this service to risk.
            if source.absolute_path is None:
                raise AudioRenderError(
                    f"Assembly-ready report contained an unresolved source "
                    f"path (dialogue_line_id={source.dialogue_line_id})."
                )
            input_paths.append(source.absolute_path)

        is_same_scene = [
            sources[i].scene_id == sources[i + 1].scene_id for i in range(len(sources) - 1)
        ]
        gap_seconds = [
            self._same_scene_gap if same else self._scene_boundary_gap for same in is_same_scene
        ]

        try:
            source_probes = [
                ffmpeg_ops.probe_audio(path, ffprobe_path=self._ffprobe_path)
                for path in input_paths
            ]
        except ffmpeg_ops.FfmpegError as err:
            raise AudioRenderError(f"Failed to probe source audio: {err}") from err

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            ffmpeg_ops.concat_audio_with_gaps(
                input_paths,
                gap_seconds,
                output_path,
                sample_rate=TARGET_SAMPLE_RATE,
                channels=TARGET_CHANNELS,
                bitrate=TARGET_BITRATE,
                ffmpeg_path=self._ffmpeg_path,
            )
            output_probe = ffmpeg_ops.probe_audio(output_path, ffprobe_path=self._ffprobe_path)
        except ffmpeg_ops.FfmpegError as err:
            raise AudioRenderError(f"ffmpeg render failed: {err}") from err

        total_clip_duration = sum(probe.duration_seconds for probe in source_probes)
        total_gap = sum(gap_seconds)

        return PreviewRenderResult(
            episode_id=episode_id,
            output_path=output_path,
            clip_count=len(sources),
            same_scene_gap_count=is_same_scene.count(True),
            scene_boundary_gap_count=is_same_scene.count(False),
            total_clip_duration_seconds=total_clip_duration,
            total_gap_seconds=total_gap,
            expected_duration_seconds=total_clip_duration + total_gap,
            measured_duration_seconds=output_probe.duration_seconds,
            codec_name=output_probe.codec_name,
            sample_rate=output_probe.sample_rate,
            channels=output_probe.channels,
            bit_rate=output_probe.bit_rate,
            file_size_bytes=output_path.stat().st_size,
        )
