"""ReferenceSelectionService — deterministic reference-image selection for scene generation.

Milestone 8: a scene may feature several characters at once, and each
one's approved reference art must be sent to the provider to keep the
generated image on-model. This service answers exactly one question,
for one scene, with no AI and no randomness: "which single reference
asset represents each present character right now?"

Strict, per the founder's Milestone 8 decision: character consistency
matters more than permissive generation. A character with no single,
unambiguous canon reference (see
``CharacterVersionService.get_canon_reference``) is never silently
filled in from an older/earliest reference — it is reported back as
*unresolved*, naming the character and the reason, so the caller
(:class:`~app.core.services.scene_generation_readiness_service.SceneGenerationReadinessService`)
can turn that into an actionable blocking message. This service itself
never raises for "not ready" — it is a pure, side-effect-free read,
safe to call for a cost-free GUI reference preview as well as for real
generation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.db.enums import CharacterVersionStatus
from app.core.models import Character, CharacterVersion, Scene
from app.core.services.character_version_service import CharacterVersionService


@dataclass(frozen=True)
class SelectedReference:
    """One character's chosen reference asset for one generation request."""

    character: Character
    character_version: CharacterVersion
    reference_asset_id: uuid.UUID
    reference_label: str | None


@dataclass(frozen=True)
class ReferenceSelectionResult:
    """Everything :meth:`ReferenceSelectionService.select_references` found.

    ``unresolved`` — a ``(Character, reason)`` pair for every present
    character this service could *not* deterministically resolve a
    canon reference for. Never empty-but-silently-dropped: a character
    that can't be resolved always shows up here, never simply missing
    from ``selected`` with no explanation.
    """

    selected: list[SelectedReference] = field(default_factory=list)
    unresolved: list[tuple[Character, str]] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.unresolved


class ReferenceSelectionService:
    """Selects exactly one canon reference asset per present character, deterministically."""

    def __init__(self, character_versions: CharacterVersionService | None = None) -> None:
        self._character_versions = character_versions or CharacterVersionService()

    def select_references(self, session: Session, scene: Scene) -> ReferenceSelectionResult:
        selected: list[SelectedReference] = []
        unresolved: list[tuple[Character, str]] = []

        # scene.characters_present carries no defined ordering column
        # (a plain M2M table) — sorting by slug keeps both the selected
        # list and the resulting GenerationJob provenance reproducible
        # across repeated calls for the same scene.
        characters = sorted(scene.characters_present, key=lambda c: c.slug)
        for character in characters:
            if character.active_version_id is None:
                unresolved.append((character, "has no active CharacterVersion"))
                continue
            version = session.get(CharacterVersion, character.active_version_id)
            if version is None or version.status != CharacterVersionStatus.APPROVED_CANON:
                unresolved.append((character, "active version is not approved_canon"))
                continue
            canon = self._character_versions.get_canon_reference(session, version.id)
            if canon is None:
                reason = (
                    "no single canon reference is selected for the active version "
                    "(mark one as canon in the character's reference list)"
                )
                unresolved.append((character, reason))
                continue
            selected.append(
                SelectedReference(
                    character=character,
                    character_version=version,
                    reference_asset_id=canon.asset_id,
                    reference_label=canon.label,
                )
            )
        return ReferenceSelectionResult(selected=selected, unresolved=unresolved)
