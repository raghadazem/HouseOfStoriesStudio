"""Tests for Episode, Scene, and Short."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.enums import PipelineStage, ShortStatus
from app.core.models import Character, Episode, Scene, Short


def _make_episode(**overrides: object) -> Episode:
    defaults: dict[str, object] = {
        "slug": "ep001_lost_little_turtle",
        "number": 1,
        "title_ar": "ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        "title_en": "Melissa and Bilsan and the Lost Little Turtle",
        "lesson": "Helping others",
    }
    defaults.update(overrides)
    return Episode(**defaults)


def test_episode_defaults(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.commit()

    assert episode.season == 1
    assert episode.pipeline_stage == PipelineStage.IDEA
    assert episode.includes_song is False
    assert episode.dialogue_language == "simple_white_arabic"
    assert episode.runtime_target_minutes_min == 8
    assert episode.runtime_target_minutes_max == 10


def test_episode_number_must_be_unique(session: Session) -> None:
    session.add(_make_episode())
    session.commit()

    session.add(_make_episode(slug="ep001_duplicate"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_episode_slug_must_be_unique(session: Session) -> None:
    session.add(_make_episode())
    session.commit()

    session.add(_make_episode(number=2))
    with pytest.raises(IntegrityError):
        session.commit()


def test_episode_characters_featured_many_to_many(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    bilsan = Character(slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    session.add_all([melissa, bilsan])
    session.flush()

    episode = _make_episode(characters_featured=[melissa, bilsan])
    session.add(episode)
    session.commit()

    assert {c.slug for c in episode.characters_featured} == {"melissa", "bilsan"}


def test_scene_order_index_unique_per_episode(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()

    session.add(Scene(episode_id=episode.id, order_index=1))
    session.commit()

    session.add(Scene(episode_id=episode.id, order_index=1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_scene_order_index_can_repeat_across_episodes(session: Session) -> None:
    ep1 = _make_episode()
    ep2 = _make_episode(slug="ep002_other", number=2)
    session.add_all([ep1, ep2])
    session.flush()

    session.add(Scene(episode_id=ep1.id, order_index=1))
    session.add(Scene(episode_id=ep2.id, order_index=1))
    session.commit()  # must not raise


def test_scene_arabic_dialogue_round_trips(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()

    scene = Scene(
        episode_id=episode.id,
        order_index=1,
        dialogue_ar="مرحباً! هل رأيت السلحفاة الصغيرة؟",
    )
    session.add(scene)
    session.commit()

    session.expunge_all()
    reloaded = session.get(Scene, scene.id)
    assert reloaded is not None
    assert reloaded.dialogue_ar == "مرحباً! هل رأيت السلحفاة الصغيرة؟"


def test_short_index_unique_per_episode(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()

    session.add(Short(episode_id=episode.id, short_index=1))
    session.commit()

    session.add(Short(episode_id=episode.id, short_index=1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_episode_gets_exactly_three_shorts(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()

    for index in (1, 2, 3):
        episode.shorts.append(Short(short_index=index, status=ShortStatus.PLANNED))
    session.commit()

    assert [s.short_index for s in episode.shorts] == [1, 2, 3]
    assert all(s.status == ShortStatus.PLANNED for s in episode.shorts)


def test_deleting_episode_cascades_to_scenes_and_shorts(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()
    session.add(Scene(episode_id=episode.id, order_index=1))
    episode.shorts.append(Short(short_index=1))
    session.commit()

    episode_id = episode.id
    session.delete(episode)
    session.commit()

    assert session.query(Scene).filter_by(episode_id=episode_id).count() == 0
    assert session.query(Short).filter_by(episode_id=episode_id).count() == 0
