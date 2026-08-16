"""EpisodeAudioAssemblyService — Milestone 10 Phase 1: a read-only model
answering "give me every production-ready final spoken voice Asset for
an Episode, in deterministic playback order."

This service has **zero generation capability** and **zero DB write
capability**. It only resolves and validates already-produced,
already-approved ``final_line_voice`` Assets — it never calls an
:class:`~app.core.ai.provider_interface.AIProvider`, never touches
:class:`~app.core.ai.orchestrator.AIOrchestrator`, and never imports
anything from ``app.core.ai.generation_runner`` or
``app.core.ai.workflows``. Enforced by
``tests/unit/test_episode_audio_assembly_service.py::test_module_never_imports_a_generation_capable_symbol``,
which inspects this module's own import table.

It also does not process audio: no concatenation, no silence
generation, no encoding. It only *predicts* what a future timeline's
duration would be, using the founder-approved preview gap constants
below, so that can be reviewed before any audio-processing dependency
is ever added (Phase 2+).

Ordering is always explicit (``Scene.order_index`` then
``DialogueLine.order_index``) — never incidental database order. A
spoken line without a valid, resolvable final take is never silently
dropped: it still appears in the report, marked invalid with the exact
reason, so an incomplete episode can never be silently reported as
assembly-ready.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.db.enums import ApprovalStatus
from app.core.models import Asset, DialogueLine, Episode, Scene
from app.core.models.asset import ROLE_FINAL_LINE_VOICE
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.storage_service import StorageService

# Founder-approved initial preview timing policy (2026-08-16). Preview
# defaults only -- deliberately plain module constants, not DB columns,
# since Phase 1 never generates audio and these may still change before
# Phase 2 actually consumes them. One boundary between two consecutive
# spoken sources gets exactly one gap, never both: SAME_SCENE_GAP when
# both sources share a scene_id, SCENE_BOUNDARY_GAP otherwise (including
# when one or more excluded song scenes sit between them).
DEFAULT_SAME_SCENE_GAP_SECONDS = 0.45
DEFAULT_SCENE_BOUNDARY_GAP_SECONDS = 1.25


@dataclass(frozen=True)
class AssemblySource:
    """One spoken :class:`~app.core.models.dialogue_line.DialogueLine`'s
    resolved (or invalid) audio source, in assembly order.

    Always present for every current spoken line in the episode, valid
    or not -- an invalid line is never omitted, only flagged via
    ``is_valid``/``validation_errors``, so an incomplete episode can
    never be silently reported as ready.
    """

    scene_id: uuid.UUID
    scene_order_index: int
    dialogue_line_id: uuid.UUID
    dialogue_line_order_index: int
    speaker: str
    authored_text: str
    asset_id: uuid.UUID | None
    relative_path: str | None
    absolute_path: Path | None
    duration_seconds: float | None
    provider_name: str | None
    model_id: str | None
    is_valid: bool
    validation_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeAssemblyReport:
    """The full deterministic-order source list for one Episode, plus
    aggregate figures -- including a *predicted* preview duration using
    the Phase 1 timing-policy constants. No audio is ever produced by
    computing this."""

    episode_id: uuid.UUID
    sources: list[AssemblySource]
    included_scene_count: int
    spoken_line_count: int
    song_line_count_excluded: int
    valid_source_count: int
    is_assembly_ready: bool
    total_source_duration_seconds: float
    same_scene_boundary_count: int
    scene_boundary_count: int
    predicted_silence_seconds: float
    predicted_preview_duration_seconds: float

    @property
    def invalid_sources(self) -> list[AssemblySource]:
        return [s for s in self.sources if not s.is_valid]


class EpisodeAudioAssemblyService:
    """Resolves and validates an Episode's spoken final-voice sources.

    Deliberately its own service (not folded into
    :class:`~app.core.services.scene_service.SceneService`): this is a
    read-model over already-final data for a downstream concern (future
    audio assembly), not a scene-authoring responsibility.
    """

    def __init__(
        self,
        storage: StorageService | None = None,
        config: AppConfig | None = None,
        same_scene_gap_seconds: float = DEFAULT_SAME_SCENE_GAP_SECONDS,
        scene_boundary_gap_seconds: float = DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
    ) -> None:
        self._config = config or get_config()
        self._storage = storage or StorageService(self._config)
        self._same_scene_gap = same_scene_gap_seconds
        self._scene_boundary_gap = scene_boundary_gap_seconds

    def build_report(self, session: Session, episode_id: uuid.UUID) -> EpisodeAssemblyReport:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        scenes = (
            session.query(Scene)
            .filter_by(episode_id=episode_id)
            .order_by(Scene.order_index)
            .all()
        )

        sources: list[AssemblySource] = []
        song_line_count_excluded = 0
        included_scene_ids: set[uuid.UUID] = set()

        for scene in scenes:
            if scene.is_song_scene:
                song_line_count_excluded += (
                    session.query(DialogueLine)
                    .filter_by(scene_id=scene.id, is_current=True)
                    .count()
                )
                continue
            lines = (
                session.query(DialogueLine)
                # is_current=True here is what guarantees every line this
                # service ever looks at is the line's current authored
                # revision -- no separate runtime check is needed.
                .filter_by(scene_id=scene.id, is_current=True)
                .order_by(DialogueLine.order_index)
                .all()
            )
            for line in lines:
                sources.append(self._resolve_source(session, scene, line))
                included_scene_ids.add(scene.id)

        valid_sources = [s for s in sources if s.is_valid]
        total_duration = sum(s.duration_seconds for s in valid_sources if s.duration_seconds)

        same_scene_gaps, scene_boundary_gaps = self._count_boundaries(sources)
        predicted_silence = (
            same_scene_gaps * self._same_scene_gap + scene_boundary_gaps * self._scene_boundary_gap
        )

        return EpisodeAssemblyReport(
            episode_id=episode_id,
            sources=sources,
            included_scene_count=len(included_scene_ids),
            spoken_line_count=len(sources),
            song_line_count_excluded=song_line_count_excluded,
            valid_source_count=len(valid_sources),
            is_assembly_ready=len(sources) > 0 and len(valid_sources) == len(sources),
            total_source_duration_seconds=total_duration,
            same_scene_boundary_count=same_scene_gaps,
            scene_boundary_count=scene_boundary_gaps,
            predicted_silence_seconds=predicted_silence,
            predicted_preview_duration_seconds=total_duration + predicted_silence,
        )

    def _resolve_source(self, session: Session, scene: Scene, line: DialogueLine) -> AssemblySource:
        errors: list[str] = []

        finals = (
            session.query(Asset)
            .filter_by(dialogue_line_id=line.id, role=ROLE_FINAL_LINE_VOICE)
            .all()
        )
        asset: Asset | None = None
        if len(finals) == 0:
            errors.append("no final_line_voice asset exists for this line")
        elif len(finals) > 1:
            errors.append(
                f"{len(finals)} final_line_voice assets exist for this line (expected exactly 1)"
            )
        else:
            asset = finals[0]

        absolute_path: Path | None = None
        if asset is not None:
            if asset.approval_status != ApprovalStatus.APPROVED:
                errors.append(f"final asset is not approved (status={asset.approval_status.value})")
            try:
                absolute_path = self._storage.resolve_managed_path(asset.relative_path)
            except ValidationError as err:
                errors.append(f"relative_path failed safe-path resolution: {err}")
            else:
                if not absolute_path.is_file():
                    errors.append("physical audio file does not exist on disk")
            if asset.duration_seconds is None or asset.duration_seconds <= 0:
                errors.append(f"invalid duration_seconds ({asset.duration_seconds!r})")

        provider_name: str | None = None
        model_id: str | None = None
        if asset is not None and asset.generation_job is not None:
            job = asset.generation_job
            provider_name = job.provider_name
            model_id = (job.parameters or {}).get("model_id", job.provider_model)

        return AssemblySource(
            scene_id=scene.id,
            scene_order_index=scene.order_index,
            dialogue_line_id=line.id,
            dialogue_line_order_index=line.order_index,
            speaker=line.speaker_raw,
            authored_text=line.authored_text,
            asset_id=asset.id if asset is not None else None,
            relative_path=asset.relative_path if asset is not None else None,
            absolute_path=absolute_path,
            duration_seconds=asset.duration_seconds if asset is not None else None,
            provider_name=provider_name,
            model_id=model_id,
            is_valid=not errors,
            validation_errors=errors,
        )

    def _count_boundaries(self, sources: list[AssemblySource]) -> tuple[int, int]:
        """One gap per consecutive pair, never both kinds at once."""
        same_scene = 0
        scene_boundary = 0
        for previous, current in pairwise(sources):
            if previous.scene_id == current.scene_id:
                same_scene += 1
            else:
                scene_boundary += 1
        return same_scene, scene_boundary
