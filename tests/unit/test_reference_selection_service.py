"""Tests for ReferenceSelectionService: deterministic, strict, multi-character."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode, Scene
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.reference_selection_service import ReferenceSelectionService

_LOCK_FIELDS = {
    "visual_summary": "Two ponytails, denim dress.",
    "master_prompt": "Melissa: 6yo girl...",
    "negative_prompt": "no extra characters",
    "color_palette": ["denim blue", "red"],
    "relative_height": "taller than Bilsan",
}


def _approved_active_character(
    session: Session, cvs: CharacterVersionService, slug: str, name_en: str, *, with_canon: bool = True
) -> Character:
    """A Character with an active, approved_canon version — optionally with
    a canon reference already selected."""
    character = Character(slug=slug, name_ar=slug, name_en=name_en)
    session.add(character)
    session.flush()
    version = cvs.create_character_version(session, character.id, **_LOCK_FIELDS)
    asset = Asset(
        asset_type=AssetType.IMAGE,
        original_filename="ref.png",
        relative_path=f"characters/{slug}/versions/{version.id}/ref.png",
        checksum=uuid.uuid4().hex.ljust(64, "0"),
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(asset)
    session.flush()
    reference = cvs.add_character_reference(
        session,
        character_id=character.id,
        character_version_id=version.id,
        asset_id=asset.id,
        label="front view",
    )
    if with_canon:
        cvs.set_canon_reference(session, reference.id)
    cvs.submit_character_version_for_review(session, version.id)
    cvs.approve_character_version(session, version.id, decided_by="founder")
    cvs.set_active_character_version(session, character.id, version.id)
    return character


def _scene(session: Session, characters: list[Character]) -> Scene:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    scene = Scene(episode_id=episode.id, order_index=1)
    scene.characters_present = characters
    session.add(scene)
    session.flush()
    return scene


def test_select_references_single_character(session: Session) -> None:
    cvs = CharacterVersionService()
    melissa = _approved_active_character(session, cvs, "melissa", "Melissa")
    scene = _scene(session, [melissa])

    result = ReferenceSelectionService(cvs).select_references(session, scene)

    assert result.is_complete
    assert len(result.selected) == 1
    assert result.selected[0].character.id == melissa.id


def test_select_references_multi_character_deterministic_order(session: Session) -> None:
    cvs = CharacterVersionService()
    # Created in reverse-alphabetical order to prove sorting, not insertion order, wins.
    tortor = _approved_active_character(session, cvs, "tortor", "Tortor")
    melissa = _approved_active_character(session, cvs, "melissa", "Melissa")
    bilsan = _approved_active_character(session, cvs, "bilsan", "Bilsan")
    scene = _scene(session, [tortor, melissa, bilsan])

    result = ReferenceSelectionService(cvs).select_references(session, scene)

    assert result.is_complete
    assert [s.character.slug for s in result.selected] == ["bilsan", "melissa", "tortor"]


def test_select_references_blocks_character_with_no_canon_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    melissa = _approved_active_character(session, cvs, "melissa", "Melissa", with_canon=False)
    scene = _scene(session, [melissa])

    result = ReferenceSelectionService(cvs).select_references(session, scene)

    assert not result.is_complete
    assert result.selected == []
    assert result.unresolved[0][0].id == melissa.id
    assert "no single canon reference" in result.unresolved[0][1]


def test_select_references_blocks_character_with_no_active_version(session: Session) -> None:
    character = Character(slug="new-char", name_ar="ش", name_en="New")
    session.add(character)
    session.flush()
    scene = _scene(session, [character])

    result = ReferenceSelectionService().select_references(session, scene)

    assert not result.is_complete
    assert "has no active CharacterVersion" in result.unresolved[0][1]


def test_select_references_blocks_character_with_non_canon_status_version(session: Session) -> None:
    cvs = CharacterVersionService()
    character = Character(slug="draft-char", name_ar="ش", name_en="Draft")
    session.add(character)
    session.flush()
    version = cvs.create_character_version(session, character.id, **_LOCK_FIELDS)
    # Active version pointer set directly (bypassing set_active_character_version's
    # approved_canon requirement) to exercise the defensive status re-check.
    character.active_version_id = version.id
    session.flush()
    scene = _scene(session, [character])

    result = ReferenceSelectionService(cvs).select_references(session, scene)

    assert not result.is_complete
    assert "not approved_canon" in result.unresolved[0][1]


def test_select_references_partial_resolution_names_only_the_blocked_character(
    session: Session,
) -> None:
    cvs = CharacterVersionService()
    melissa = _approved_active_character(session, cvs, "melissa", "Melissa")
    bilsan = _approved_active_character(session, cvs, "bilsan", "Bilsan", with_canon=False)
    scene = _scene(session, [melissa, bilsan])

    result = ReferenceSelectionService(cvs).select_references(session, scene)

    assert not result.is_complete
    assert [s.character.slug for s in result.selected] == ["melissa"]
    assert result.unresolved[0][0].slug == "bilsan"


def test_select_references_empty_cast_is_complete_with_nothing_selected(session: Session) -> None:
    scene = _scene(session, [])

    result = ReferenceSelectionService().select_references(session, scene)

    assert result.is_complete
    assert result.selected == []
