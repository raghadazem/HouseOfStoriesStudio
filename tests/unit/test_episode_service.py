"""Tests for EpisodeService: CRUD, status transitions, templates, progress."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import PipelineStage
from app.core.services.episode_service import EpisodeService
from app.core.services.exceptions import (
    ChecklistError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)


def _create(es: EpisodeService, session: Session, **overrides):
    defaults = {
        "slug": "ep001_lost_little_turtle",
        "number": 1,
        "title_ar": "ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        "title_en": "Melissa and Bilsan and the Lost Little Turtle",
        "lesson": "Helping others",
    }
    defaults.update(overrides)
    return es.create_episode(session, **defaults)


def test_create_episode_supports_arabic_and_english_titles(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    assert episode.title_ar == "ميليسا وبيلسان والسلحفاة الصغيرة الضائعة"
    assert episode.title_en == "Melissa and Bilsan and the Lost Little Turtle"


def test_create_episode_rejects_duplicate_slug(session: Session) -> None:
    es = EpisodeService()
    _create(es, session)
    with pytest.raises(ConflictError, match="slug"):
        _create(es, session, number=2)


def test_create_episode_rejects_duplicate_number(session: Session) -> None:
    es = EpisodeService()
    _create(es, session)
    with pytest.raises(ConflictError, match="number"):
        _create(es, session, slug="ep002_other")


def test_create_episode_rejects_invalid_runtime_range(session: Session) -> None:
    es = EpisodeService()
    with pytest.raises(ValidationError):
        _create(es, session, runtime_target_minutes_min=10, runtime_target_minutes_max=8)


def test_get_episode_not_found(session: Session) -> None:
    es = EpisodeService()
    with pytest.raises(NotFoundError):
        es.get_episode(session, uuid.uuid4())


def test_update_episode_rejects_unknown_field(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    with pytest.raises(ValidationError):
        es.update_episode(session, episode.id, slug="new_slug")


def test_update_episode_changes_allowed_fields(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    updated = es.update_episode(session, episode.id, description_en="A short description.")
    assert updated.description_en == "A short description."


def test_delete_draft_episode_allowed_at_idea_stage(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    es.delete_draft_episode(session, episode.id)
    with pytest.raises(NotFoundError):
        es.get_episode(session, episode.id)


def test_delete_draft_episode_rejected_past_idea_stage(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    es.change_production_stage(session, episode.id, PipelineStage.SCRIPT)
    with pytest.raises(InvalidTransitionError):
        es.delete_draft_episode(session, episode.id)


def test_change_production_stage_moves_freely_through_production_stages(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    es.change_production_stage(session, episode.id, PipelineStage.SCRIPT)
    es.change_production_stage(session, episode.id, PipelineStage.STORYBOARD)
    assert episode.pipeline_stage == PipelineStage.STORYBOARD


def test_change_production_stage_rejects_gated_stages(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    with pytest.raises(InvalidTransitionError):
        es.change_production_stage(session, episode.id, PipelineStage.READY_TO_PUBLISH)


def test_change_episode_status_rejects_ready_to_publish_when_checklist_fails(
    session: Session,
) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    with pytest.raises(ChecklistError):
        es.change_episode_status(session, episode.id, PipelineStage.READY_TO_PUBLISH)
    assert episode.pipeline_stage == PipelineStage.IDEA  # unchanged


def test_change_episode_status_rejects_non_gated_stage(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    with pytest.raises(InvalidTransitionError):
        es.change_episode_status(session, episode.id, PipelineStage.SCRIPT)


def test_change_episode_status_published_requires_ready_to_publish_first(
    session: Session,
) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    with pytest.raises(InvalidTransitionError):
        es.change_episode_status(session, episode.id, PipelineStage.PUBLISHED)


def test_create_episode_from_template_creates_shorts_and_tasks(session: Session) -> None:
    es = EpisodeService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ع",
        title_en="Test",
        lesson="Sharing",
    )
    assert len(episode.shorts) == 3
    assert {s.short_index for s in episode.shorts} == {1, 2, 3}


def test_create_episode_from_template_can_skip_shorts_and_tasks(session: Session) -> None:
    es = EpisodeService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ع",
        title_en="Test",
        lesson="Sharing",
        include_shorts=False,
        include_default_tasks=False,
    )
    assert episode.shorts == []


def test_duplicate_episode_structure_copies_shape_not_content(session: Session) -> None:
    from app.core.services.scene_service import SceneService

    es = EpisodeService()
    ss = SceneService()
    source = _create(es, session)
    ss.add_scene(
        session, source.id, location="forest", description="secret plot detail", dialogue_ar="سر"
    )

    duplicate = es.duplicate_episode_structure(
        session,
        source.id,
        new_slug="ep002_duplicate",
        new_number=2,
        new_title_ar="جديد",
        new_title_en="New",
    )

    dup_scenes = ss.list_episode_scenes(session, duplicate.id)
    assert len(dup_scenes) == 1
    assert dup_scenes[0].location == "forest"
    assert dup_scenes[0].description is None  # content NOT copied
    assert dup_scenes[0].dialogue_ar is None
    assert len(duplicate.shorts) == 3


def test_calculate_episode_progress(session: Session) -> None:
    from app.core.services.production_task_service import ProductionTaskService

    es = EpisodeService()
    ts = ProductionTaskService()
    episode = _create(es, session)
    tasks = ts.create_default_episode_tasks(session, episode.id)
    ts.complete_task(session, tasks[0].id)

    progress = es.calculate_episode_progress(session, episode.id)
    assert progress.total_tasks == len(tasks)
    assert progress.completed_tasks == 1
    assert progress.pipeline_stage == PipelineStage.IDEA


def test_validate_episode_readiness_delegates_to_checklist(session: Session) -> None:
    es = EpisodeService()
    episode = _create(es, session)
    report = es.validate_episode_readiness(session, episode.id)
    assert report.is_ready is False
    assert report.readiness_percent < 100
