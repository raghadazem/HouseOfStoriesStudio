"""EpisodeService — episode CRUD, pipeline-stage tracking, and readiness.

Two different methods change ``Episode.pipeline_stage`` on purpose:
:meth:`change_production_stage` moves freely through the day-to-day
production steps (idea -> ... -> seo), while :meth:`change_episode_status`
gates the two significant transitions — ``ready_to_publish`` (must pass
:class:`~app.core.services.production_checklist_service.ProductionChecklistService`)
and ``published`` (must already be ready_to_publish). This is what
enforces "an episode cannot be marked Ready to Publish when required
checks fail."
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.db.enums import PipelineStage
from app.core.models import Character, Episode
from app.core.services.exceptions import (
    ChecklistError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)
from app.core.services.production_checklist_service import (
    ChecklistReport,
    ProductionChecklistService,
)
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService

_UPDATABLE_FIELDS = {
    "title_ar",
    "title_en",
    "lesson",
    "logline_ar",
    "season",
    "dialogue_language",
    "runtime_target_minutes_min",
    "runtime_target_minutes_max",
    "includes_song",
    "description_ar",
    "description_en",
    "hashtags",
    "credits_text",
    "youtube_url",
}

_GATED_STAGES = (PipelineStage.READY_TO_PUBLISH, PipelineStage.PUBLISHED)


@dataclass(frozen=True)
class EpisodeProgress:
    """Result of :meth:`EpisodeService.calculate_episode_progress`."""

    completed_tasks: int
    total_tasks: int
    percent: float
    pipeline_stage: PipelineStage


class EpisodeService:
    """CRUD, pipeline-stage transitions, and readiness for episodes."""

    def __init__(
        self,
        checklist_service: ProductionChecklistService | None = None,
        task_service: ProductionTaskService | None = None,
        scene_service: SceneService | None = None,
        short_service: ShortService | None = None,
    ) -> None:
        self._checklist = checklist_service or ProductionChecklistService()
        self._tasks = task_service or ProductionTaskService()
        self._scenes = scene_service or SceneService()
        self._shorts = short_service or ShortService()

    def create_episode(
        self,
        session: Session,
        *,
        slug: str,
        number: int,
        title_ar: str,
        title_en: str,
        lesson: str,
        season: int = 1,
        logline_ar: str | None = None,
        dialogue_language: str = "simple_white_arabic",
        runtime_target_minutes_min: int = 8,
        runtime_target_minutes_max: int = 10,
        includes_song: bool = False,
        character_ids: list[uuid.UUID] | None = None,
    ) -> Episode:
        """Create an episode. Supports Arabic and English titles independently.

        Raises:
            ConflictError: ``slug`` or ``number`` already in use.
            ValidationError: Invalid runtime range.
        """
        if session.query(Episode).filter_by(slug=slug).count() > 0:
            raise ConflictError(f"Episode slug {slug!r} already exists.")
        if session.query(Episode).filter_by(number=number).count() > 0:
            raise ConflictError(f"Episode number {number} already exists.")
        if runtime_target_minutes_max < runtime_target_minutes_min:
            raise ValidationError("runtime_target_minutes_max must be >= runtime_target_minutes_min.")

        episode = Episode(
            slug=slug,
            number=number,
            title_ar=title_ar,
            title_en=title_en,
            lesson=lesson,
            season=season,
            logline_ar=logline_ar,
            dialogue_language=dialogue_language,
            runtime_target_minutes_min=runtime_target_minutes_min,
            runtime_target_minutes_max=runtime_target_minutes_max,
            includes_song=includes_song,
        )
        if character_ids:
            episode.characters_featured = self._load_characters(session, character_ids)
        session.add(episode)
        session.flush()
        return episode

    def get_episode(self, session: Session, episode_id: uuid.UUID) -> Episode:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        return episode

    def get_episode_by_slug(self, session: Session, slug: str) -> Episode:
        episode = session.query(Episode).filter_by(slug=slug).one_or_none()
        if episode is None:
            raise NotFoundError(f"Episode with slug {slug!r} not found.")
        return episode

    def list_episodes(
        self,
        session: Session,
        *,
        pipeline_stage: PipelineStage | None = None,
        season: int | None = None,
    ) -> list[Episode]:
        query = session.query(Episode)
        if pipeline_stage is not None:
            query = query.filter_by(pipeline_stage=pipeline_stage)
        if season is not None:
            query = query.filter_by(season=season)
        return query.order_by(Episode.number).all()

    def update_episode(self, session: Session, episode_id: uuid.UUID, **fields: object) -> Episode:
        """Update episode metadata. ``slug``/``number`` are not updatable here (identity fields)."""
        episode = self.get_episode(session, episode_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Episode fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(episode, key, value)
        session.flush()
        return episode

    def delete_draft_episode(self, session: Session, episode_id: uuid.UUID) -> None:
        """Delete an episode, but only while it's still at the ``idea`` stage.

        Raises:
            InvalidTransitionError: The episode has progressed past
                ``idea`` — too much real work may already exist to
                delete casually.
        """
        episode = self.get_episode(session, episode_id)
        if episode.pipeline_stage != PipelineStage.IDEA:
            raise InvalidTransitionError(
                f"Only an episode still at the 'idea' stage may be deleted "
                f"(current: {episode.pipeline_stage.value})."
            )
        session.delete(episode)
        session.flush()

    def change_production_stage(
        self, session: Session, episode_id: uuid.UUID, new_stage: PipelineStage
    ) -> Episode:
        """Move through the day-to-day production pipeline (idea..seo).

        Raises:
            InvalidTransitionError: ``new_stage`` is one of the gated
                stages (use :meth:`change_episode_status`), or the
                episode is already ``published``.
        """
        episode = self.get_episode(session, episode_id)
        if new_stage in _GATED_STAGES:
            raise InvalidTransitionError(
                f"{new_stage.value!r} must be set via change_episode_status(), "
                "not change_production_stage()."
            )
        if episode.pipeline_stage == PipelineStage.PUBLISHED:
            raise InvalidTransitionError("Cannot change the production stage of a published episode.")
        episode.pipeline_stage = new_stage
        session.flush()
        return episode

    def change_episode_status(
        self, session: Session, episode_id: uuid.UUID, new_stage: PipelineStage
    ) -> Episode:
        """Gate the two significant transitions: ready_to_publish and published.

        Raises:
            InvalidTransitionError: ``new_stage`` isn't one of the two
                gated stages, or (for ``published``) the episode isn't
                already ``ready_to_publish``.
            ChecklistError: (for ``ready_to_publish``) the readiness
                checklist has blocking issues.
        """
        episode = self.get_episode(session, episode_id)
        if new_stage not in _GATED_STAGES:
            raise InvalidTransitionError(
                f"change_episode_status only accepts "
                f"{[s.value for s in _GATED_STAGES]}; use change_production_stage "
                "for other stages."
            )

        if new_stage == PipelineStage.READY_TO_PUBLISH:
            report = self._checklist.evaluate(session, episode_id)
            if not report.is_ready:
                raise ChecklistError(
                    f"Episode {episode_id} is not ready to publish "
                    f"({report.readiness_percent}% ready). Blocking issues: "
                    f"{[c.name for c in report.blocking_issues]}"
                )
            episode.pipeline_stage = PipelineStage.READY_TO_PUBLISH
        else:  # PUBLISHED
            if episode.pipeline_stage != PipelineStage.READY_TO_PUBLISH:
                raise InvalidTransitionError(
                    "Episode must be ready_to_publish before it can be published "
                    f"(current: {episode.pipeline_stage.value})."
                )
            episode.pipeline_stage = PipelineStage.PUBLISHED
            episode.published_at = datetime.now(UTC)

        session.flush()
        return episode

    def create_episode_from_template(
        self,
        session: Session,
        *,
        slug: str,
        number: int,
        title_ar: str,
        title_en: str,
        lesson: str,
        season: int = 1,
        character_ids: list[uuid.UUID] | None = None,
        include_shorts: bool = True,
        include_default_tasks: bool = True,
        **episode_fields: object,
    ) -> Episode:
        """Create an episode, plus its 3 default Shorts and default task checklist."""
        episode = self.create_episode(
            session,
            slug=slug,
            number=number,
            title_ar=title_ar,
            title_en=title_en,
            lesson=lesson,
            season=season,
            character_ids=character_ids,
            **episode_fields,
        )
        if include_shorts:
            self._shorts.generate_default_three_shorts(session, episode.id)
        if include_default_tasks:
            self._tasks.create_default_episode_tasks(session, episode.id)
        session.flush()
        return episode

    def duplicate_episode_structure(
        self,
        session: Session,
        source_episode_id: uuid.UUID,
        *,
        new_slug: str,
        new_number: int,
        new_title_ar: str,
        new_title_en: str,
    ) -> Episode:
        """Copy an episode's *shape* — settings, scene count/locations, 3 Shorts.

        Never copies written creative content (scene descriptions,
        dialogue, Short hooks/captions) — only the structural skeleton
        (scene locations and count), so this can't be mistaken for
        generating new creative content.
        """
        source = self.get_episode(session, source_episode_id)
        new_episode = self.create_episode(
            session,
            slug=new_slug,
            number=new_number,
            title_ar=new_title_ar,
            title_en=new_title_en,
            lesson=source.lesson,
            season=source.season,
            dialogue_language=source.dialogue_language,
            runtime_target_minutes_min=source.runtime_target_minutes_min,
            runtime_target_minutes_max=source.runtime_target_minutes_max,
            includes_song=source.includes_song,
            character_ids=[c.id for c in source.characters_featured],
        )
        for scene in self._scenes.list_episode_scenes(session, source_episode_id):
            self._scenes.add_scene(session, new_episode.id, location=scene.location)
        self._shorts.generate_default_three_shorts(session, new_episode.id)
        session.flush()
        return new_episode

    def calculate_episode_progress(self, session: Session, episode_id: uuid.UUID) -> EpisodeProgress:
        """Production-task completion percentage, alongside the current pipeline stage."""
        episode = self.get_episode(session, episode_id)
        progress = self._tasks.calculate_task_progress(session, episode_id)
        return EpisodeProgress(
            completed_tasks=progress.completed,
            total_tasks=progress.total,
            percent=progress.percent,
            pipeline_stage=episode.pipeline_stage,
        )

    def validate_episode_readiness(self, session: Session, episode_id: uuid.UUID) -> ChecklistReport:
        """Thin convenience wrapper around :class:`ProductionChecklistService`."""
        return self._checklist.evaluate(session, episode_id)

    @staticmethod
    def _load_characters(session: Session, character_ids: list[uuid.UUID]) -> list[Character]:
        characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
        found = {c.id for c in characters}
        missing = set(character_ids) - found
        if missing:
            raise NotFoundError(f"Character(s) not found: {sorted(missing)}")
        return characters
