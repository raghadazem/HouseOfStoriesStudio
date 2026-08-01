"""Integration tests for app.core.db.seed — seeding Melissa, Bilsan, and Episode 001."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db.enums import CharacterVersionStatus, PipelineStage, ShortStatus
from app.core.db.seed import (
    BILSAN_SLUG,
    EPISODE_001_SLUG,
    MELISSA_SLUG,
    seed_demo_data,
)
from app.core.models import Character, Episode, Short


def test_seed_demo_data_creates_expected_rows(session: Session) -> None:
    result = seed_demo_data(session)

    assert set(result) == {"melissa", "bilsan", "episode_001"}
    assert session.query(Character).count() == 2
    assert session.query(Episode).count() == 1
    assert session.query(Short).count() == 3


def test_seed_demo_data_matches_approved_character_bible(session: Session) -> None:
    seed_demo_data(session)

    melissa = session.query(Character).filter_by(slug=MELISSA_SLUG).one()
    assert melissa.name_ar == "ميليسا"
    assert melissa.age == 6
    assert melissa.role == "older sister"
    assert set(melissa.traits) == {"brave", "curious", "kind", "loves nature"}

    bilsan = session.query(Character).filter_by(slug=BILSAN_SLUG).one()
    assert bilsan.name_ar == "بيلسان"
    assert bilsan.age == 4
    assert "teddy bear" in bilsan.versions[0].allowed_accessories


def test_seed_character_versions_are_draft_placeholders_not_approved(session: Session) -> None:
    """No approved artwork exists yet, so nothing should claim approved_canon status."""
    seed_demo_data(session)

    for slug in (MELISSA_SLUG, BILSAN_SLUG):
        character = session.query(Character).filter_by(slug=slug).one()
        assert len(character.versions) == 1
        version = character.versions[0]
        assert version.status == CharacterVersionStatus.DRAFT
        assert version.master_prompt is None
        assert "PLACEHOLDER" in version.visual_summary


def test_seed_episode_001_matches_founder_approved_titles(session: Session) -> None:
    seed_demo_data(session)

    episode = session.query(Episode).filter_by(slug=EPISODE_001_SLUG).one()
    assert episode.number == 1
    assert episode.title_ar == "ميليسا وبيلسان والسلحفاة الصغيرة الضائعة"
    assert episode.title_en == "Melissa and Bilsan and the Lost Little Turtle"
    assert episode.lesson == "Helping others"
    assert episode.pipeline_stage == PipelineStage.IDEA
    assert {c.slug for c in episode.characters_featured} == {MELISSA_SLUG, BILSAN_SLUG}


def test_seed_episode_001_has_exactly_three_planned_shorts(session: Session) -> None:
    seed_demo_data(session)

    episode = session.query(Episode).filter_by(slug=EPISODE_001_SLUG).one()
    assert [s.short_index for s in episode.shorts] == [1, 2, 3]
    assert all(s.status == ShortStatus.PLANNED for s in episode.shorts)


def test_seed_demo_data_is_idempotent(session: Session) -> None:
    seed_demo_data(session)
    seed_demo_data(session)  # running twice must not duplicate anything

    assert session.query(Character).count() == 2
    assert session.query(Episode).count() == 1
    assert session.query(Short).count() == 3
