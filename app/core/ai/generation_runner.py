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
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.db.enums import GenerationJobStatus
from app.core.models import Asset, GenerationJob
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.exceptions import CharacterLockIncompleteError, ValidationError

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
