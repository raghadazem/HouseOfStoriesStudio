"""VoiceProductionCandidateService — "does this DialogueLine already have
a valid, current, reusable production candidate?"

Deliberately a separate concept from
:class:`~app.core.services.voice_generation_readiness_service.VoiceGenerationReadinessService`
(Milestone 9 pre-bulk-production checkpoint, 2026-08-15): readiness
answers "is it technically possible to generate this line right now?"
(speaker resolved, active+approved profile, provider configured, no
job in flight) — a line can be fully READY while *also* already having
a perfectly good candidate, and generating it again would just waste a
paid call. This service answers the orthogonal question, so
"Generate Missing" can compose both (`is_ready AND NOT
has_current_candidate`) instead of overloading readiness with a second
meaning.

A candidate only counts as current if it was produced under the exact
configuration production would use *right now* — not merely "a
SUCCEEDED job exists". A prior successful job generated under a
superseded VoiceProfile (e.g. before the Melissa/Bilsan casting swap),
a stale ``normalized_text_sent`` (e.g. before the بيلسان override
existed), a since-changed ``output_format``, or a rejected
performance take (e.g. the pre-eleven_v3 هاها candidate) must never be
mistaken for current — see the module docstring on
``app.core.ai.line_performance_overrides`` for how the one existing
line-specific exception (Tortor's Scene 7 laugh cue) is folded into
"what production would send right now" so it participates in this
matching correctly, with no special-casing needed here.

Approval/role status is deliberately never part of the match: a DRAFT,
an APPROVED, or a ``final_line_voice`` candidate are all equally
"already generated" from a *duplicate-paid-call* point of view — only
:class:`~app.core.services.scene_service.SceneService.set_line_final_take`
governs which candidate becomes the line's actual final take, a
completely separate human decision this service has no opinion on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.line_performance_overrides import get_line_performance_override
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.text_normalization import normalize_arabic_line
from app.core.db.enums import GenerationJobStatus
from app.core.models import Asset, DialogueLine
from app.core.services.exceptions import NotFoundError
from app.core.services.pronunciation_override_service import PronunciationOverrideService
from app.core.services.voice_profile_service import VoiceProfileService


@dataclass(frozen=True)
class LineCandidateReport:
    """Whether ``dialogue_line_id`` already has a current, reusable
    production candidate, and what production would send if it didn't."""

    dialogue_line_id: uuid.UUID
    has_current_candidate: bool
    current_candidate_asset_id: uuid.UUID | None
    expected_voice_id: str | None
    expected_model_id: str | None
    expected_output_format: str | None
    expected_normalized_text_sent: str | None


class VoiceProductionCandidateService:
    """Matches existing ``GenerationJob``/``Asset`` history against the
    CURRENT effective production configuration for one line."""

    def __init__(
        self,
        generation_jobs: GenerationJobService | None = None,
        voice_profiles: VoiceProfileService | None = None,
        pronunciation_overrides: PronunciationOverrideService | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._generation_jobs = generation_jobs or GenerationJobService()
        self._voice_profiles = voice_profiles or VoiceProfileService()
        self._pronunciation_overrides = pronunciation_overrides or PronunciationOverrideService()
        self._config = config or get_config()

    def evaluate_line(
        self,
        session: Session,
        dialogue_line_id: uuid.UUID,
        *,
        provider_name: str,
        orchestrator: AIOrchestrator,
    ) -> LineCandidateReport:
        line = session.get(DialogueLine, dialogue_line_id)
        if line is None:
            raise NotFoundError(f"DialogueLine {dialogue_line_id} not found.")

        expected_voice_id: str | None = None
        if line.character_id is not None or line.speaker_key is not None:
            profile = self._voice_profiles.get_active_voice_profile(
                session, character_id=line.character_id, speaker_key=line.speaker_key
            )
            expected_voice_id = profile.provider_voice_id if profile is not None else None

        provider = orchestrator.get_provider(provider_name)
        expected_output_format = getattr(provider, "output_format", None)

        performance_override = get_line_performance_override(dialogue_line_id)
        if performance_override is not None:
            expected_model_id: str | None = performance_override.model_id
            expected_text = performance_override.provider_bound_text
        else:
            expected_model_id = getattr(provider, "model", None)
            override_map = {
                o.term: o.replacement for o in self._pronunciation_overrides.list_overrides(session)
            }
            expected_text = normalize_arabic_line(line.authored_text, pronunciation_overrides=override_map)

        current_asset_id: uuid.UUID | None = None
        if expected_voice_id is not None:
            succeeded_jobs = self._generation_jobs.list_jobs(
                session, dialogue_line_id=dialogue_line_id, status=GenerationJobStatus.SUCCEEDED
            )
            for job in succeeded_jobs:  # newest first, see GenerationJobService.list_jobs
                if job.result_asset_id is None:
                    continue
                asset = session.get(Asset, job.result_asset_id)
                if asset is None:
                    continue
                absolute_path = self._config.production_dir / asset.relative_path
                if not absolute_path.is_file():
                    continue
                params = job.parameters or {}
                matches = (
                    params.get("voice_id") == expected_voice_id
                    and params.get("model_id", job.provider_model) == expected_model_id
                    and params.get("output_format") == expected_output_format
                    and params.get("normalized_text_sent") == expected_text
                )
                if matches:
                    current_asset_id = asset.id
                    break

        return LineCandidateReport(
            dialogue_line_id=dialogue_line_id,
            has_current_candidate=current_asset_id is not None,
            current_candidate_asset_id=current_asset_id,
            expected_voice_id=expected_voice_id,
            expected_model_id=expected_model_id,
            expected_output_format=expected_output_format,
            expected_normalized_text_sent=expected_text,
        )
