"""generation_runner — runs one candidate batch, owning the full job lifecycle.

The one function a caller (the GUI worker thread, and — per the
founder's requirement that headless execution use the identical
lifecycle — any future CLI command) invokes to actually generate
character-reference candidates. Qt is never imported here; nothing in
this module knows a GUI exists.

Like ``AssetImportService.import_asset`` (the one other documented
exception to the "services only flush, the caller commits" rule — see
``app.core.services.unit_of_work``), this function commits after each
durable state transition instead of deferring to one outer
``session_scope``. This is deliberate, not an oversight: a
``GenerationJob`` exists specifically so a crash or a cross-thread
cancellation mid-batch still leaves a truthful, queryable row behind —
that guarantee is worthless if the row only becomes visible once the
entire batch (including slow, failable network calls) finishes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.ai.exceptions import ProviderNotConfiguredError
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.line_performance_overrides import get_line_performance_override
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.providers.gemini_provider import DEFAULT_IMAGE_SIZE
from app.core.ai.text_normalization import normalize_arabic_line
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.ai.workflows.scene_image_workflow import SceneImageWorkflow
from app.core.ai.workflows.voice_line_workflow import VoiceLineWorkflow
from app.core.db.enums import GenerationJobStatus
from app.core.models import Asset, DialogueLine, GenerationJob, Scene
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.exceptions import (
    CharacterLockIncompleteError,
    NotFoundError,
    ValidationError,
)
from app.core.services.pronunciation_override_service import PronunciationOverrideService
from app.core.services.reference_selection_service import ReferenceSelectionService
from app.core.services.scene_generation_readiness_service import SceneGenerationReadinessService
from app.core.services.voice_generation_readiness_service import (
    SONG_SCENE_MESSAGE,
    VoiceGenerationReadinessService,
)
from app.core.services.voice_profile_service import VoiceProfileService

MIN_CANDIDATE_COUNT = 1
MAX_CANDIDATE_COUNT = 4


@dataclass(frozen=True)
class CandidateBatchRequest:
    """Everything one "generate N character-reference candidates" request needs."""

    provider_name: str
    prompt_template_id: uuid.UUID
    character_version_id: uuid.UUID
    character_id: uuid.UUID | None = None
    variables: dict[str, object] | None = None
    parameters: dict[str, object] | None = None
    candidate_count: int = 1
    notes: str | None = None
    # Set only for a manual retry of one specific earlier job — see
    # ``run_character_reference_batch``'s docstring. Only meaningful
    # together with candidate_count=1.
    retry_of_job_id: uuid.UUID | None = None


def render_preview(
    session: Session,
    request: CandidateBatchRequest,
    *,
    prompt_engine: PromptEngine | None = None,
):
    """Render the exact prompt a batch would send, without generating anything.

    Backs the GUI's "user sees final prompt preview" step — reuses the
    same :class:`~app.core.ai.prompt_engine.PromptEngine` call the
    batch itself uses, so the preview can never drift from what
    actually gets sent.
    """
    engine = prompt_engine or PromptEngine()
    return engine.build_request(
        session,
        prompt_template_id=request.prompt_template_id,
        variables=request.variables,
        character_version_id=request.character_version_id,
        parameters=request.parameters,
    )


def run_character_reference_batch(
    session: Session,
    request: CandidateBatchRequest,
    *,
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    character_versions: CharacterVersionService | None = None,
    on_job_update: Callable[[GenerationJob], None] | None = None,
) -> list[GenerationJob]:
    """Run one logical "generate N candidates" request end to end.

    1. Fails fast (before creating any job row) if the character
       version isn't prompt-complete or the provider isn't configured —
       no point creating jobs doomed to fail identically.
    2. Renders the prompt once and creates ``candidate_count`` PENDING
       jobs sharing one ``batch_id`` — never assumes a provider can
       return multiple candidates from one call; one provider call per
       job.
    3. Runs each job in turn via ``AIOrchestrator.run_workflow``
       (prompt render + provider call + asset import), transitioning
       each job through its lifecycle.

    Manual retry: pass ``request.retry_of_job_id`` (with
    ``candidate_count=1``) to link the single new job back to the
    original failed/cancelled one via ``retry_of_job_id``, satisfying
    "never mutates history, no automatic paid retries." Per the
    approved Milestone 7 scope (leaving the prompt-template path
    intact rather than redesigning it), a retry re-renders the prompt
    through the normal path using the same ``prompt_template_id``/
    ``variables``/``character_version_id`` the caller supplies —
    within one GUI session these are unchanged from the original
    attempt, so the resulting prompt is for all practical purposes the
    same request, while still tracking the original design's own
    Character Lock data live rather than replaying frozen bytes from a
    second, parallel execution path.

    Cancellation: this function does not poll for cancellation itself.
    A caller cancels a specific job by calling
    ``GenerationJobService.request_cancel`` directly (from any
    thread/session — see module docstring on why every transition here
    is committed immediately, making that safe). Before starting each
    job, this function checks whether it has already been cancelled
    while queued; after each job's blocking provider call returns, it
    checks whether cancellation was requested while that call was in
    flight, and if so finalizes the job as cancelled instead of
    promoting it to succeeded (see
    ``GenerationJobService.finalize_cancelled_after_running``).

    Args:
        on_job_update: Invoked after every persisted state change, so a
            GUI worker can emit a Qt signal without this module ever
            importing Qt.

    Returns:
        Every job created for this batch, in creation order, each with
        its final status.
    """
    if not (MIN_CANDIDATE_COUNT <= request.candidate_count <= MAX_CANDIDATE_COUNT):
        raise ValidationError(
            f"candidate_count must be between {MIN_CANDIDATE_COUNT} and "
            f"{MAX_CANDIDATE_COUNT}, got {request.candidate_count}."
        )

    char_versions = character_versions or CharacterVersionService()
    completeness = char_versions.validate_prompt_completeness(
        session, request.character_version_id
    )
    if not completeness.is_complete:
        raise CharacterLockIncompleteError(
            f"CharacterVersion {request.character_version_id} cannot be used for "
            f"generation: missing {completeness.missing_fields}.",
            missing_fields=completeness.missing_fields,
        )

    provider = orchestrator.get_provider(request.provider_name)
    if not provider.is_configured():
        raise ProviderNotConfiguredError(f"Provider {request.provider_name!r} is not configured.")

    rendered = render_preview(session, request)
    reference_asset_ids = _resolve_reference_asset_ids(session, rendered.reference_asset_paths)
    provider_model = getattr(provider, "model", None)

    # A retry stays grouped in its original batch (so a candidate grid
    # keyed on batch_id keeps showing it alongside its siblings)
    # instead of starting a brand-new batch of one.
    if request.retry_of_job_id is not None:
        batch_id = generation_jobs.get_job(session, request.retry_of_job_id).batch_id
    else:
        batch_id = generation_jobs.new_batch_id()
    jobs: list[GenerationJob] = []
    for index in range(request.candidate_count):
        # A distinguishing per-candidate parameter, not just cosmetic:
        # without it, N candidates from the same character version +
        # template would render byte-identical prompts, and
        # MockProvider (a pure function of the request) would then
        # produce byte-identical output — tripping
        # AssetImportService's duplicate-checksum rejection on every
        # candidate after the first. A real provider naturally varies
        # its output per call and simply ignores this key.
        job_parameters = {**rendered.parameters, "candidate_index": index}
        job = generation_jobs.create_job(
            session,
            workflow_name=CharacterReferenceWorkflow.name,
            provider_name=request.provider_name,
            provider_model=provider_model,
            batch_id=batch_id,
            prompt_text=rendered.prompt_text,
            negative_prompt_text=rendered.negative_prompt_text,
            parameters=job_parameters,
            reference_asset_ids=reference_asset_ids,
            character_id=request.character_id,
            character_version_id=request.character_version_id,
            retry_of_job_id=request.retry_of_job_id,
        )
        session.commit()
        jobs.append(job)
        if on_job_update is not None:
            on_job_update(job)

    for job in jobs:
        _run_one_job(session, job, request, orchestrator, generation_jobs, on_job_update)
    return jobs


def _run_one_job(
    session: Session,
    job: GenerationJob,
    request: CandidateBatchRequest,
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    on_job_update: Callable[[GenerationJob], None] | None,
) -> None:
    current = generation_jobs.get_job(session, job.id)
    if current.status != GenerationJobStatus.PENDING:
        # Already cancelled while queued, before its turn came up.
        return

    job = generation_jobs.mark_running(session, job.id)
    session.commit()
    if on_job_update is not None:
        on_job_update(job)

    try:
        # Pass the job's own already-persisted parameters (not
        # request.parameters) so the immutable snapshot recorded at
        # creation time and what is actually sent to the provider can
        # never diverge — this is also what carries each candidate's
        # distinguishing candidate_index (see the batch loop above).
        result = orchestrator.run_workflow(
            session,
            CharacterReferenceWorkflow.name,
            provider_name=request.provider_name,
            prompt_template_id=request.prompt_template_id,
            variables=request.variables,
            parameters=dict(job.parameters),
            character_id=request.character_id,
            character_version_id=request.character_version_id,
            notes=request.notes,
        )
    except Exception as err:  # noqa: BLE001 - deliberately broad: every failure must be recorded
        current = generation_jobs.get_job(session, job.id)
        if current.status == GenerationJobStatus.CANCEL_REQUESTED:
            job = generation_jobs.finalize_cancelled_after_running(
                session,
                job.id,
                provider_outcome=f"Cancelled by user; provider call also failed: {err}",
            )
        else:
            job = generation_jobs.mark_failed(
                session, job.id, error_category=type(err).__name__, error_message=str(err)
            )
        session.commit()
        if on_job_update is not None:
            on_job_update(job)
        return

    current = generation_jobs.get_job(session, job.id)
    if current.status == GenerationJobStatus.CANCEL_REQUESTED:
        job = generation_jobs.finalize_cancelled_after_running(
            session,
            job.id,
            provider_outcome=(
                "Cancelled by user; provider completed successfully after "
                "cancellation was requested. Result asset was created but not "
                "promoted for review."
            ),
            result_asset_id=result.asset.id,
        )
    else:
        job = generation_jobs.mark_succeeded(session, job.id, result_asset_id=result.asset.id)
        result.asset.generation_job_id = job.id
    session.commit()
    if on_job_update is not None:
        on_job_update(job)


def _resolve_reference_asset_ids(
    session: Session, reference_asset_paths: list[str]
) -> list[uuid.UUID]:
    """Map rendered reference-image managed-relative paths back to Asset ids.

    Provenance stores identifiers, never a second copy of the bytes —
    see ``GenerationJob`` model docstring.
    """
    if not reference_asset_paths:
        return []
    rows = (
        session.query(Asset.id)
        .filter(Asset.relative_path.in_(reference_asset_paths))
        .all()
    )
    return [row[0] for row in rows]


# ============================================================= Scene Images


@dataclass(frozen=True)
class SceneImageBatchRequest:
    """Everything one "generate N scene-image candidates" request needs.

    Deliberately not a variant of ``CandidateBatchRequest``: there is no
    ``prompt_template_id``/``variables`` here at all — a scene's prompt
    is its own ``Scene.prompt_text``/``negative_prompt_text``, already
    authored and possibly hand-edited (see ``SceneImageWorkflow``'s
    direct-prompt path), never a template to render.
    """

    provider_name: str
    scene_id: uuid.UUID
    episode_id: uuid.UUID
    candidate_count: int = 1
    # "1K"/"2K" only (Milestone 8's GUI never offers 512px/4K) — see
    # docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md. Snapshotted
    # onto every job's parameters; never silently changed on retry.
    image_size: str = DEFAULT_IMAGE_SIZE
    notes: str | None = None
    retry_of_job_id: uuid.UUID | None = None


def run_scene_image_batch(
    session: Session,
    request: SceneImageBatchRequest,
    *,
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    readiness: SceneGenerationReadinessService | None = None,
    references: ReferenceSelectionService | None = None,
    on_job_update: Callable[[GenerationJob], None] | None = None,
) -> list[GenerationJob]:
    """Run one logical "generate N scene-image candidates" request end to end.

    Mirrors :func:`run_character_reference_batch`'s shape exactly (fail
    fast before creating any job row, one shared ``batch_id``, one
    provider call per job, honest cancellation, commit after every
    durable transition) — see that function's docstring for the
    lifecycle/cancellation contract, unchanged here.

    Fail-fast checks, in order, before any ``GenerationJob`` row is created:

    1. ``candidate_count`` is in range.
    2. :class:`SceneGenerationReadinessService` reports the scene ready
       (composed prompt, every present character resolved to exactly
       one canon reference, provider configured, reference count within
       the provider's documented character-reference capacity, no
       already-in-flight job for this scene) — raises
       :class:`~app.core.services.exceptions.ValidationError` naming
       every blocking reason if not.

    Every candidate in the batch shares the exact same prompt/negative-
    prompt/reference-asset snapshot — a scene's authored text and its
    characters' canon references don't vary per candidate, unlike a
    template that could render differently. Only ``candidate_index``
    (inside ``parameters``) distinguishes candidates, exactly like
    :func:`run_character_reference_batch`.

    Provenance (Milestone 8 Decision 4): ``reference_asset_ids`` keeps
    storing the flat list of every selected ``Asset.id`` (generic,
    reusable). ``parameters["character_references"]`` additionally
    snapshots the structured ``{character_id, character_version_id,
    reference_asset_id, reference_label}`` mapping used for *this job*,
    immutable from creation even if a canon-reference selection changes
    later — this is why no new database column/table was needed.
    """
    if not (MIN_CANDIDATE_COUNT <= request.candidate_count <= MAX_CANDIDATE_COUNT):
        raise ValidationError(
            f"candidate_count must be between {MIN_CANDIDATE_COUNT} and "
            f"{MAX_CANDIDATE_COUNT}, got {request.candidate_count}."
        )

    scene = session.get(Scene, request.scene_id)
    if scene is None:
        raise NotFoundError(f"Scene {request.scene_id} not found.")

    readiness_service = readiness or SceneGenerationReadinessService()
    report = readiness_service.evaluate(
        session, request.scene_id, provider_name=request.provider_name, orchestrator=orchestrator
    )
    if not report.is_ready:
        raise ValidationError(
            f"Scene {request.scene_id} is not ready to generate: "
            f"{'; '.join(report.blocking_messages)}"
        )

    provider = orchestrator.get_provider(request.provider_name)
    if not provider.is_configured():
        raise ProviderNotConfiguredError(f"Provider {request.provider_name!r} is not configured.")
    provider_model = getattr(provider, "model", None)

    reference_service = references or ReferenceSelectionService()
    selection = reference_service.select_references(session, scene)
    reference_paths: list[str] = []
    character_references: list[dict[str, object]] = []
    for selected in selection.selected:
        asset = session.get(Asset, selected.reference_asset_id)
        reference_paths.append(asset.relative_path)
        character_references.append(
            {
                "character_id": str(selected.character.id),
                "character_version_id": str(selected.character_version.id),
                "reference_asset_id": str(selected.reference_asset_id),
                "reference_label": selected.reference_label,
            }
        )
    reference_asset_ids = [selected.reference_asset_id for selected in selection.selected]

    if request.retry_of_job_id is not None:
        batch_id = generation_jobs.get_job(session, request.retry_of_job_id).batch_id
    else:
        batch_id = generation_jobs.new_batch_id()

    jobs: list[GenerationJob] = []
    for index in range(request.candidate_count):
        job_parameters = {
            "candidate_index": index,
            "image_size": request.image_size,
            "character_references": character_references,
        }
        job = generation_jobs.create_job(
            session,
            workflow_name=SceneImageWorkflow.name,
            provider_name=request.provider_name,
            provider_model=provider_model,
            batch_id=batch_id,
            prompt_text=scene.prompt_text or "",
            negative_prompt_text=scene.negative_prompt_text,
            parameters=job_parameters,
            reference_asset_ids=reference_asset_ids,
            episode_id=request.episode_id,
            scene_id=request.scene_id,
            retry_of_job_id=request.retry_of_job_id,
        )
        session.commit()
        jobs.append(job)
        if on_job_update is not None:
            on_job_update(job)

    for job in jobs:
        _run_one_scene_job(session, job, request, reference_paths, orchestrator, generation_jobs, on_job_update)
    return jobs


def _run_one_scene_job(
    session: Session,
    job: GenerationJob,
    request: SceneImageBatchRequest,
    reference_paths: list[str],
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    on_job_update: Callable[[GenerationJob], None] | None,
) -> None:
    current = generation_jobs.get_job(session, job.id)
    if current.status != GenerationJobStatus.PENDING:
        return  # already cancelled while queued, before its turn came up

    job = generation_jobs.mark_running(session, job.id)
    session.commit()
    if on_job_update is not None:
        on_job_update(job)

    try:
        result = orchestrator.run_workflow(
            session,
            SceneImageWorkflow.name,
            provider_name=request.provider_name,
            rendered_prompt_text=job.prompt_text,
            rendered_negative_prompt_text=job.negative_prompt_text,
            rendered_reference_asset_paths=reference_paths,
            parameters=dict(job.parameters),
            episode_id=request.episode_id,
            scene_id=request.scene_id,
            notes=request.notes,
        )
    except Exception as err:  # noqa: BLE001 - deliberately broad: every failure must be recorded
        current = generation_jobs.get_job(session, job.id)
        if current.status == GenerationJobStatus.CANCEL_REQUESTED:
            job = generation_jobs.finalize_cancelled_after_running(
                session,
                job.id,
                provider_outcome=f"Cancelled by user; provider call also failed: {err}",
            )
        else:
            job = generation_jobs.mark_failed(
                session, job.id, error_category=type(err).__name__, error_message=str(err)
            )
        session.commit()
        if on_job_update is not None:
            on_job_update(job)
        return

    current = generation_jobs.get_job(session, job.id)
    if current.status == GenerationJobStatus.CANCEL_REQUESTED:
        job = generation_jobs.finalize_cancelled_after_running(
            session,
            job.id,
            provider_outcome=(
                "Cancelled by user; provider completed successfully after "
                "cancellation was requested. Result asset was created but not "
                "promoted for review."
            ),
            result_asset_id=result.asset.id,
        )
    else:
        job = generation_jobs.mark_succeeded(session, job.id, result_asset_id=result.asset.id)
        result.asset.generation_job_id = job.id
    session.commit()
    if on_job_update is not None:
        on_job_update(job)


# ============================================================= Voice Lines


@dataclass(frozen=True)
class VoiceLineBatchRequest:
    """Everything one "generate N candidates for one dialogue line" request needs.

    Deliberately per-line, not per-scene: unlike scene-image candidates
    (which share one prompt), each dialogue line has its own speaker,
    voice profile, and text -- a scene-level "generate all READY lines"
    action (Milestone 9 Decision 5) calls this once per line, each with
    its own batch_id, rather than forcing multiple speakers into one
    shared batch.
    """

    provider_name: str
    dialogue_line_id: uuid.UUID
    episode_id: uuid.UUID
    candidate_count: int = 1
    notes: str | None = None
    retry_of_job_id: uuid.UUID | None = None


def run_voice_line_batch(
    session: Session,
    request: VoiceLineBatchRequest,
    *,
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    readiness: VoiceGenerationReadinessService | None = None,
    voice_profiles: VoiceProfileService | None = None,
    pronunciation_overrides: PronunciationOverrideService | None = None,
    on_job_update: Callable[[GenerationJob], None] | None = None,
) -> list[GenerationJob]:
    """Run one logical "generate N candidates for one dialogue line" request.

    Mirrors :func:`run_scene_image_batch`'s shape exactly (fail fast
    before creating any job row, one shared batch_id, one provider call
    per job, honest cancellation, commit after every durable
    transition) -- see that function's docstring for the lifecycle/
    cancellation contract, unchanged here.

    Fail-fast checks, in order, before any GenerationJob row is created:

    1. candidate_count is in range.
    2. The line's Scene is not a song scene (Scene.is_song_scene) --
       enforced here even though the GUI already hides/disables the
       Generate action for these lines, so a direct call can never
       create a GenerationJob for sung content.
    3. VoiceGenerationReadinessService reports the line ready (speaker
       resolved, an approved active voice profile exists, the provider
       is configured, no already-in-flight job for this exact line) --
       raises ValidationError naming every blocking reason if not.

    Text normalization (Milestone 9 Decisions 4/9, extended for
    reviewed vocalization): the line's authored_text is never
    modified. The exact text sent to the provider is computed once,
    here: starting from DialogueLine.reviewed_tts_text if a human has
    reviewed a fully/appropriately vocalized rendering for this exact
    row, otherwise authored_text itself; either way passed through
    app.core.ai.text_normalization.normalize_arabic_line using the
    currently-configured global PronunciationOverride rows; then a
    registered LinePerformanceOverride (if any) takes final precedence
    over all of the above. Snapshotted immutably onto every job's
    parameters["normalized_text_sent"] alongside the untouched
    authored_text -- both stay inspectable later, never conflated.

    Every candidate in the batch shares the exact same normalized text/
    voice-profile snapshot -- only candidate_index (inside parameters)
    distinguishes candidates, exactly like run_scene_image_batch.
    """
    if not (MIN_CANDIDATE_COUNT <= request.candidate_count <= MAX_CANDIDATE_COUNT):
        raise ValidationError(
            f"candidate_count must be between {MIN_CANDIDATE_COUNT} and "
            f"{MAX_CANDIDATE_COUNT}, got {request.candidate_count}."
        )

    line = session.get(DialogueLine, request.dialogue_line_id)
    if line is None:
        raise NotFoundError(f"DialogueLine {request.dialogue_line_id} not found.")
    if line.scene.is_song_scene:
        # Enforced here too, not just by the GUI hiding/disabling the
        # Generate action -- core must refuse even a direct call.
        raise ValidationError(SONG_SCENE_MESSAGE)

    readiness_service = readiness or VoiceGenerationReadinessService()
    report = readiness_service.evaluate(
        session, request.dialogue_line_id, provider_name=request.provider_name, orchestrator=orchestrator
    )
    if not report.is_ready:
        raise ValidationError(
            f"DialogueLine {request.dialogue_line_id} is not ready to generate: "
            f"{'; '.join(report.blocking_messages)}"
        )

    provider = orchestrator.get_provider(request.provider_name)
    if not provider.is_configured():
        raise ProviderNotConfiguredError(f"Provider {request.provider_name!r} is not configured.")
    provider_model = getattr(provider, "model", None)

    profiles = voice_profiles or VoiceProfileService()
    profile = profiles.get_active_voice_profile(
        session, character_id=line.character_id, speaker_key=line.speaker_key
    )
    overrides_service = pronunciation_overrides or PronunciationOverrideService()
    override_map = {o.term: o.replacement for o in overrides_service.list_overrides(session)}
    # The base text before pronunciation-override substitution: a
    # human-reviewed, fully/appropriately vocalized rendering if one
    # has been recorded for this exact DialogueLine row (see its
    # reviewed_tts_text column docstring), otherwise authored_text
    # itself -- either way still passed through the same override
    # table, and authored_text is never read for writing.
    base_text = line.reviewed_tts_text if line.reviewed_tts_text is not None else line.authored_text
    normalized_text = normalize_arabic_line(base_text, pronunciation_overrides=override_map)
    applied_terms = sorted(term for term in override_map if term in base_text)

    # A founder-approved, line-specific performance exception (e.g. the
    # Tortor Scene 7 laugh cue) -- see line_performance_overrides'
    # module docstring for why this lives here rather than as a
    # PronunciationOverride or a provider-level special case.
    # authored_text/normalize_arabic_line's own output above are both
    # left untouched by this; only what actually gets sent downstream
    # changes.
    performance_override = get_line_performance_override(request.dialogue_line_id)
    if performance_override is not None:
        normalized_text = performance_override.provider_bound_text
        # The dedicated GenerationJob.provider_model column (not just
        # parameters["model_id"]) must also reflect what was actually
        # sent -- otherwise this job's own provenance column would
        # misleadingly read "eleven_multilingual_v2" for a line that
        # was really generated with eleven_v3.
        provider_model = performance_override.model_id

    voice_parameters: dict[str, object] = {"voice_id": profile.provider_voice_id}
    voice_parameters.update(profile.default_parameters)
    # The exact output_format that will actually be requested (a
    # VoiceProfile-level override, if ever set, wins; otherwise the
    # provider's own configured default) -- this is the single value
    # both sent to the provider and snapshotted for provenance below,
    # so the two can never disagree.
    voice_parameters.setdefault("output_format", getattr(provider, "output_format", None))
    if performance_override is not None:
        voice_parameters["model_id"] = performance_override.model_id
        voice_parameters["performance_override_reason"] = performance_override.reason

    if request.retry_of_job_id is not None:
        batch_id = generation_jobs.get_job(session, request.retry_of_job_id).batch_id
    else:
        batch_id = generation_jobs.new_batch_id()

    jobs: list[GenerationJob] = []
    for index in range(request.candidate_count):
        job_parameters = {
            **voice_parameters,
            "candidate_index": index,
            "voice_profile_id": str(profile.id),
            "speaker_raw": line.speaker_raw,
            "authored_text": line.authored_text,
            "normalized_text_sent": normalized_text,
            "pronunciation_overrides_applied": applied_terms,
        }
        job = generation_jobs.create_job(
            session,
            workflow_name=VoiceLineWorkflow.name,
            provider_name=request.provider_name,
            provider_model=provider_model,
            batch_id=batch_id,
            prompt_text=normalized_text,
            parameters=job_parameters,
            character_id=line.character_id,
            episode_id=request.episode_id,
            scene_id=line.scene_id,
            dialogue_line_id=request.dialogue_line_id,
            retry_of_job_id=request.retry_of_job_id,
        )
        session.commit()
        jobs.append(job)
        if on_job_update is not None:
            on_job_update(job)

    for job in jobs:
        _run_one_voice_job(session, job, request, orchestrator, generation_jobs, on_job_update)
    return jobs


def _run_one_voice_job(
    session: Session,
    job: GenerationJob,
    request: VoiceLineBatchRequest,
    orchestrator: AIOrchestrator,
    generation_jobs: GenerationJobService,
    on_job_update: Callable[[GenerationJob], None] | None,
) -> None:
    current = generation_jobs.get_job(session, job.id)
    if current.status != GenerationJobStatus.PENDING:
        return  # already cancelled while queued, before its turn came up

    job = generation_jobs.mark_running(session, job.id)
    session.commit()
    if on_job_update is not None:
        on_job_update(job)

    try:
        result = orchestrator.run_workflow(
            session,
            VoiceLineWorkflow.name,
            provider_name=request.provider_name,
            rendered_prompt_text=job.prompt_text,
            parameters=dict(job.parameters),
            episode_id=request.episode_id,
            dialogue_line_id=request.dialogue_line_id,
            notes=request.notes,
        )
    except Exception as err:  # noqa: BLE001 - deliberately broad: every failure must be recorded
        current = generation_jobs.get_job(session, job.id)
        if current.status == GenerationJobStatus.CANCEL_REQUESTED:
            job = generation_jobs.finalize_cancelled_after_running(
                session,
                job.id,
                provider_outcome=f"Cancelled by user; provider call also failed: {err}",
            )
        else:
            job = generation_jobs.mark_failed(
                session, job.id, error_category=type(err).__name__, error_message=str(err)
            )
        session.commit()
        if on_job_update is not None:
            on_job_update(job)
        return

    current = generation_jobs.get_job(session, job.id)
    if current.status == GenerationJobStatus.CANCEL_REQUESTED:
        job = generation_jobs.finalize_cancelled_after_running(
            session,
            job.id,
            provider_outcome=(
                "Cancelled by user; provider completed successfully after "
                "cancellation was requested. Result asset was created but not "
                "promoted for review."
            ),
            result_asset_id=result.asset.id,
        )
    else:
        job = generation_jobs.mark_succeeded(session, job.id, result_asset_id=result.asset.id)
        result.asset.generation_job_id = job.id
    session.commit()
    if on_job_update is not None:
        on_job_update(job)
