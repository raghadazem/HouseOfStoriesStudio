"""Tests for PromptComposerService: pure text assembly, never an AI call."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import CharacterVersionStatus, PromptCategory, PromptType
from app.core.models import Character, CharacterVersion, Episode, PromptTemplate
from app.core.services.exceptions import NotFoundError
from app.core.services.prompt_composer_service import PromptComposerService
from app.core.services.scene_service import SceneService


def _episode(session: Session) -> Episode:
    episode = Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    return episode


def _character_with_active_version(
    session: Session, *, slug: str, name_en: str, master_prompt: str, negative_prompt: str | None
) -> Character:
    character = Character(slug=slug, name_ar=slug, name_en=name_en)
    session.add(character)
    session.flush()
    version = CharacterVersion(
        character_id=character.id,
        version_number="v01",
        status=CharacterVersionStatus.APPROVED_CANON,
        master_prompt=master_prompt,
        visual_summary=f"{name_en} visual summary",
        negative_prompt=negative_prompt,
    )
    session.add(version)
    session.flush()
    character.active_version_id = version.id
    session.flush()
    return character


def test_compose_scene_prompt_rejects_missing_scene(session: Session) -> None:
    with pytest.raises(NotFoundError):
        PromptComposerService().compose_scene_prompt(session, uuid.uuid4())


def test_compose_scene_prompt_with_no_characters_or_style(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(
        session, episode.id, description="A turtle on a riverbank",
        camera_direction="Wide shot", location="The Valley",
    )

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    assert "Visual description: A turtle on a riverbank" in composed.prompt_text
    assert "Camera: Wide shot" in composed.prompt_text
    assert "Environment: The Valley" in composed.prompt_text
    assert "Characters:" not in composed.prompt_text
    assert composed.negative_prompt_text == ""


def test_compose_scene_prompt_merges_one_characters_locked_design(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    melissa = _character_with_active_version(
        session, slug="melissa", name_en="Melissa",
        master_prompt="6-year-old girl, curly brown hair", negative_prompt="no adult features",
    )
    scene = ss.add_scene(session, episode.id, description="Exploring the forest")
    ss.set_scene_characters(session, scene.id, [melissa.id])

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    assert "Melissa" in composed.prompt_text
    assert "curly brown hair" in composed.prompt_text
    assert composed.negative_prompt_text == "no adult features"


def test_compose_scene_prompt_merges_multiple_characters(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    melissa = _character_with_active_version(
        session, slug="melissa", name_en="Melissa", master_prompt="curious older sister",
        negative_prompt="no adult features",
    )
    bilsan = _character_with_active_version(
        session, slug="bilsan", name_en="Bilsan", master_prompt="funny younger sister",
        negative_prompt="no adult features",
    )
    scene = ss.add_scene(session, episode.id)
    ss.set_scene_characters(session, scene.id, [melissa.id, bilsan.id])

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    assert "curious older sister" in composed.prompt_text
    assert "funny younger sister" in composed.prompt_text
    # Both characters share the same negative prompt text -- de-duplicated, not repeated.
    assert composed.negative_prompt_text == "no adult features"


def test_compose_scene_prompt_includes_global_reusable_style_template(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    session.add(
        PromptTemplate(
            name="house_style", category=PromptCategory.IMAGE, prompt_type=PromptType.IMAGE,
            text_en="Warm colors, soft 3D-look shading.", is_reusable=True,
        )
    )
    session.flush()
    scene = ss.add_scene(session, episode.id)

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    assert "Visual style:" in composed.prompt_text
    assert "Warm colors, soft 3D-look shading." in composed.prompt_text


def test_compose_scene_prompt_merges_manual_negative_prompt_without_duplicating(
    session: Session,
) -> None:
    ss = SceneService()
    episode = _episode(session)
    melissa = _character_with_active_version(
        session, slug="melissa", name_en="Melissa", master_prompt="a girl",
        negative_prompt="blurry",
    )
    scene = ss.add_scene(session, episode.id)
    ss.set_scene_characters(session, scene.id, [melissa.id])
    ss.update_scene(session, scene.id, negative_prompt_text="blurry, extra limbs")

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    # "blurry" (from the character) and the manually-entered "blurry,
    # extra limbs" are different strings -- both survive, in order,
    # with no exact-duplicate repeated.
    assert composed.negative_prompt_text == "blurry, blurry, extra limbs"


def test_compose_scene_prompt_ignores_character_with_no_active_version(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    character = Character(slug="unlocked", name_ar="x", name_en="Unlocked")
    session.add(character)
    session.flush()
    scene = ss.add_scene(session, episode.id, description="A scene")
    ss.set_scene_characters(session, scene.id, [character.id])

    composed = PromptComposerService().compose_scene_prompt(session, scene.id)

    assert "Characters:" not in composed.prompt_text
    assert "Visual description: A scene" in composed.prompt_text
