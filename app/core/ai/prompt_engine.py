"""PromptEngine — resolves and renders a prompt into a ``GenerationRequest``.

A thin wrapper around the existing
:class:`~app.core.services.prompt_template_service.PromptTemplateService`
— rendering logic is never duplicated here, only reused. This is also
the actual mechanism behind "Character Lock" consistency: when
``character_version_id`` is given, that version's locked prompt fields
and approved reference art are merged in, so a workflow cannot build an
image/video/voice prompt for a character without going through its
locked design.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.ai.provider_interface import GenerationRequest, Modality
from app.core.db.enums import PromptType
from app.core.models import CharacterVersion
from app.core.services.exceptions import NotFoundError
from app.core.services.prompt_template_service import PromptTemplateService

_MODALITY_BY_PROMPT_TYPE: dict[PromptType, Modality] = {
    PromptType.IMAGE: "image",
    PromptType.VIDEO: "video",
    PromptType.VOICE: "voice",
    PromptType.MUSIC: "song",
    PromptType.TEXT: "text",
}


class PromptEngine:
    """Builds a ready-to-send :class:`GenerationRequest` from a prompt template."""

    def __init__(self, prompt_templates: PromptTemplateService | None = None) -> None:
        self._prompts = prompt_templates or PromptTemplateService()

    def build_request(
        self,
        session: Session,
        *,
        prompt_template_id: uuid.UUID,
        variables: dict[str, object] | None = None,
        character_version_id: uuid.UUID | None = None,
        negative_prompt_text: str | None = None,
        reference_asset_paths: list[str] | None = None,
        parameters: dict[str, object] | None = None,
    ) -> GenerationRequest:
        """Render ``prompt_template_id`` and wrap the result as a ``GenerationRequest``.

        The request's ``modality`` is derived from the template's own
        ``prompt_type`` (image/video/voice/music/text) — a workflow
        never has to (and cannot) pass a mismatched modality.

        Raises:
            NotFoundError: The template, or ``character_version_id``,
                doesn't exist.
            TemplateRenderError: The template references a variable not
                present in ``variables`` (after the character-lock merge).
        """
        template = self._prompts.get_prompt_template(session, prompt_template_id)
        modality = _MODALITY_BY_PROMPT_TYPE[template.prompt_type]

        merged_variables = dict(variables or {})
        negative_prompt = negative_prompt_text
        references = list(reference_asset_paths or [])

        if character_version_id is not None:
            version = self._get_character_version(session, character_version_id)
            merged_variables.setdefault("character_master_prompt", version.master_prompt or "")
            merged_variables.setdefault("character_visual_summary", version.visual_summary or "")
            merged_variables.setdefault(
                "character_color_palette", ", ".join(version.color_palette)
            )
            merged_variables.setdefault(
                "character_relative_height", version.relative_height or ""
            )
            if negative_prompt is None and version.negative_prompt:
                negative_prompt = version.negative_prompt
            references += [
                reference.asset.relative_path
                for reference in version.references
                if reference.asset is not None
            ]

        rendered_text = self._prompts.render_prompt_template(
            session, prompt_template_id, merged_variables
        )

        return GenerationRequest(
            modality=modality,
            prompt_text=rendered_text,
            negative_prompt_text=negative_prompt,
            reference_asset_paths=references,
            parameters=dict(parameters or {}),
        )

    @staticmethod
    def _get_character_version(session: Session, version_id: uuid.UUID) -> CharacterVersion:
        version = session.get(CharacterVersion, version_id)
        if version is None:
            raise NotFoundError(f"CharacterVersion {version_id} not found.")
        return version
