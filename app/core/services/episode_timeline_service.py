"""EpisodeTimelineService -- Milestone 10 Phase 3: a read-only,
multi-track readiness report for an Episode's eventual audio master.

Generalizes Phase 1's single dialogue track
(:class:`~app.core.services.episode_audio_assembly_service.EpisodeAudioAssemblyService`)
into a report that also honestly states what's known about the
episode's music track, and explicitly states what is *not yet known*
about an SFX/ambience track (there is none -- see
:data:`SfxTrackStatus`).

This service never renders, generates, mixes, or writes anything. It
has **zero** DB write capability, **zero** filesystem write
capability, and **zero** generation capability -- it only composes
already-computed Phase 1 output with plain read queries against
already-existing ``Asset``/``Scene``/``Song`` data. The dialogue track
is *delegated to* Phase 1, never re-derived: this module holds no
DialogueLine ordering, ``final_line_voice`` resolution, song-scene
exclusion, or gap-timing logic of its own -- see
:meth:`EpisodeTimelineService.build_timeline`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.db.enums import ApprovalStatus
from app.core.models import Asset, Episode, Scene, Song
from app.core.models.asset import ROLE_FINAL_MUSIC
from app.core.services.episode_audio_assembly_service import (
    EpisodeAssemblyReport,
    EpisodeAudioAssemblyService,
)
from app.core.services.exceptions import NotFoundError


class MusicTrackStatus(str, Enum):
    """Where the episode's produced song audio actually stands.

    Deliberately distinguishes MISSING from PRESENT_NOT_APPROVED --
    an unapproved ``final_music`` Asset must never be silently treated
    as production-ready, matching how Phase 1 already refuses to treat
    an unapproved ``final_line_voice`` as ready.
    """

    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    PRESENT_NOT_APPROVED = "present_not_approved"
    PRESENT_AND_APPROVED = "present_and_approved"


class SfxTrackStatus(str, Enum):
    """SFX/ambience has no representation anywhere in this project yet.

    UNSUPPORTED is the only value that will ever exist here until a
    real SFX data model/workflow is designed and founder-approved --
    this is an honest statement of current system capability, never a
    placeholder for "zero SFX items, and that's fine."
    """

    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MusicTrack:
    """The music track's real, currently-known state -- never guessed."""

    status: MusicTrackStatus
    asset_id: uuid.UUID | None
    song_exists: bool
    song_scene_count: int
    topology_ambiguous: bool


@dataclass(frozen=True)
class SfxTrack:
    status: SfxTrackStatus = SfxTrackStatus.UNSUPPORTED


@dataclass(frozen=True)
class EpisodeTimelineReport:
    """One Episode's full multi-track readiness snapshot.

    ``is_mix_ready`` is computed, never persisted -- recomputing this
    report must always be safe and side-effect-free.
    """

    episode_id: uuid.UUID
    dialogue_report: EpisodeAssemblyReport
    music_track: MusicTrack
    sfx_track: SfxTrack
    is_mix_ready: bool


class EpisodeTimelineService:
    """Builds a multi-track :class:`EpisodeTimelineReport` for one Episode."""

    def __init__(
        self,
        assembly_service: EpisodeAudioAssemblyService | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._config = config or get_config()
        self._assembly_service = assembly_service or EpisodeAudioAssemblyService(
            config=self._config
        )

    def build_timeline(self, session: Session, episode_id: uuid.UUID) -> EpisodeTimelineReport:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        # The dialogue track is entirely Phase 1's report, untouched --
        # this service never re-derives ordering, validation, or the
        # gap-timing policy.
        dialogue_report = self._assembly_service.build_report(session, episode_id)

        music_track = self._build_music_track(session, episode)
        sfx_track = SfxTrack()

        is_mix_ready = dialogue_report.is_assembly_ready and music_track.status in (
            MusicTrackStatus.NOT_APPLICABLE,
            MusicTrackStatus.PRESENT_AND_APPROVED,
        )

        return EpisodeTimelineReport(
            episode_id=episode_id,
            dialogue_report=dialogue_report,
            music_track=music_track,
            sfx_track=sfx_track,
            is_mix_ready=is_mix_ready,
        )

    def _build_music_track(self, session: Session, episode: Episode) -> MusicTrack:
        song_scene_count = (
            session.query(Scene)
            .filter_by(episode_id=episode.id, is_song_scene=True)
            .count()
        )
        # The current schema has exactly one Song row per Episode, with
        # no per-scene link -- more than one song scene makes "which
        # scene does the song belong at" genuinely unanswerable from
        # today's data. Flagged, never guessed; see module docstring
        # and app.core.models.episode.Song's own docstring.
        topology_ambiguous = song_scene_count > 1
        song_exists = (
            session.query(Song).filter_by(episode_id=episode.id).one_or_none() is not None
        )

        if not episode.includes_song:
            return MusicTrack(
                status=MusicTrackStatus.NOT_APPLICABLE,
                asset_id=None,
                song_exists=song_exists,
                song_scene_count=song_scene_count,
                topology_ambiguous=topology_ambiguous,
            )

        # Mirrors ProductionChecklistService._latest_role_asset exactly
        # (production_checklist_service.py) -- the same "most recently
        # created final_music Asset for this episode" lookup already
        # used to gate the Music stage's readiness, so both services
        # agree on which Asset is "the" current final music.
        asset = (
            session.query(Asset)
            .filter_by(episode_id=episode.id, role=ROLE_FINAL_MUSIC)
            .order_by(Asset.created_at.desc())
            .first()
        )
        if asset is None:
            status = MusicTrackStatus.MISSING
        elif asset.approval_status == ApprovalStatus.APPROVED:
            status = MusicTrackStatus.PRESENT_AND_APPROVED
        else:
            status = MusicTrackStatus.PRESENT_NOT_APPROVED

        return MusicTrack(
            status=status,
            asset_id=asset.id if asset is not None else None,
            song_exists=song_exists,
            song_scene_count=song_scene_count,
            topology_ambiguous=topology_ambiguous,
        )
