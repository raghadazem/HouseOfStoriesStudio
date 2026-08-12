"""Tests for SceneService: ordering, contiguity, deletion protection."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.services.prompt_composer_service import ComposedPrompt
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


# --- Episode Workspace additions: title/camera/prompt fields, cast, approval ---


def test_update_scene_accepts_new_workspace_fields(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    updated = ss.update_scene(
        session,
        scene.id,
        title="The Turtle Appears",
        camera_direction="Wide establishing shot",
        prompt_text="a turtle on a riverbank",
        negative_prompt_text="blurry, low quality",
    )
    assert updated.title == "The Turtle Appears"
    assert updated.camera_direction == "Wide establishing shot"
    assert updated.prompt_text == "a turtle on a riverbank"
    assert updated.negative_prompt_text == "blurry, low quality"


def test_add_scene_accepts_title_and_camera_direction(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, title="Opening", camera_direction="Close-up")
    assert scene.title == "Opening"
    assert scene.camera_direction == "Close-up"


def test_duplicate_scene_copies_new_fields_too(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    original = ss.add_scene(session, episode.id, title="Original", camera_direction="Pan left")
    ss.update_scene(session, original.id, prompt_text="p", negative_prompt_text="np")

    duplicate = ss.duplicate_scene(session, original.id)

    assert duplicate.title == "Original"
    assert duplicate.camera_direction == "Pan left"
    assert duplicate.prompt_text == "p"
    assert duplicate.negative_prompt_text == "np"


def test_set_scene_characters_replaces_cast(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    bilsan = Character(slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    session.add_all([melissa, bilsan])
    session.flush()

    ss.set_scene_characters(session, scene.id, [melissa.id])
    assert [c.slug for c in scene.characters_present] == ["melissa"]

    ss.set_scene_characters(session, scene.id, [melissa.id, bilsan.id])
    assert {c.slug for c in scene.characters_present} == {"melissa", "bilsan"}

    ss.set_scene_characters(session, scene.id, [])
    assert scene.characters_present == []


def test_set_scene_characters_rejects_unknown_character(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    with pytest.raises(NotFoundError):
        ss.set_scene_characters(session, scene.id, [uuid.uuid4()])


def test_approve_reject_request_changes_scene_records_history(session: Session) -> None:
    ss = SceneService()
    approvals = ApprovalService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)

    ss.approve_scene(session, scene.id, decided_by="founder")
    assert (
        approvals.get_current_approval_state(session, "scene", scene.id)
        == ApprovalDecision.APPROVED
    )

    ss.request_scene_changes(session, scene.id, notes="camera direction unclear")
    assert (
        approvals.get_current_approval_state(session, "scene", scene.id)
        == ApprovalDecision.NEEDS_CHANGES
    )

    ss.reject_scene(session, scene.id, notes="doesn't match the script")
    assert (
        approvals.get_current_approval_state(session, "scene", scene.id)
        == ApprovalDecision.REJECTED
    )


def test_generate_and_store_prompt_persists_composer_output(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, description="A turtle on a riverbank")

    class _FakeComposer:
        def compose_scene_prompt(self, session, scene_id):
            return ComposedPrompt(prompt_text="composed prompt", negative_prompt_text="composed negative")

    updated = ss.generate_and_store_prompt(session, scene.id, composer=_FakeComposer())
    assert updated.prompt_text == "composed prompt"
    assert updated.negative_prompt_text == "composed negative"


def test_update_scene_accepts_voice_notes(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    updated = ss.update_scene(session, scene.id, voice_notes="Warm, gentle tone; slow pacing.")
    assert updated.voice_notes == "Warm, gentle tone; slow pacing."


def test_build_voice_package_splits_dialogue_by_speaker(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    first = ss.add_scene(
        session, episode.id, title="The Discovery",
        dialogue_ar="الراوي: مقدمة قصيرة.\nميليسا: انظري يا بيلسان!\nبيلسان: ماذا؟",
    )
    ss.update_scene(session, first.id, voice_notes="Curious, upbeat pacing.")
    second = ss.add_scene(
        session, episode.id, title="The Reunion",
        dialogue_ar="طُرطُر: نجحنا!\n(اتجاه بصري بلا حوار)",
    )
    ss.update_scene(session, second.id, voice_notes="Joyful, relieved.")

    lines = ss.build_voice_package(session, episode.id)

    assert [(line.speaker, line.text) for line in lines] == [
        ("الراوي", "مقدمة قصيرة."),
        ("ميليسا", "انظري يا بيلسان!"),
        ("بيلسان", "ماذا؟"),
        ("طُرطُر", "نجحنا!"),
    ]
    assert lines[0].scene_title == "The Discovery"
    assert lines[0].voice_notes == "Curious, upbeat pacing."
    assert lines[-1].scene_title == "The Reunion"
    assert lines[-1].voice_notes == "Joyful, relieved."


def test_build_voice_package_groups_lines_per_speaker(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    ss.add_scene(
        session, episode.id,
        dialogue_ar="ميليسا: سطر أول.\nبيلسان: سطر ثانٍ.\nميليسا: سطر ثالث.",
    )

    lines = ss.build_voice_package(session, episode.id)
    by_speaker: dict[str, list[str]] = {}
    for line in lines:
        by_speaker.setdefault(line.speaker, []).append(line.text)

    assert by_speaker == {
        "ميليسا": ["سطر أول.", "سطر ثالث."],
        "بيلسان": ["سطر ثانٍ."],
    }


def test_build_voice_package_ignores_scenes_with_no_dialogue(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    ss.add_scene(session, episode.id, description="A silent visual beat.")

    assert ss.build_voice_package(session, episode.id) == []


# --- set_scene_key_image (Milestone 8) ---------------------------------------


def _approved_scene_asset(session: Session, scene_id: uuid.UUID, **overrides) -> Asset:
    defaults = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "candidate.png",
        "relative_path": f"episodes/ep001/images/{uuid.uuid4()}.png",
        "checksum": uuid.uuid4().hex.ljust(64, "0"),
        "scene_id": scene_id,
        "approval_status": ApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    asset = Asset(**defaults)
    session.add(asset)
    session.flush()
    return asset


def test_set_scene_key_image_assigns_role(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    asset = _approved_scene_asset(session, scene.id)

    result = ss.set_scene_key_image(session, scene.id, asset.id)

    assert result.role == "final_scene_image"


def test_set_scene_key_image_replacing_preserves_old_as_approved(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    first = _approved_scene_asset(session, scene.id)
    second = _approved_scene_asset(session, scene.id)

    ss.set_scene_key_image(session, scene.id, first.id)
    ss.set_scene_key_image(session, scene.id, second.id)

    session.refresh(first)
    session.refresh(second)
    assert first.role is None
    assert first.approval_status == ApprovalStatus.APPROVED  # preserved, not deleted
    assert second.role == "final_scene_image"


def test_set_scene_key_image_rejects_asset_from_another_scene(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene_a = ss.add_scene(session, episode.id)
    scene_b = ss.add_scene(session, episode.id)
    asset = _approved_scene_asset(session, scene_b.id)

    with pytest.raises(ValidationError, match="does not belong"):
        ss.set_scene_key_image(session, scene_a.id, asset.id)


def test_set_scene_key_image_rejects_unapproved_asset(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)
    asset = _approved_scene_asset(session, scene.id, approval_status=ApprovalStatus.DRAFT)

    with pytest.raises(ValidationError, match="approved"):
        ss.set_scene_key_image(session, scene.id, asset.id)


def test_set_scene_key_image_rejects_unknown_asset(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)

    with pytest.raises(NotFoundError):
        ss.set_scene_key_image(session, scene.id, uuid.uuid4())


# --- set_line_final_take (Milestone 9) ----------------------------------------


def _approved_voice_asset(session: Session, dialogue_line_id: uuid.UUID, **overrides) -> Asset:
    defaults = {
        "asset_type": AssetType.VOICE,
        "original_filename": "take.wav",
        "relative_path": f"episodes/ep001/audio/voice/{uuid.uuid4()}.wav",
        "checksum": uuid.uuid4().hex.ljust(64, "0"),
        "dialogue_line_id": dialogue_line_id,
        "approval_status": ApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    asset = Asset(**defaults)
    session.add(asset)
    session.flush()
    return asset


def _one_line(session: Session, ss: SceneService):
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    return ss.sync_dialogue_lines(session, scene.id)[0]


def test_set_line_final_take_assigns_role(session: Session) -> None:
    ss = SceneService()
    line = _one_line(session, ss)
    asset = _approved_voice_asset(session, line.id)

    result = ss.set_line_final_take(session, line.id, asset.id)

    assert result.role == "final_line_voice"


def test_set_line_final_take_replacing_preserves_old_as_approved(session: Session) -> None:
    ss = SceneService()
    line = _one_line(session, ss)
    first = _approved_voice_asset(session, line.id)
    second = _approved_voice_asset(session, line.id)

    ss.set_line_final_take(session, line.id, first.id)
    ss.set_line_final_take(session, line.id, second.id)

    session.refresh(first)
    session.refresh(second)
    assert first.role is None
    assert first.approval_status == ApprovalStatus.APPROVED  # preserved, not deleted
    assert second.role == "final_line_voice"


def test_set_line_final_take_rejects_asset_from_another_line(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B")
    line_a, line_b = ss.sync_dialogue_lines(session, scene.id)
    asset = _approved_voice_asset(session, line_b.id)

    with pytest.raises(ValidationError, match="does not belong"):
        ss.set_line_final_take(session, line_a.id, asset.id)


def test_set_line_final_take_rejects_unapproved_asset(session: Session) -> None:
    ss = SceneService()
    line = _one_line(session, ss)
    asset = _approved_voice_asset(session, line.id, approval_status=ApprovalStatus.DRAFT)

    with pytest.raises(ValidationError, match="approved"):
        ss.set_line_final_take(session, line.id, asset.id)


def test_set_line_final_take_rejects_unknown_line(session: Session) -> None:
    ss = SceneService()
    with pytest.raises(NotFoundError):
        ss.set_line_final_take(session, uuid.uuid4(), uuid.uuid4())


def test_set_line_final_take_rejects_unknown_asset(session: Session) -> None:
    ss = SceneService()
    line = _one_line(session, ss)

    with pytest.raises(NotFoundError):
        ss.set_line_final_take(session, line.id, uuid.uuid4())
