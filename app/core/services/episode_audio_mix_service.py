"""EpisodeAudioMixService -- Milestone 10 Phase 5: the first real
Episode 001 dialogue+song mix preview.

Composes, unchanged:

- :class:`~app.core.services.episode_timeline_service.EpisodeTimelineService`
  for the mix-readiness gate and the resolved ``final_music`` Asset.
- :class:`~app.core.services.episode_audio_assembly_service.EpisodeAudioAssemblyService`
  for the ordered, validated spoken-dialogue sources (song scenes
  already excluded -- never re-derived here).
- :func:`app.core.ffmpeg_ops.concat_audio_with_gaps` for the actual
  concatenation. That function already normalizes every input
  (regardless of its own sample rate/channel layout) to the target
  format via a per-input ``aformat`` filter, so mono dialogue clips
  and the 48kHz stereo song both convert to one consistent 44.1kHz
  stereo output with no changes needed there.

This module adds exactly one new piece of domain logic: where, in the
already-ordered spoken-source list, the song scene sits, and what gap
policy applies around that insertion point. Everything else is
delegation -- this module holds no dialogue ordering, ``final_line_voice``
resolution, song-scene exclusion, or per-clip validation logic of its
own.

Read/render only: no DB writes, no Asset/GenerationJob creation, no
provider or TTS calls, no modification of any source Asset.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core import ffmpeg_ops
from app.core.db.enums import ApprovalStatus
from app.core.models import Asset, Scene
from app.core.models.asset import ROLE_FINAL_MUSIC
from app.core.services.episode_audio_assembly_service import (
    DEFAULT_SAME_SCENE_GAP_SECONDS,
    DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
    EpisodeAudioAssemblyService,
)
from app.core.services.episode_timeline_service import EpisodeTimelineService
from app.core.services.exceptions import AudioRenderError
from app.core.services.storage_service import StorageService

TARGET_SAMPLE_RATE = 44100
TARGET_CHANNELS = 2
TARGET_BITRATE = "128k"


@dataclass(frozen=True)
class MixPreviewResult:
    """What actually happened, measured from the real output file --
    never predicted or copied from the DB."""

    episode_id: uuid.UUID
    output_path: Path
    spoken_clip_count: int
    same_scene_gap_count: int
    scene_boundary_gap_count: int  # includes the 2 song-transition gaps
    song_transition_gap_count: int
    total_spoken_duration_seconds: float
    song_duration_seconds: float
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


class EpisodeAudioMixService:
    """Renders the real dialogue+song mix preview for one Episode."""

    def __init__(
        self,
        timeline_service: EpisodeTimelineService | None = None,
        assembly_service: EpisodeAudioAssemblyService | None = None,
        storage: StorageService | None = None,
        config: AppConfig | None = None,
        same_scene_gap_seconds: float = DEFAULT_SAME_SCENE_GAP_SECONDS,
        scene_boundary_gap_seconds: float = DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        self._config = config or get_config()
        self._storage = storage or StorageService(self._config)
        self._assembly_service = assembly_service or EpisodeAudioAssemblyService(
            config=self._config,
            same_scene_gap_seconds=same_scene_gap_seconds,
            scene_boundary_gap_seconds=scene_boundary_gap_seconds,
        )
        self._timeline_service = timeline_service or EpisodeTimelineService(
            assembly_service=self._assembly_service, config=self._config
        )
        self._same_scene_gap = same_scene_gap_seconds
        self._scene_boundary_gap = scene_boundary_gap_seconds
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path

    def render_mix_preview(
        self, session: Session, episode_id: uuid.UUID, output_path: Path
    ) -> MixPreviewResult:
        """Render ``output_path`` and return measurements of the real result.

        Raises:
            AudioRenderError: The episode is not mix-ready, the song
                topology is ambiguous, the resolved music Asset can't
                be uniquely determined or doesn't exist on disk, or
                ``ffmpeg``/``ffprobe`` failed.
        """
        timeline = self._timeline_service.build_timeline(session, episode_id)

        if not timeline.is_mix_ready:
            raise AudioRenderError(
                f"Episode {episode_id} is not mix-ready: "
                f"dialogue_ready={timeline.dialogue_report.is_assembly_ready}, "
                f"music_status={timeline.music_track.status.value}."
            )
        if timeline.music_track.topology_ambiguous:
            raise AudioRenderError(
                f"Episode {episode_id} has an ambiguous song-scene topology "
                f"({timeline.music_track.song_scene_count} song scenes for one "
                "Song row) -- refusing to guess where the song belongs."
            )

        music_path = self._resolve_music_path(session, episode_id)
        song_scene_order_index = self._resolve_song_scene_order_index(session, episode_id)

        sources = timeline.dialogue_report.sources
        split_index = next(
            (i for i, s in enumerate(sources) if s.scene_order_index > song_scene_order_index),
            len(sources),
        )
        before, after = sources[:split_index], sources[split_index:]
        if not before or not after:
            raise AudioRenderError(
                f"Song scene (order_index={song_scene_order_index}) has no spoken "
                f"dialogue on one side (before={len(before)}, after={len(after)}) -- "
                "refusing to guess placement at an episode boundary."
            )

        input_paths: list[Path] = []
        segment_kind: list[str] = []
        gap_seconds: list[float] = []
        is_same_scene_flags: list[bool] = []

        def _append_dialogue_run(run: list) -> None:
            for i, source in enumerate(run):
                if source.absolute_path is None:
                    raise AudioRenderError(
                        "Assembly-ready report contained an unresolved source path "
                        f"(dialogue_line_id={source.dialogue_line_id})."
                    )
                input_paths.append(source.absolute_path)
                segment_kind.append("dialogue")
                if i < len(run) - 1:
                    same = source.scene_id == run[i + 1].scene_id
                    gap_seconds.append(self._same_scene_gap if same else self._scene_boundary_gap)
                    is_same_scene_flags.append(same)

        _append_dialogue_run(before)
        gap_seconds.append(self._scene_boundary_gap)  # transition into the song
        is_same_scene_flags.append(False)
        input_paths.append(music_path)
        segment_kind.append("song")
        gap_seconds.append(self._scene_boundary_gap)  # transition out of the song
        is_same_scene_flags.append(False)
        _append_dialogue_run(after)

        try:
            probes = [
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
            raise AudioRenderError(f"ffmpeg mix render failed: {err}") from err

        total_spoken_duration = sum(
            probe.duration_seconds
            for probe, kind in zip(probes, segment_kind)
            if kind == "dialogue"
        )
        song_duration = next(
            probe.duration_seconds
            for probe, kind in zip(probes, segment_kind)
            if kind == "song"
        )
        total_gap = sum(gap_seconds)

        return MixPreviewResult(
            episode_id=episode_id,
            output_path=output_path,
            spoken_clip_count=len(sources),
            same_scene_gap_count=is_same_scene_flags.count(True),
            scene_boundary_gap_count=is_same_scene_flags.count(False),
            song_transition_gap_count=2,
            total_spoken_duration_seconds=total_spoken_duration,
            song_duration_seconds=song_duration,
            total_gap_seconds=total_gap,
            expected_duration_seconds=total_spoken_duration + song_duration + total_gap,
            measured_duration_seconds=output_probe.duration_seconds,
            codec_name=output_probe.codec_name,
            sample_rate=output_probe.sample_rate,
            channels=output_probe.channels,
            bit_rate=output_probe.bit_rate,
            file_size_bytes=output_path.stat().st_size,
        )

    def _resolve_music_path(self, session: Session, episode_id: uuid.UUID) -> Path:
        # Stricter than EpisodeTimelineService's own "most recent" lookup
        # on purpose: a status report may reasonably pick "the latest"
        # candidate, but a render must never silently choose among
        # multiple approved final_music Assets -- that ambiguity has to
        # be refused, not resolved by an arbitrary tiebreak.
        approved_music_assets = (
            session.query(Asset)
            .filter_by(episode_id=episode_id, role=ROLE_FINAL_MUSIC, approval_status=ApprovalStatus.APPROVED)
            .all()
        )
        if len(approved_music_assets) != 1:
            raise AudioRenderError(
                f"Expected exactly 1 approved final_music Asset for episode {episode_id}, "
                f"found {len(approved_music_assets)} -- refusing to guess which one to mix."
            )
        asset = approved_music_assets[0]
        music_path = self._storage.resolve_managed_path(asset.relative_path)
        if not music_path.is_file():
            raise AudioRenderError(
                f"final_music Asset {asset.id} file does not exist on disk: {music_path}"
            )
        return music_path

    def _resolve_song_scene_order_index(self, session: Session, episode_id: uuid.UUID) -> int:
        song_scenes = (
            session.query(Scene).filter_by(episode_id=episode_id, is_song_scene=True).all()
        )
        if len(song_scenes) != 1:
            raise AudioRenderError(
                f"Expected exactly 1 song scene for episode {episode_id}, "
                f"found {len(song_scenes)} -- refusing to guess song placement."
            )
        return song_scenes[0].order_index
