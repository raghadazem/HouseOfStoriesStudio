"""SceneGenerationReadinessService — "can Scene X generate an image right now?"

Deliberately not folded into
:class:`~app.core.services.production_checklist_service.ProductionChecklistService`:
that service evaluates 24 checks across an *entire* episode (script,
shorts, licensing, tasks, export metadata, ...) — wrong-grained and
wasteful to run once per scene-card render (up to 15x per Images tab
load). Also not a method on :class:`~app.core.services.scene_service.SceneService`:
answering this question requires reaching into
:class:`~app.core.services.reference_selection_service.ReferenceSelectionService`,
:class:`~app.core.ai.generation_job_service.GenerationJobService`, and
:class:`~app.core.ai.orchestrator.AIOrchestrator` — none of which are
scene-CRUD concerns.

Every check here composes an *existing* service call; nothing is
re-implemented. Returns actionable, per-check reasons — never a bare
boolean — so the GUI can name the exact blocker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.db.enums import GenerationJobStatus
from app.core.models import Scene
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.reference_selection_service import ReferenceSelectionService

_JOB_IN_FLIGHT_STATUSES = (
    GenerationJobStatus.PENDING,
    GenerationJobStatus.RUNNING,
    GenerationJobStatus.CANCEL_REQUESTED,
)


@dataclass
class SceneReadinessCheck:
    """One named pass/fail entry in a :class:`SceneReadinessReport`."""

    name: str
    passed: bool
    message: str


@dataclass
class SceneReadinessReport:
    scene_id: uuid.UUID
    checks: list[SceneReadinessCheck] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blocking_messages(self) -> list[str]:
        return [check.message for check in self.checks if not check.passed]


class SceneGenerationReadinessService:
    """Evaluates every Milestone 8 pre-generation rule for one scene."""

    def __init__(
        self,
        generation_jobs: GenerationJobService | None = None,
        references: ReferenceSelectionService | None = None,
    ) -> None:
        self._generation_jobs = generation_jobs or GenerationJobService()
        self._references = references or ReferenceSelectionService()

    def evaluate(
        self,
        session: Session,
        scene_id: uuid.UUID,
        *,
        provider_name: str,
        orchestrator: AIOrchestrator,
    ) -> SceneReadinessReport:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise NotFoundError(f"Scene {scene_id} not found.")

        report = SceneReadinessReport(scene_id=scene_id)

        has_prompt = bool(scene.prompt_text and scene.prompt_text.strip())
        report.checks.append(
            SceneReadinessCheck(
                "prompt_composed",
                has_prompt,
                "Scene prompt is composed."
                if has_prompt
                else "Scene has no composed prompt yet — use Compose Prompt in Storyboard first.",
            )
        )

        selection = self._references.select_references(session, scene)
        for character, reason in selection.unresolved:
            report.checks.append(
                SceneReadinessCheck(
                    f"character_ready:{character.slug}",
                    False,
                    f"{character.name_en}: {reason}.",
                )
            )
        if selection.is_complete:
            report.checks.append(
                SceneReadinessCheck(
                    "characters_ready",
                    True,
                    "Every present character has an approved, canon-referenced version."
                    if scene.characters_present
                    else "No characters are present in this scene.",
                )
            )

        try:
            provider = orchestrator.get_provider(provider_name)
        except ValidationError:
            provider = None
        provider_configured = provider is not None and provider.is_configured()
        report.checks.append(
            SceneReadinessCheck(
                "provider_configured",
                provider_configured,
                f"Provider {provider_name!r} is configured."
                if provider_configured
                else f"Provider {provider_name!r} is not configured.",
            )
        )

        if provider is not None and selection.is_complete:
            max_refs = provider.capabilities.max_character_references
            if max_refs is not None and len(selection.selected) > max_refs:
                report.checks.append(
                    SceneReadinessCheck(
                        "reference_capacity",
                        False,
                        f"{len(selection.selected)} character references are needed but "
                        f"{provider_name!r} supports at most {max_refs} per request — "
                        "reduce the characters present in this scene.",
                    )
                )
            else:
                report.checks.append(
                    SceneReadinessCheck(
                        "reference_capacity", True, "Within the provider's reference capacity."
                    )
                )

        existing_jobs = self._generation_jobs.list_jobs(session, scene_id=scene_id)
        in_flight = [job for job in existing_jobs if job.status in _JOB_IN_FLIGHT_STATUSES]
        report.checks.append(
            SceneReadinessCheck(
                "no_job_in_flight",
                not in_flight,
                "No generation already in progress for this scene."
                if not in_flight
                else "A generation batch is already pending/running for this scene.",
            )
        )

        return report
