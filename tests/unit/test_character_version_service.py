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
    cvs.submit_character_version_for_review(session, version.id)
    cvs.approve_character_version(session, version.id, decided_by="founder")

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
    cvs.submit_character_version_for_review(session, v1.id)
    cvs.approve_character_version(session, v1.id, decided_by="founder")
    cvs.set_active_character_version(session, character.id, v1.id)
    assert character.active_version_id == v1.id

    v2 = cvs.create_character_version(session, character.id)
    cvs.submit_character_version_for_review(session, v2.id)
    cvs.approve_character_version(session, v2.id, decided_by="founder")
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
    cvs.submit_character_version_for_review(session, bilsan_version.id)
    cvs.approve_character_version(session, bilsan_version.id)

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
