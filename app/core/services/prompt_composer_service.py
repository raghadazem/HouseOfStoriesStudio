"""PromptComposerService — the Episode Workspace's Storyboard Prompt Composer.

Assembles a plain, human-editable prompt string for a Scene from
existing data only: the scene's own visual description/camera/location,
every present character's locked design (``CharacterVersion.master_prompt``/
``visual_summary``/``negative_prompt`` — the same fields
``app.core.ai.prompt_engine.PromptEngine`` merges for an actual
generation call), and any global/episode-reusable style
``PromptTemplate``s via ``PromptTemplateService.resolve_global_and_contextual_prompts``.

Deliberately **not** part of ``app.core.ai`` and never calls an AI
provider: ``PromptEngine`` renders a Jinja ``PromptTemplate`` into a
``GenerationRequest`` for a provider call; this composer does neither —
it builds and returns plain strings for a person to read, store, and
hand-edit. See ``docs/29_EPISODE_WORKSPACE_STATUS.md``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.db.enums import PromptCategory
from app.core.models import CharacterVersion, Scene
from app.core.services.exceptions import NotFoundError
from app.core.services.prompt_template_service import PromptTemplateService


@dataclass(frozen=True)
class ComposedPrompt:
    """The result of :meth:`PromptComposerService.compose_scene_prompt`."""

    prompt_text: str
    negative_prompt_text: str


class PromptComposerService:
    """Composes (never generates) a Scene's prompt from existing locked data."""

    def __init__(self, prompt_templates: PromptTemplateService | None = None) -> None:
        self._prompts = prompt_templates or PromptTemplateService()

    def compose_scene_prompt(self, session: Session, scene_id: uuid.UUID) -> ComposedPrompt:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise NotFoundError(f"Scene {scene_id} not found.")

        sections: list[str] = []

        style_templates = self._prompts.resolve_global_and_contextual_prompts(
            session, category=PromptCategory.IMAGE, episode_id=scene.episode_id
        )
        if style_templates:
            sections.append(
                "Visual style: " + " ".join(t.text_en.strip() for t in style_templates if t.text_en)
            )

        character_blocks: list[str] = []
        negative_parts: list[str] = []
        for character in scene.characters_present:
            if character.active_version_id is None:
                continue
            version = session.get(CharacterVersion, character.active_version_id)
            if version is None:
                continue
            block_parts = [p for p in (version.master_prompt, version.visual_summary) if p]
            if block_parts:
                character_blocks.append(f"{character.name_en}: " + " ".join(block_parts))
            if version.negative_prompt:
                negative_parts.append(version.negative_prompt)
        if character_blocks:
            sections.append("Characters: " + " | ".join(character_blocks))

        if scene.description:
            sections.append(f"Visual description: {scene.description}")
        if scene.camera_direction:
            sections.append(f"Camera: {scene.camera_direction}")
        if scene.location:
            sections.append(f"Environment: {scene.location}")

        prompt_text = "\n".join(sections)

        if scene.negative_prompt_text:
            negative_parts.append(scene.negative_prompt_text)
        # De-duplicate while preserving first-seen order — a character
        # referenced via more than one path, or re-composing after a
        # manual edit that repeated a character's own negative prompt,
        # should never produce a repeated clause.
        seen: set[str] = set()
        deduped_negative = []
        for part in negative_parts:
            normalized = part.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped_negative.append(normalized)
        negative_prompt_text = ", ".join(deduped_negative)

        return ComposedPrompt(prompt_text=prompt_text, negative_prompt_text=negative_prompt_text)
