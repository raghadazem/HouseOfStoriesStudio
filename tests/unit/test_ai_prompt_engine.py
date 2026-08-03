"""Tests for PromptEngine: template rendering + Character Lock merge."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.ai.prompt_engine import PromptEngine
from app.core.db.enums import ApprovalStatus, AssetType, PromptCategory, PromptType
from app.core.models import Asset, Character, CharacterReference, CharacterVersion
from app.core.services.exceptions import NotFoundError, TemplateRenderError
from app.core.services.prompt_template_service import PromptTemplateService


def _character_version(session: Session, **overrides: object) -> CharacterVersion:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    defaults: dict[str, object] = {
        "character_id": character.id,
        "version_number": "v01",
        "master_prompt": "a young girl with curly brown hair",
        "negative_prompt": "no modern clothing",
        "color_palette": ["#ffcc00"],
        "relative_height": "child",
    }
    defaults.update(overrides)
    version = CharacterVersion(**defaults)
    session.add(version)
    session.flush()
    return version


def test_build_request_renders_simple_template(session: Session) -> None:
    template = PromptTemplateService().create_prompt_template(
        session,
        name="simple_scene",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A scene showing {{ location }}.",
    )
    request = PromptEngine().build_request(
        session, prompt_template_id=template.id, variables={"location": "a forest"}
    )
    assert request.modality == "image"
    assert request.prompt_text == "A scene showing a forest."
    assert request.negative_prompt_text is None
    assert request.reference_asset_paths == []


def test_build_request_derives_modality_from_prompt_type(session: Session) -> None:
    template = PromptTemplateService().create_prompt_template(
        session,
        name="voice_greeting",
        category=PromptCategory.VOICE,
        prompt_type=PromptType.VOICE,
        text_en="Say hello.",
    )
    request = PromptEngine().build_request(session, prompt_template_id=template.id)
    assert request.modality == "voice"


def test_build_request_missing_variable_raises(session: Session) -> None:
    template = PromptTemplateService().create_prompt_template(
        session,
        name="needs_var",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="{{ missing }}",
    )
    with pytest.raises(TemplateRenderError):
        PromptEngine().build_request(session, prompt_template_id=template.id)


def test_build_request_unknown_template_raises(session: Session) -> None:
    with pytest.raises(NotFoundError):
        PromptEngine().build_request(session, prompt_template_id=uuid.uuid4())


def test_build_request_unknown_character_version_raises(session: Session) -> None:
    template = PromptTemplateService().create_prompt_template(
        session,
        name="char_scene",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="{{ character_master_prompt }}",
    )
    with pytest.raises(NotFoundError):
        PromptEngine().build_request(
            session, prompt_template_id=template.id, character_version_id=uuid.uuid4()
        )


def test_build_request_merges_character_lock_fields(session: Session) -> None:
    version = _character_version(session)
    reference_asset = Asset(
        asset_type=AssetType.IMAGE,
        original_filename="ref.png",
        relative_path="characters/melissa/versions/v01/ref.png",
        checksum="a" * 64,
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(reference_asset)
    session.flush()
    session.add(
        CharacterReference(
            character_id=version.character_id,
            character_version_id=version.id,
            asset_id=reference_asset.id,
        )
    )
    session.flush()

    template = PromptTemplateService().create_prompt_template(
        session,
        name="character_ref",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="{{ character_master_prompt }} | palette: {{ character_color_palette }}",
    )

    request = PromptEngine().build_request(
        session, prompt_template_id=template.id, character_version_id=version.id
    )

    assert "a young girl with curly brown hair" in request.prompt_text
    assert "#ffcc00" in request.prompt_text
    assert request.negative_prompt_text == "no modern clothing"
    assert request.reference_asset_paths == ["characters/melissa/versions/v01/ref.png"]


def test_build_request_explicit_negative_prompt_wins_over_character_lock(
    session: Session,
) -> None:
    version = _character_version(session)
    template = PromptTemplateService().create_prompt_template(
        session,
        name="character_ref_2",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="{{ character_master_prompt }}",
    )
    request = PromptEngine().build_request(
        session,
        prompt_template_id=template.id,
        character_version_id=version.id,
        negative_prompt_text="explicit override",
    )
    assert request.negative_prompt_text == "explicit override"
