"""Tests for ShortService: defaults, ordering, source-scene linking, readiness."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Episode
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService


def _episode(session: Session, slug: str = "ep001_test", number: int = 1) -> Episode:
    episode = Episode(slug=slug, number=number, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    return episode


def test_generate_default_three_shorts_creates_exactly_three(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    shorts = shs.generate_default_three_shorts(session, episode.id)
    assert [s.short_index for s in shorts] == [1, 2, 3]


def test_generate_default_three_shorts_is_idempotent(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    shs.generate_default_three_shorts(session, episode.id)
    second_call = shs.generate_default_three_shorts(session, episode.id)
    assert second_call == []  # nothing new created
    assert len(shs.list_episode_shorts(session, episode.id)) == 3


def test_create_short_allows_a_fourth_short_later(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    shs.generate_default_three_shorts(session, episode.id)
    fourth = shs.create_short(session, episode.id)
    assert fourth.short_index == 4


def test_update_short_rejects_short_index(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    with pytest.raises(ValidationError, match="reorder_shorts"):
        shs.update_short(session, short.id, short_index=5)


def test_update_short_accepts_milestone_6_fields(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    updated = shs.update_short(
        session, short.id,
        spoken_text_ar="ميليسا: مرحباً!",
        on_screen_text_ar="سلحفاة صغيرة! 🐢",
        target_duration_seconds=30,
        editing_notes="Fast cold-open cut, freeze on the reveal.",
    )
    assert updated.spoken_text_ar == "ميليسا: مرحباً!"
    assert updated.on_screen_text_ar == "سلحفاة صغيرة! 🐢"
    assert updated.target_duration_seconds == 30
    assert updated.editing_notes == "Fast cold-open cut, freeze on the reveal."


def test_reorder_shorts_normalizes_sequence(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    shorts = shs.generate_default_three_shorts(session, episode.id)
    reordered = shs.reorder_shorts(
        session, episode.id, [shorts[2].id, shorts[0].id, shorts[1].id]
    )
    assert [s.id for s in reordered] == [shorts[2].id, shorts[0].id, shorts[1].id]
    assert [s.short_index for s in reordered] == [1, 2, 3]


def test_delete_short_renormalizes_sequence(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    shorts = shs.generate_default_three_shorts(session, episode.id)
    shs.delete_short(session, shorts[0].id)
    remaining = shs.list_episode_shorts(session, episode.id)
    assert [s.short_index for s in remaining] == [1, 2]


def test_link_source_scenes_requires_same_episode(session: Session) -> None:
    shs = ShortService()
    ss = SceneService()
    episode_a = _episode(session, slug="ep001", number=1)
    episode_b = _episode(session, slug="ep002", number=2)

    scene_in_b = ss.add_scene(session, episode_b.id)
    short_in_a = shs.create_short(session, episode_a.id)

    with pytest.raises(ValidationError, match="do not belong"):
        shs.link_source_scenes(session, short_in_a.id, [scene_in_b.id])


def test_link_source_scenes_rejects_unknown_scene(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    with pytest.raises(NotFoundError):
        shs.link_source_scenes(session, short.id, [uuid.uuid4()])


def test_link_and_unlink_source_scenes(session: Session) -> None:
    shs = ShortService()
    ss = SceneService()
    episode = _episode(session)
    scene1 = ss.add_scene(session, episode.id, location="a")
    scene2 = ss.add_scene(session, episode.id, location="b")
    short = shs.create_short(session, episode.id)

    shs.link_source_scenes(session, short.id, [scene1.id, scene2.id])
    assert {s.id for s in short.source_scenes} == {scene1.id, scene2.id}

    shs.unlink_source_scene(session, short.id, scene1.id)
    assert {s.id for s in short.source_scenes} == {scene2.id}


def test_validate_short_reports_missing_fields(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    result = shs.validate_short(session, short.id)
    assert result.is_valid is False
    assert "no source scenes linked" in result.issues


def test_validate_short_passes_when_complete(session: Session) -> None:
    shs = ShortService()
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    short = shs.create_short(
        session,
        episode.id,
        title_ar="عنوان",
        working_title_en="Title",
        hook_ar="خطاف",
        caption_ar="تعليق",
    )
    shs.link_source_scenes(session, short.id, [scene.id])
    result = shs.validate_short(session, short.id)
    assert result.is_valid is True


def test_calculate_short_readiness_false_without_final_video(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    readiness = shs.calculate_short_readiness(session, short.id)
    assert readiness.is_ready is False


def test_calculate_short_readiness_true_with_approved_final_video(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    asset = Asset(
        asset_type=AssetType.VIDEO,
        original_filename="short1.mp4",
        relative_path="episodes/ep001/videos/short1.mp4",
        checksum="b" * 64,
        short_id=short.id,
        role="final_video",
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(asset)
    session.flush()

    readiness = shs.calculate_short_readiness(session, short.id)
    assert readiness.is_ready is True


def test_calculate_short_readiness_false_when_final_video_not_approved(session: Session) -> None:
    shs = ShortService()
    episode = _episode(session)
    short = shs.create_short(session, episode.id)
    asset = Asset(
        asset_type=AssetType.VIDEO,
        original_filename="short1.mp4",
        relative_path="episodes/ep001/videos/short1.mp4",
        checksum="c" * 64,
        short_id=short.id,
        role="final_video",
        approval_status=ApprovalStatus.DRAFT,
    )
    session.add(asset)
    session.flush()

    readiness = shs.calculate_short_readiness(session, short.id)
    assert readiness.is_ready is False
