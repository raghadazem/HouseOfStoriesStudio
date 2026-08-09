"""Background (QThread) workers — the GUI's only place that touches threading.

Every worker here is a thin bridge: it invokes one ``app.core`` operation
and reports back via Qt signals. Business/state-transition logic never
lives in a worker — see ``app.core.ai.generation_runner`` and
``app.core.ai.generation_job_service`` for where that actually lives.
``app/core`` must never import Qt; workers are the one-way boundary
where a plain-Python callback becomes a Qt signal.
"""

from __future__ import annotations

from app.gui.workers.generation_worker import GenerationWorker, JobSnapshot

__all__ = ["GenerationWorker", "JobSnapshot"]
