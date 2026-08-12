"""Tests for CharacterVersionService: the Character Lock lifecycle."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType, CharacterVersionStatus
from app.core.models import Asset, Character
from app.core.services.approval_service import ApprovalService
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.exceptions import (
    CharacterLockIncompleteError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)


def _character(session: Session) -> Character:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    return character


def _approved_image_asset(session: Session, **overrides) -> Asset:
    defaults = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "ref.png",
        "relative_path": "characters/melissa/versions/v01/ref.png",
        "checksum": "a" * 64,
        "approval_status": ApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    asset = Asset(**defaults)
    session.add(asset)
    session.flush()
    return asset


_LOCK_FIELDS = {
    "visual_summary": "Two ponytails, denim dress.",
    "master_prompt": "Melissa: 6yo girl...",
    "negative_prompt": "no extra characters",
    "color_palette": ["denim blue", "red"],
    "relative_height": "taller than Bilsan",
}


def _approve_with_complete_lock(
    session: Session, cvs: CharacterVersionService, character: Character, version_id: uuid.UUID
) -> None:
    """Give ``version_id`` a complete Character Lock, then submit + approve it.

    Shared by every test that needs an ``approved_canon`` version to
    exist as setup, now that :meth:`CharacterVersionService.approve_character_version`
    enforces lock completeness — see ``test_approve_character_version_*``
    below for the tests of that enforcement itself.
    """
    cvs.update_character_version(session, version_id, **_LOCK_FIELDS)
    # relative_path and checksum are both unique on Asset — derive both
    # from version_id so this helper is safe to call more than once per
    # test (e.g. once per version being approved).
    asset = _approved_image_asset(
        session,
        relative_path=f"characters/{character.slug}/versions/{version_id}/ref.png",
        checksum=uuid.uuid5(uuid.NAMESPACE_URL, str(version_id)).hex.ljust(64, "0"),
    )
    cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version_id, asset_id=asset.id
    )
    cvs.submit_character_version_for_review(session, version_id)
    cvs.approve_character_version(session, version_id, decided_by="founder")


def test_create_character_version_auto_numbers(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    v1 = cvs.create_character_version(session, character.id)
    v2 = cvs.create_character_version(session, character.id)
    assert (v1.version_number, v2.version_number) == ("v01", "v02")
    assert v1.status == CharacterVersionStatus.DRAFT


def test_create_character_version_rejects_duplicate_explicit_number(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    cvs.create_character_version(session, character.id, version_number="v01")
    with pytest.raises(ConflictError):
        cvs.create_character_version(session, character.id, version_number="v01")


def test_update_character_version_rejected_once_approved(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    _approve_with_complete_lock(session, cvs, character, version.id)

    with pytest.raises(InvalidTransitionError):
        cvs.update_character_version(session, version.id, visual_summary="changed")


def test_submit_for_review_requires_draft_status(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    cvs.submit_character_version_for_review(session, version.id)
    with pytest.raises(InvalidTransitionError):
        cvs.submit_character_version_for_review(session, version.id)  # already in_review


def test_approve_character_version_requires_in_review(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    with pytest.raises(InvalidTransitionError):
        cvs.approve_character_version(session, version.id)  # still draft


def test_reject_character_version_requires_notes(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    cvs.submit_character_version_for_review(session, version.id)
    with pytest.raises(ValidationError):
        cvs.reject_character_version(session, version.id, notes="")


def test_reject_character_version_returns_to_draft_with_history(session: Session) -> None:
    cvs = CharacterVersionService()
    approvals = ApprovalService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    cvs.submit_character_version_for_review(session, version.id)

    cvs.reject_character_version(session, version.id, notes="Outfit color is off-palette.")

    assert version.status == CharacterVersionStatus.DRAFT
    assert version.review_notes == "Outfit color is off-palette."
    history = approvals.list_approval_history(session, "character_version", version.id)
    assert [r.decision.value for r in history] == ["rejected"]


def test_set_active_character_version_requires_approved_canon(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    with pytest.raises(InvalidTransitionError):
        cvs.set_active_character_version(session, character.id, version.id)


def test_set_active_character_version_switches_transactionally_and_keeps_history(
    session: Session,
) -> None:
    cvs = CharacterVersionService()
    character = _character(session)

    v1 = cvs.create_character_version(session, character.id)
    _approve_with_complete_lock(session, cvs, character, v1.id)
    cvs.set_active_character_version(session, character.id, v1.id)
    assert character.active_version_id == v1.id

    v2 = cvs.create_character_version(session, character.id)
    _approve_with_complete_lock(session, cvs, character, v2.id)
    cvs.set_active_character_version(session, character.id, v2.id)

    assert character.active_version_id == v2.id
    assert v1.status == CharacterVersionStatus.APPROVED_CANON  # untouched, still in history
    assert v1 in character.versions
    assert v2 in character.versions


def test_set_active_character_version_rejects_version_from_other_character(
    session: Session,
) -> None:
    cvs = CharacterVersionService()
    melissa = _character(session)
    bilsan = Character(slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    session.add(bilsan)
    session.flush()

    bilsan_version = cvs.create_character_version(session, bilsan.id)
    _approve_with_complete_lock(session, cvs, bilsan, bilsan_version.id)

    with pytest.raises(ValidationError):
        cvs.set_active_character_version(session, melissa.id, bilsan_version.id)


def test_add_character_reference_rejects_non_image_video_asset(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    voice_asset = _approved_image_asset(
        session, asset_type=AssetType.VOICE, relative_path="characters/melissa/versions/v01/voice.wav"
    )
    with pytest.raises(ValidationError, match="image or video"):
        cvs.add_character_reference(session, character_id=character.id, asset_id=voice_asset.id)


def test_add_character_reference_rejects_unapproved_asset(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    draft_asset = _approved_image_asset(session, approval_status=ApprovalStatus.DRAFT)
    with pytest.raises(ValidationError, match="approved"):
        cvs.add_character_reference(session, character_id=character.id, asset_id=draft_asset.id)


def test_add_character_reference_success(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    asset = _approved_image_asset(session)
    reference = cvs.add_character_reference(
        session, character_id=character.id, asset_id=asset.id, label="front_view"
    )
    assert reference.label == "front_view"
    assert cvs.list_character_references(session, character.id) == [reference]


def test_add_character_reference_rejects_duplicate_asset_link(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    asset = _approved_image_asset(session)
    cvs.add_character_reference(session, character_id=character.id, asset_id=asset.id)
    with pytest.raises(ConflictError):
        cvs.add_character_reference(session, character_id=character.id, asset_id=asset.id)


def test_remove_character_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    asset = _approved_image_asset(session)
    reference = cvs.add_character_reference(session, character_id=character.id, asset_id=asset.id)
    cvs.remove_character_reference(session, reference.id)
    assert cvs.list_character_references(session, character.id) == []


def test_remove_character_reference_not_found(session: Session) -> None:
    cvs = CharacterVersionService()
    with pytest.raises(NotFoundError):
        cvs.remove_character_reference(session, uuid.uuid4())


def test_validate_character_lock_reports_all_missing_fields(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)  # everything empty

    result = cvs.validate_character_lock(session, version.id)

    assert result.is_complete is False
    assert set(result.missing_fields) == {
        "visual_summary",
        "master_prompt",
        "negative_prompt",
        "color_palette",
        "relative_height",
        "approved_reference_assets",
    }


def test_validate_character_lock_complete_when_all_fields_and_reference_present(
    session: Session,
) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(
        session,
        character.id,
        visual_summary="Two ponytails, denim dress.",
        master_prompt="Melissa: 6yo girl...",
        negative_prompt="no extra characters",
        color_palette=["denim blue", "red"],
        relative_height="taller than Bilsan",
    )
    asset = _approved_image_asset(session)
    cvs.add_character_reference(session, character_id=character.id, character_version_id=version.id, asset_id=asset.id)

    result = cvs.validate_character_lock(session, version.id)
    assert result.is_complete is True
    assert result.missing_fields == []


def test_validate_prompt_completeness_ignores_reference_requirement(session: Session) -> None:
    """Unlike validate_character_lock, this narrower check never requires
    an approved reference asset — see its docstring for why (avoiding a
    chicken-and-egg block on the very workflow that produces a
    version's first reference image)."""
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id, **_LOCK_FIELDS)

    result = cvs.validate_prompt_completeness(session, version.id)

    assert result.is_complete is True
    assert result.missing_fields == []


def test_validate_prompt_completeness_reports_missing_prompt_fields(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)  # everything empty

    result = cvs.validate_prompt_completeness(session, version.id)

    assert result.is_complete is False
    assert set(result.missing_fields) == {
        "visual_summary",
        "master_prompt",
        "negative_prompt",
        "color_palette",
        "relative_height",
    }
    assert "approved_reference_assets" not in result.missing_fields


def test_approve_character_version_rejects_incomplete_lock(session: Session) -> None:
    """A version with complete prompt fields but no reference asset yet
    still cannot become approved_canon — approval requires the *full*
    Character Lock, not just prompt completeness."""
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id, **_LOCK_FIELDS)
    cvs.submit_character_version_for_review(session, version.id)

    with pytest.raises(CharacterLockIncompleteError) as exc_info:
        cvs.approve_character_version(session, version.id, decided_by="founder")

    assert exc_info.value.missing_fields == ["approved_reference_assets"]
    assert version.status == CharacterVersionStatus.IN_REVIEW  # unchanged


def test_approve_character_version_rejects_missing_prompt_fields_too(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)  # everything empty
    cvs.submit_character_version_for_review(session, version.id)

    with pytest.raises(CharacterLockIncompleteError) as exc_info:
        cvs.approve_character_version(session, version.id, decided_by="founder")

    assert "master_prompt" in exc_info.value.missing_fields
    assert "approved_reference_assets" in exc_info.value.missing_fields


def test_approve_character_version_succeeds_with_complete_lock(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    _approve_with_complete_lock(session, cvs, character, version.id)
    assert version.status == CharacterVersionStatus.APPROVED_CANON


# --- Canon Reference (Milestone 8) ------------------------------------------


def test_get_canon_reference_returns_none_when_none_marked(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    asset = _approved_image_asset(session)
    cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id, asset_id=asset.id
    )

    assert cvs.get_canon_reference(session, version.id) is None


def test_get_canon_reference_returns_the_marked_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    asset = _approved_image_asset(session)
    reference = cvs.add_character_reference(
        session,
        character_id=character.id,
        character_version_id=version.id,
        asset_id=asset.id,
        is_current_canon=True,
    )

    canon = cvs.get_canon_reference(session, version.id)
    assert canon is not None
    assert canon.id == reference.id


def test_get_canon_reference_returns_none_when_ambiguous(session: Session) -> None:
    """Two references both flagged canon (a data-integrity edge case,
    never producible via set_canon_reference itself) must never let a
    caller silently guess which one wins."""
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    asset_a = _approved_image_asset(session, relative_path="characters/melissa/versions/v01/a.png", checksum="a" * 64)
    asset_b = _approved_image_asset(session, relative_path="characters/melissa/versions/v01/b.png", checksum="b" * 64)
    cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id,
        asset_id=asset_a.id, is_current_canon=True,
    )
    cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id,
        asset_id=asset_b.id, is_current_canon=True,
    )

    assert cvs.get_canon_reference(session, version.id) is None


def test_set_canon_reference_marks_the_given_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    asset = _approved_image_asset(session)
    reference = cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id, asset_id=asset.id
    )

    cvs.set_canon_reference(session, reference.id)

    assert cvs.get_canon_reference(session, version.id).id == reference.id


def test_set_canon_reference_unsets_previous_sibling_canon(session: Session) -> None:
    cvs = CharacterVersionService()
    character = _character(session)
    version = cvs.create_character_version(session, character.id)
    asset_a = _approved_image_asset(session, relative_path="characters/melissa/versions/v01/a.png", checksum="a" * 64)
    asset_b = _approved_image_asset(session, relative_path="characters/melissa/versions/v01/b.png", checksum="b" * 64)
    ref_a = cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id,
        asset_id=asset_a.id, is_current_canon=True,
    )
    ref_b = cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id, asset_id=asset_b.id,
    )

    cvs.set_canon_reference(session, ref_b.id)

    assert cvs.get_canon_reference(session, version.id).id == ref_b.id
    session.refresh(ref_a)
    assert ref_a.is_current_canon is False


def test_set_canon_reference_raises_not_found_for_unknown_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    with pytest.raises(NotFoundError):
        cvs.set_canon_reference(session, uuid.uuid4())
