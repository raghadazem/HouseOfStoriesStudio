"""GenerationJobService — owns the ``GenerationJob`` lifecycle.

The persistent, queryable source of truth for one generation attempt's
provenance and status. Pure persistence and state-machine rules only —
this service knows nothing about providers, workflows, or
``AIOrchestrator``; see ``app.core.ai.generation_runner`` for the
function that ties this together with actual generation execution.
Kept separate so the lifecycle rules are fully testable without any
provider or network concern, and so a future CLI/headless execution
path can drive the exact same lifecycle the GUI worker does.

Lifecycle
---------

::

    PENDING --------------------------> CANCELLED   (cancelled before any provider call)
       |
       v
    RUNNING ----> SUCCEEDED
       |
       +--------> FAILED
       |
       +--------> CANCEL_REQUESTED ----> CANCELLED  (once the in-flight call resolves)

Honest cancellation semantics
------------------------------

A provider call, once started, cannot generally be interrupted
mid-flight (no server-side cancellation API is assumed to exist) — so
this service never reports a job as terminal (``CANCELLED``) while its
provider call could still be running:

- ``PENDING`` -> ``CANCELLED`` is immediate and direct: no provider
  call was ever made, so nothing dishonest about calling it done.
- ``RUNNING`` -> ``CANCEL_REQUESTED`` records the *request* only — the
  in-flight call keeps running to completion, because nothing in this
  application can stop it.
- ``CANCEL_REQUESTED`` -> ``CANCELLED`` only happens once the caller
  (``generation_runner``) has observed the provider call actually
  return — successfully or not — via
  :meth:`GenerationJobService.finalize_cancelled_after_running`. A
  result that arrives after cancellation was requested is never
  silently promoted to ``SUCCEEDED``; the job stays ``CANCELLED`` and,
  if an asset really was produced, ``result_asset_id`` still records it
  (truthful history — money may have been spent) without ever
  surfacing it to the review/candidate-grid UI, which only queries
  ``SUCCEEDED`` jobs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.db.enums import GenerationJobStatus
from app.core.models import GenerationJob
from app.core.services.exceptions import InvalidTransitionError, NotFoundError


class GenerationJobService:
    """Create, transition, and query ``GenerationJob`` rows."""

    def create_job(
        self,
        session: Session,
        *,
        workflow_name: str,
        provider_name: str,
        provider_model: str | None,
        batch_id: uuid.UUID,
        prompt_text: str,
        negative_prompt_text: str | None = None,
        parameters: dict[str, object] | None = None,
        reference_asset_ids: list[uuid.UUID] | None = None,
        character_id: uuid.UUID | None = None,
        character_version_id: uuid.UUID | None = None,
        episode_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
        short_id: uuid.UUID | None = None,
        dialogue_line_id: uuid.UUID | None = None,
        retry_of_job_id: uuid.UUID | None = None,
    ) -> GenerationJob:
        """Persist one new ``PENDING`` job.

        Called before any provider call is made — real, paid,
        failable generation needs a durable record to exist even if the
        process crashes mid-call, not only once it succeeds.
        """
        job = GenerationJob(
            workflow_name=workflow_name,
            provider_name=provider_name,
            provider_model=provider_model,
            status=GenerationJobStatus.PENDING,
            batch_id=batch_id,
            prompt_text=prompt_text,
            negative_prompt_text=negative_prompt_text,
            parameters=dict(parameters or {}),
            reference_asset_ids=[str(asset_id) for asset_id in (reference_asset_ids or [])],
            character_id=character_id,
            character_version_id=character_version_id,
            episode_id=episode_id,
            scene_id=scene_id,
            short_id=short_id,
            dialogue_line_id=dialogue_line_id,
            retry_of_job_id=retry_of_job_id,
        )
        session.add(job)
        session.flush()
        return job

    @staticmethod
    def new_batch_id() -> uuid.UUID:
        """A fresh identifier to group every job in one logical request."""
        return uuid.uuid4()

    def mark_running(self, session: Session, job_id: uuid.UUID) -> GenerationJob:
        job = self._get(session, job_id)
        if job.status != GenerationJobStatus.PENDING:
            raise InvalidTransitionError(
                f"Only a pending job can start running (current: {job.status.value})."
            )
        job.status = GenerationJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        session.flush()
        return job

    def mark_succeeded(
        self,
        session: Session,
        job_id: uuid.UUID,
        *,
        result_asset_id: uuid.UUID,
        cost_usd: Decimal | None = None,
    ) -> GenerationJob:
        """Complete a running job successfully.

        ``cost_usd`` must only ever be an authoritative, provider-
        reported figure — never an estimate computed here. Leave it
        ``None`` when the provider didn't report one.
        """
        job = self._get(session, job_id)
        if job.status != GenerationJobStatus.RUNNING:
            raise InvalidTransitionError(
                f"Only a running job can succeed (current: {job.status.value})."
            )
        job.status = GenerationJobStatus.SUCCEEDED
        job.completed_at = datetime.now(UTC)
        job.result_asset_id = result_asset_id
        job.cost_usd = cost_usd
        session.flush()
        return job

    def mark_failed(
        self, session: Session, job_id: uuid.UUID, *, error_category: str, error_message: str
    ) -> GenerationJob:
        job = self._get(session, job_id)
        if job.status != GenerationJobStatus.RUNNING:
            raise InvalidTransitionError(
                f"Only a running job can fail (current: {job.status.value})."
            )
        job.status = GenerationJobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.error_category = error_category
        job.error_message = error_message
        session.flush()
        return job

    def request_cancel(self, session: Session, job_id: uuid.UUID) -> GenerationJob:
        """Request cancellation — see module docstring for exact semantics."""
        job = self._get(session, job_id)
        if job.status == GenerationJobStatus.PENDING:
            job.status = GenerationJobStatus.CANCELLED
            job.completed_at = datetime.now(UTC)
            job.error_category = "Cancelled"
            job.error_message = "Cancelled before the provider was ever called."
            session.flush()
            return job
        if job.status == GenerationJobStatus.RUNNING:
            job.status = GenerationJobStatus.CANCEL_REQUESTED
            session.flush()
            return job
        raise InvalidTransitionError(
            f"Cannot cancel a job that is {job.status.value} "
            "(only a pending or running job can be cancelled)."
        )

    def finalize_cancelled_after_running(
        self,
        session: Session,
        job_id: uuid.UUID,
        *,
        provider_outcome: str,
        result_asset_id: uuid.UUID | None = None,
    ) -> GenerationJob:
        """Resolve a ``cancel_requested`` job once its provider call returns.

        See the module docstring's "Honest cancellation semantics"
        section — this is the one place a job is allowed to reach
        ``CANCELLED`` from ``CANCEL_REQUESTED``, and it only happens
        after the in-flight call has actually finished.
        """
        job = self._get(session, job_id)
        if job.status != GenerationJobStatus.CANCEL_REQUESTED:
            raise InvalidTransitionError(
                "Only a cancel_requested job can be finalized as cancelled "
                f"(current: {job.status.value})."
            )
        job.status = GenerationJobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        job.error_category = "Cancelled"
        job.error_message = provider_outcome
        job.result_asset_id = result_asset_id
        session.flush()
        return job

    def retry_job(self, session: Session, original_job_id: uuid.UUID) -> GenerationJob:
        """Create a new ``PENDING`` job that repeats a failed/cancelled one.

        Never mutates the original job — copies its immutable
        provenance (prompt/parameters/references/associations) into a
        brand-new row linked back via ``retry_of_job_id``, preserving
        full history rather than an automatic paid retry.
        """
        original = self._get(session, original_job_id)
        return self.create_job(
            session,
            workflow_name=original.workflow_name,
            provider_name=original.provider_name,
            provider_model=original.provider_model,
            batch_id=original.batch_id,
            prompt_text=original.prompt_text,
            negative_prompt_text=original.negative_prompt_text,
            parameters=dict(original.parameters),
            reference_asset_ids=[uuid.UUID(a) for a in original.reference_asset_ids],
            character_id=original.character_id,
            character_version_id=original.character_version_id,
            episode_id=original.episode_id,
            scene_id=original.scene_id,
            short_id=original.short_id,
            dialogue_line_id=original.dialogue_line_id,
            retry_of_job_id=original.id,
        )

    def get_job(self, session: Session, job_id: uuid.UUID) -> GenerationJob:
        return self._get(session, job_id)

    def list_jobs_for_batch(self, session: Session, batch_id: uuid.UUID) -> list[GenerationJob]:
        return (
            session.query(GenerationJob)
            .filter_by(batch_id=batch_id)
            .order_by(GenerationJob.created_at)
            .all()
        )

    def list_jobs(
        self,
        session: Session,
        *,
        character_version_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
        dialogue_line_id: uuid.UUID | None = None,
        status: GenerationJobStatus | None = None,
    ) -> list[GenerationJob]:
        query = session.query(GenerationJob)
        if character_version_id is not None:
            query = query.filter_by(character_version_id=character_version_id)
        if scene_id is not None:
            query = query.filter_by(scene_id=scene_id)
        if dialogue_line_id is not None:
            query = query.filter_by(dialogue_line_id=dialogue_line_id)
        if status is not None:
            query = query.filter_by(status=status)
        return query.order_by(GenerationJob.created_at.desc()).all()

    def _get(self, session: Session, job_id: uuid.UUID) -> GenerationJob:
        job = session.get(GenerationJob, job_id)
        if job is None:
            raise NotFoundError(f"GenerationJob {job_id} not found.")
        return job
