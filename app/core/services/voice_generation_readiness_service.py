"""VoiceGenerationReadinessService — "can this DialogueLine generate voice audio right now?"

Mirrors
:class:`~app.core.services.scene_generation_readiness_service.SceneGenerationReadinessService`'s
shape exactly (same reasoning: wrong grain for the episode-wide
``ProductionChecklistService``, wrong owner for ``SceneService``/
``VoiceProfileService`` individually — this composes both plus
``GenerationJobService``/``AIOrchestrator``). Evaluated **per line**,
since lines block independently of each other.

Every check composes an *existing* service call — no rule is
re-implemented. Returns actionable, per-check reasons, never a bare
boolean, so the GUI can name the exact blocker. No silent fallback to
a different character's voice, ever — an unresolved speaker or a
missing/unapproved voice profile always blocks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.db.enums import ApprovalDecision, GenerationJobStatus
from app.core.models import DialogueLine
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.scene_service import SceneService
from app.core.services.voice_profile_service import VoiceProfileService

_JOB_IN_FLIGHT_STATUSES = (
    GenerationJobStatus.PENDING,
    GenerationJobStatus.RUNNING,
    GenerationJobStatus.CANCEL_REQUESTED,
)


@dataclass
class LineReadinessCheck:
    """One named pass/fail entry in a :class:`LineReadinessReport`."""

    name: str
    passed: bool
    message: str


SONG_SCENE_MESSAGE = (
    "This dialogue line belongs to a song scene and is not eligible for ordinary "
    "TTS generation. It is produced through the Song/Music pipeline instead."
)


@dataclass
class LineReadinessReport:
    dialogue_line_id: uuid.UUID
    checks: list[LineReadinessCheck] = field(default_factory=list)
    # Set only for lines whose parent Scene.is_song_scene is True. Such a
    # line is neither READY nor BLOCKED -- it was never subject to the
    # ordinary speaker/profile/provider checks below, so it can never
    # produce a "blocked" reason (e.g. an unresolved speaker inside a song
    # scene must not read as a Voice failure).
    not_applicable_reason: str | None = None

    @property
    def is_song_scene(self) -> bool:
        return self.not_applicable_reason is not None

    @property
    def is_ready(self) -> bool:
        if self.is_song_scene:
            return False
        return all(check.passed for check in self.checks)

    @property
    def blocking_messages(self) -> list[str]:
        if self.is_song_scene:
            return []
        return [check.message for check in self.checks if not check.passed]


class VoiceGenerationReadinessService:
    """Evaluates every Milestone 9 pre-generation rule for one dialogue line."""

    def __init__(
        self,
        generation_jobs: GenerationJobService | None = None,
        voice_profiles: VoiceProfileService | None = None,
        approvals: ApprovalService | None = None,
        scenes: SceneService | None = None,
    ) -> None:
        self._generation_jobs = generation_jobs or GenerationJobService()
        self._voice_profiles = voice_profiles or VoiceProfileService()
        self._approvals = approvals or ApprovalService()
        self._scenes = scenes or SceneService()

    def evaluate(
        self,
        session: Session,
        dialogue_line_id: uuid.UUID,
        *,
        provider_name: str,
        orchestrator: AIOrchestrator,
    ) -> LineReadinessReport:
        line = session.get(DialogueLine, dialogue_line_id)
        if line is None:
            raise NotFoundError(f"DialogueLine {dialogue_line_id} not found.")

        if line.scene.is_song_scene:
            return LineReadinessReport(
                dialogue_line_id=dialogue_line_id, not_applicable_reason=SONG_SCENE_MESSAGE
            )

        report = LineReadinessReport(dialogue_line_id=dialogue_line_id)

        speaker_resolved = line.character_id is not None or line.speaker_key is not None
        report.checks.append(
            LineReadinessCheck(
                "speaker_resolved",
                speaker_resolved,
                "Speaker resolved."
                if speaker_resolved
                else f"{line.speaker_raw!r} does not match any known character or the Narrator.",
            )
        )

        profile = None
        if speaker_resolved:
            profile = self._voice_profiles.get_active_voice_profile(
                session, character_id=line.character_id, speaker_key=line.speaker_key
            )
            has_active_profile = profile is not None
            report.checks.append(
                LineReadinessCheck(
                    "active_voice_profile",
                    has_active_profile,
                    "An active voice profile is set."
                    if has_active_profile
                    else f"No active voice profile exists for {line.speaker_raw!r} yet.",
                )
            )
            if profile is not None:
                state = self._approvals.get_current_approval_state(
                    session, "voice_profile", profile.id
                )
                profile_approved = state == ApprovalDecision.APPROVED
                report.checks.append(
                    LineReadinessCheck(
                        "voice_profile_approved",
                        profile_approved,
                        "The active voice profile is approved."
                        if profile_approved
                        else f"The active voice profile for {line.speaker_raw!r} is not yet approved.",
                    )
                )

        try:
            provider = orchestrator.get_provider(provider_name)
        except ValidationError:
            provider = None
        provider_configured = provider is not None and provider.is_configured()
        report.checks.append(
            LineReadinessCheck(
                "provider_configured",
                provider_configured,
                f"Provider {provider_name!r} is configured."
                if provider_configured
                else f"Provider {provider_name!r} is not configured.",
            )
        )

        existing_jobs = self._generation_jobs.list_jobs(session, dialogue_line_id=dialogue_line_id)
        in_flight = [job for job in existing_jobs if job.status in _JOB_IN_FLIGHT_STATUSES]
        report.checks.append(
            LineReadinessCheck(
                "no_job_in_flight",
                not in_flight,
                "No generation already in progress for this line."
                if not in_flight
                else "A generation is already pending/running for this line.",
            )
        )

        return report

    def evaluate_scene(
        self,
        session: Session,
        scene_id: uuid.UUID,
        *,
        provider_name: str,
        orchestrator: AIOrchestrator,
    ) -> list[LineReadinessReport]:
        """Sync (see ``SceneService.sync_dialogue_lines``) then evaluate every
        current line in the scene, in order — backs both the Voice tab's
        per-line badges and the "N lines are READY" count a scene-level
        batch confirmation needs."""
        lines = self._scenes.sync_dialogue_lines(session, scene_id)
        return [
            self.evaluate(session, line.id, provider_name=provider_name, orchestrator=orchestrator)
            for line in lines
        ]
