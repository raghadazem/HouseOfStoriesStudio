"""Tests for Character, CharacterVersion, and CharacterReference."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType, CharacterVersionStatus
from app.core.models import Asset, Character, CharacterReference, CharacterVersion


def _make_asset(**overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "melissa_front_v01.png",
        "relative_path": "characters/melissa/reference/melissa_front_v01.png",
        "checksum": "a" * 64,
        "approval_status": ApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    return Asset(**defaults)


def test_character_round_trips_arabic_and_english_names(session: Session) -> None:
    melissa = Character(
        slug="melissa",
        name_ar="ميليسا",
        name_en="Melissa",
        age=6,
        role="older sister",
        traits=["brave", "curious", "kind", "loves nature"],
    )
    session.add(melissa)
    session.commit()

    session.expunge_all()
    reloaded = session.get(Character, melissa.id)
    assert reloaded is not None
    assert reloaded.name_ar == "ميليسا"
    assert reloaded.traits == ["brave", "curious", "kind", "loves nature"]


def test_character_slug_must_be_unique(session: Session) -> None:
    session.add(Character(slug="melissa", name_ar="ميليسا", name_en="Melissa"))
    session.commit()

    session.add(Character(slug="melissa", name_ar="بيلسان", name_en="Bilsan"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_character_has_timestamps_and_uuid_primary_key(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.commit()

    assert isinstance(melissa.id, uuid.UUID)
    assert melissa.created_at is not None
    assert melissa.updated_at is not None


def test_character_version_unique_per_character(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()

    session.add(CharacterVersion(character_id=melissa.id, version_number="v01"))
    session.commit()

    session.add(CharacterVersion(character_id=melissa.id, version_number="v01"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_version_number_allowed_across_different_characters(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    bilsan = Character(slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    session.add_all([melissa, bilsan])
    session.flush()

    session.add(CharacterVersion(character_id=melissa.id, version_number="v01"))
    session.add(CharacterVersion(character_id=bilsan.id, version_number="v01"))
    session.commit()  # must not raise


def test_character_version_defaults_to_draft_status(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()

    version = CharacterVersion(character_id=melissa.id, version_number="v01")
    session.add(version)
    session.commit()

    assert version.status == CharacterVersionStatus.DRAFT


def test_character_reference_links_asset_to_character_and_version(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()

    version = CharacterVersion(character_id=melissa.id, version_number="v01")
    session.add(version)
    session.flush()

    asset = _make_asset()
    session.add(asset)
    session.flush()

    reference = CharacterReference(
        character_id=melissa.id,
        character_version_id=version.id,
        asset_id=asset.id,
        label="front_view",
        is_current_canon=True,
    )
    session.add(reference)
    session.commit()

    assert melissa.references[0].asset.relative_path.endswith("melissa_front_v01.png")
    assert version.references[0].id == reference.id


def test_character_reference_asset_id_must_be_unique(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()

    asset = _make_asset()
    session.add(asset)
    session.flush()

    session.add(CharacterReference(character_id=melissa.id, asset_id=asset.id))
    session.commit()

    session.add(CharacterReference(character_id=melissa.id, asset_id=asset.id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_character_cascades_to_versions_and_references(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()
    session.add(CharacterVersion(character_id=melissa.id, version_number="v01"))
    session.commit()

    character_id = melissa.id
    session.delete(melissa)
    session.commit()

    remaining = (
        session.query(CharacterVersion).filter_by(character_id=character_id).count()
    )
    assert remaining == 0
