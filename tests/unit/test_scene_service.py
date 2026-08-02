"""Tests for SceneService: ordering, contiguity, deletion protection."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Episode
from app.core.services.exceptions import ConflictError, ValidationError
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
    )
    session.add(episode)
    session.flush()
    return episode


def test_add_scene_appends_by_default(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    s1 = ss.add_scene(session, episode.id, location="a")
    s2 = ss.add_scene(session, episode.id, location="b")
    assert (s1.order_index, s2.order_index) == (1, 2)


def test_add_scene_at_explicit_position_shifts_others(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    s1 = ss.add_scene(session, episode.id, location="a")
    s2 = ss.add_scene(session, episode.id, location="b")
    inserted = ss.add_scene(session, episode.id, order_index=2, location="inserted")

    scenes = ss.list_episode_scenes(session, episode.id)
    assert [(s.order_index, s.location) for s in scenes] == [
        (1, "a"),
        (2, "inserted"),
        (3, "b"),
    ]
    assert inserted.location == "inserted"
    assert s1.order_index == 1
    assert s2.order_index == 3


def test_add_scene_rejects_out_of_range_order_index(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    with pytest.raises(ValidationError):
        ss.add_scene(session, episode.id, order_index=5)


def test_update_scene_rejects_order_index(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    with pytest.raises(ValidationError, match="reorder_scenes"):
        ss.update_scene(session, scene.id, order_index=5)


def test_reorder_scenes_normalizes_sequence(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    s1 = ss.add_scene(session, episode.id, location="a")
    s2 = ss.add_scene(session, episode.id, location="b")
    s3 = ss.add_scene(session, episode.id, location="c")

    reordered = ss.reorder_scenes(session, episode.id, [s3.id, s1.id, s2.id])
    assert [s.location for s in reordered] == ["c", "a", "b"]
    assert [s.order_index for s in reordered] == [1, 2, 3]


def test_reorder_scenes_rejects_mismatched_id_set(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    s1 = ss.add_scene(session, episode.id)
    ss.add_scene(session, episode.id)
    with pytest.raises(ValidationError):
        ss.reorder_scenes(session, episode.id, [s1.id])  # missing one scene id


def test_delete_scene_renormalizes_remaining_sequence(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    ss.add_scene(session, episode.id, location="a")
    s2 = ss.add_scene(session, episode.id, location="b")
    s3 = ss.add_scene(session, episode.id, location="c")

    ss.delete_scene(session, s2.id)

    remaining = ss.list_episode_scenes(session, episode.id)
    assert [s.location for s in remaining] == ["a", "c"]
    assert [s.order_index for s in remaining] == [1, 2]
    assert s3.order_index == 2


def test_delete_scene_blocked_when_approved_final_asset_linked(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    asset = Asset(
        asset_type=AssetType.IMAGE,
        original_filename="f.png",
        relative_path="episodes/ep001/images/f.png",
        checksum="a" * 64,
        scene_id=scene.id,
        role="final_video",
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(asset)
    session.flush()

    with pytest.raises(ConflictError, match="approved final asset"):
        ss.delete_scene(session, scene.id)

    ss.delete_scene(session, scene.id, force=True)  # override works


def test_delete_scene_blocked_when_used_as_short_source(session: Session) -> None:
    ss = SceneService()
    shs = ShortService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    short = shs.create_short(session, episode.id)
    shs.link_source_scenes(session, short.id, [scene.id])

    with pytest.raises(ConflictError, match="source scene"):
        ss.delete_scene(session, scene.id)


def test_duplicate_scene_copies_content_and_inserts_after(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    original = ss.add_scene(session, episode.id, location="forest", description="d", dialogue_ar="س")
    ss.add_scene(session, episode.id, location="lake")

    duplicate = ss.duplicate_scene(session, original.id)

    scenes = ss.list_episode_scenes(session, episode.id)
    assert [s.location for s in scenes] == ["forest", "forest", "lake"]
    assert duplicate.description == "d"
    assert duplicate.dialogue_ar == "س"


def test_calculate_total_scene_duration_sums_estimates_treating_missing_as_zero(
    session: Session,
) -> None:
    ss = SceneService()
    episode = _episode(session)
    ss.add_scene(session, episode.id, estimated_duration_seconds=30)
    ss.add_scene(session, episode.id, estimated_duration_seconds=None)
    ss.add_scene(session, episode.id, estimated_duration_seconds=45)
    assert ss.calculate_total_scene_duration(session, episode.id) == 75


def test_validate_scene_sequence_detects_gap(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    ss.add_scene(session, episode.id)
    second = ss.add_scene(session, episode.id)
    ss.add_scene(session, episode.id)

    # Force a gap directly at the model level (bypassing the service) to
    # simulate corrupted state and confirm the validator catches it.
    second.order_index = 5
    session.flush()

    result = ss.validate_scene_sequence(session, episode.id)
    assert result.is_valid is False
    assert result.issues
