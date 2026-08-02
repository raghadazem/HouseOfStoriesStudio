"""Tests for PromptTemplateService: rendering, versioning, resolution."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import PromptCategory, PromptType
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import (
    ConflictError,
    InvalidTransitionError,
    TemplateRenderError,
)
from app.core.services.prompt_template_service import PromptTemplateService


def _template(pts: PromptTemplateService, session: Session, **overrides):
    defaults = {
        "name": "melissa_master_prompt",
        "category": PromptCategory.CHARACTER,
        "prompt_type": PromptType.IMAGE,
        "text_en": "Melissa, {{ trait }}",
        "is_reusable": True,
    }
    defaults.update(overrides)
    return pts.create_prompt_template(session, **defaults)


def test_create_prompt_template_rejects_duplicate_name_version(session: Session) -> None:
    pts = PromptTemplateService()
    _template(pts, session)
    with pytest.raises(ConflictError):
        _template(pts, session)


def test_create_prompt_template_global_is_valid(session: Session) -> None:
    pts = PromptTemplateService()
    template = pts.create_prompt_template(
        session,
        name="visual_style_block",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="Warm colors, expressive characters, stylized 3D look.",
        is_reusable=True,
    )
    assert template.character_id is None
    assert template.episode_id is None
    assert template.scene_id is None


def test_render_prompt_template_supports_arabic_variables(session: Session) -> None:
    pts = PromptTemplateService()
    template = pts.create_prompt_template(
        session,
        name="scene_prompt",
        category=PromptCategory.STORY,
        prompt_type=PromptType.TEXT,
        text_en="Scene: {{ location_ar }}",
    )
    rendered = pts.render_prompt_template(session, template.id, {"location_ar": "الغابة"})
    assert rendered == "Scene: الغابة"


def test_render_prompt_template_missing_variable_raises_clear_error(session: Session) -> None:
    pts = PromptTemplateService()
    template = _template(pts, session)
    with pytest.raises(TemplateRenderError, match="trait"):
        pts.render_prompt_template(session, template.id, {})


def test_validate_template_variables_lists_all_missing(session: Session) -> None:
    pts = PromptTemplateService()
    missing = pts.validate_template_variables(
        "{{ a }} and {{ b }} and {{ a }}", {"b": "known"}
    )
    assert missing == ["a"]


def test_render_prompt_template_sandbox_blocks_dangerous_constructs(session: Session) -> None:
    """Even if a malicious template string somehow got in, it can't reach Python internals."""
    pts = PromptTemplateService()
    template = pts.create_prompt_template(
        session,
        name="unsafe_attempt",
        category=PromptCategory.STORY,
        prompt_type=PromptType.TEXT,
        text_en="{{ ''.__class__.__mro__[1].__subclasses__() }}",
    )
    with pytest.raises(TemplateRenderError):
        pts.render_prompt_template(session, template.id, {})


def test_update_prompt_template_blocked_once_approved(session: Session) -> None:
    pts = PromptTemplateService()
    approvals = ApprovalService()
    template = _template(pts, session)
    approvals.approve_entity(session, "prompt_template", template.id)

    with pytest.raises(InvalidTransitionError):
        pts.update_prompt_template(session, template.id, text_en="changed")


def test_increment_template_version_creates_new_row_preserving_original(session: Session) -> None:
    pts = PromptTemplateService()
    approvals = ApprovalService()
    v1 = _template(pts, session)
    approvals.approve_entity(session, "prompt_template", v1.id)

    v2 = pts.increment_template_version(session, v1.id, text_en="Melissa, {{ trait }}, v2")

    assert v2.version == "v02"
    assert v2.name == v1.name
    assert v1.text_en == "Melissa, {{ trait }}"  # untouched historical version


def test_archive_prompt_template(session: Session) -> None:
    pts = PromptTemplateService()
    template = _template(pts, session)
    pts.archive_prompt_template(session, template.id)
    assert template.is_archived is True
    assert pts.list_prompt_templates(session) == []
    assert pts.list_prompt_templates(session, include_archived=True) == [template]


def test_resolve_global_and_contextual_prompts(session: Session) -> None:
    pts = PromptTemplateService()
    pts.create_prompt_template(
        session,
        name="style_lock",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="warm colors",
        is_reusable=True,
    )
    from app.core.models import Character

    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()

    pts.create_prompt_template(
        session,
        name="melissa_specific",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="melissa details",
        character_id=character.id,
    )

    resolved = pts.resolve_global_and_contextual_prompts(session, character_id=character.id)
    names = {t.name for t in resolved}
    assert "style_lock" in names
    assert "melissa_specific" in names
