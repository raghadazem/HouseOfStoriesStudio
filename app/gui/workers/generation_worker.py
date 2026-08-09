"""GenerationWorker — runs a character-reference generation batch off the GUI thread.

The lifecycle itself (PENDING/RUNNING/SUCCEEDED/FAILED/CANCEL_REQUESTED/
CANCELLED) is owned entirely by
:mod:`app.core.ai.generation_job_service` and
:mod:`app.core.ai.generation_runner` — this worker's only job is to run
that core operation on a background ``QThread`` (so the GUI never
freezes during a real, possibly slow, network call) and translate its
plain-Python progress callback into Qt signals. It never makes a
business decision itself.

Opens and closes its own database session inside :meth:`run` — a
``Session`` is never shared across threads (see
``app.gui.context.ApplicationContext.open_session``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from app.core.ai.generation_runner import CandidateBatchRequest, run_character_reference_batch
from app.core.db.enums import GenerationJobStatus
from app.core.models import GenerationJob
from app.core.services.exceptions import ServiceError
from app.gui.context import ApplicationContext


@dataclass(frozen=True)
class JobSnapshot:
    """A plain, thread-safe snapshot of one ``GenerationJob``'s state.

    Deliberately never the ORM object itself: that instance belongs to
    the worker thread's own session, which is closed by the time the
    main thread's slot runs — reading its attributes then would be
    reading a detached/closed-session object.
    """

    id: uuid.UUID
    batch_id: uuid.UUID
    status: GenerationJobStatus
    provider_name: str
    provider_model: str | None
    result_asset_id: uuid.UUID | None
    error_category: str | None
    error_message: str | None
    retry_of_job_id: uuid.UUID | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_job(cls, job: GenerationJob) -> JobSnapshot:
        return cls(
            id=job.id,
            batch_id=job.batch_id,
            status=job.status,
            provider_name=job.provider_name,
            provider_model=job.provider_model,
            result_asset_id=job.result_asset_id,
            error_category=job.error_category,
            error_message=job.error_message,
            retry_of_job_id=job.retry_of_job_id,
            requested_at=job.requested_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


class GenerationWorker(QThread):
    """Runs one candidate batch (or one manual retry, via ``candidate_count=1``
    and ``retry_of_job_id`` on the request) on a background thread.

    Signals:
        job_updated: Emitted after every persisted state change for any
            job in the batch — a lightweight "something changed,
            refresh" signal carrying a :class:`JobSnapshot`.
        batch_finished: Emitted once, with every job's final snapshot,
            when the whole batch has finished (successfully or not —
            "finished" means every job reached a terminal state, not
            that every job succeeded).
        batch_failed: Emitted instead of ``batch_finished`` only when
            the batch could not even start (e.g. an incomplete
            Character Lock, or an unconfigured provider) — a safe,
            already-human-readable message, never a raw traceback.
    """

    job_updated = Signal(object)
    batch_finished = Signal(list)
    batch_failed = Signal(str)

    def __init__(
        self, ctx: ApplicationContext, request: CandidateBatchRequest, parent=None
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._request = request

    def run(self) -> None:
        session = self._ctx.open_session()
        try:
            jobs = run_character_reference_batch(
                session,
                self._request,
                orchestrator=self._ctx.ai_orchestrator,
                generation_jobs=self._ctx.generation_job_service,
                on_job_update=lambda job: self.job_updated.emit(JobSnapshot.from_job(job)),
            )
            self.batch_finished.emit([JobSnapshot.from_job(job) for job in jobs])
        except ServiceError as err:
            self.batch_failed.emit(str(err))
        except Exception as err:  # noqa: BLE001 - a raw traceback must never reach the GUI thread
            self.batch_failed.emit(f"Unexpected error: {err}")
        finally:
            session.close()
