"""Shared candidate-review grid: thumbnail tiles + worker-driven review dialog.

Built for Milestone 7's character-reference candidates
(``character_version_workflow.py``'s original ``_CandidateTile``/
``_CandidateReviewDialog``); extracted here, behavior-preserving, so
Milestone 8's scene-image candidates reuse the exact same grid,
worker-orchestration, and approve/reject flow instead of a second,
parallel implementation. See
``docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md`` for the
extraction record and the regression tests that prove Milestone 7's
own GUI tests kept passing unmodified through this move.

The one thing genuinely specific to each caller — the third action
beyond Approve/Reject/Retry/Cancel (Milestone 7: "Add as Reference";
Milestone 8: "Set as Key Image") — is never hardcoded here. Each
concrete dialog overrides :meth:`CandidateReviewDialogBase._tertiary_state`
to supply its own badge/action for one job's tile.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ApprovalStatus, GenerationJobStatus
from app.core.models import Asset, GenerationJob
from app.core.services.exceptions import ServiceError, ValidationError
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets.dialogs import show_error
from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.form_dialog import FormDialog
from app.gui.widgets.loading import LoadingOverlay
from app.gui.widgets.responsive_grid import ResponsiveGrid
from app.gui.widgets.status_badge import StatusBadge
from app.gui.workers.generation_worker import GenerationWorker, JobSnapshot

_JOB_STATUS_VARIANT = {
    GenerationJobStatus.PENDING: "neutral",
    GenerationJobStatus.RUNNING: "info",
    GenerationJobStatus.SUCCEEDED: "success",
    GenerationJobStatus.FAILED: "danger",
    GenerationJobStatus.CANCEL_REQUESTED: "warning",
    GenerationJobStatus.CANCELLED: "neutral",
}

# A (label, handler) pair for the one caller-specific action beyond
# Approve/Reject/Retry/Cancel, e.g. ("Add as Reference", ...) or
# ("Set as Key Image", ...). handler receives the approved asset's id.
TertiaryAction = tuple[str, Callable[[uuid.UUID], None]]


def format_duration(started_at: datetime | None, completed_at: datetime | None) -> str:
    if started_at is None:
        return "Waiting to start…"
    if completed_at is None:
        return "In progress…"
    seconds = (completed_at - started_at).total_seconds()
    return f"{seconds:.1f}s"


def load_thumbnail(ctx: ApplicationContext, asset: Asset) -> QPixmap | None:
    try:
        path = ctx.storage_service.resolve_managed_path(asset.relative_path)
    except ValidationError:
        return None
    if not path.is_file():
        return None
    pixmap = QPixmap(str(path))
    return pixmap if not pixmap.isNull() else None


class CandidateTile(QFrame):
    def __init__(
        self,
        ctx: ApplicationContext,
        job: GenerationJob,
        asset: Asset | None,
        *,
        on_approve: Callable[[uuid.UUID], None],
        on_reject: Callable[[uuid.UUID], None],
        on_retry: Callable[[uuid.UUID], None],
        on_cancel: Callable[[uuid.UUID], None],
        tertiary_badge: str | None = None,
        tertiary_action: TertiaryAction | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setMinimumWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_sm, METRICS.spacing_sm, METRICS.spacing_sm
        )
        layout.setSpacing(METRICS.spacing_xs)

        thumb = QLabel("🖼")
        thumb.setProperty("class", "entityCardThumb")
        thumb.setFixedSize(140, 140)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if asset is not None:
            pixmap = load_thumbnail(ctx, asset)
            if pixmap is not None:
                thumb.setPixmap(
                    pixmap.scaled(
                        140,
                        140,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        badge_row = QHBoxLayout()
        badge_row.addWidget(
            StatusBadge(job.status.value.replace("_", " ").title(), _JOB_STATUS_VARIANT[job.status])
        )
        if tertiary_badge:
            badge_row.addWidget(StatusBadge(tertiary_badge, "success"))
        badge_row.addStretch(1)
        layout.addLayout(badge_row)

        meta = QLabel(f"{job.provider_name}" + (f" · {job.provider_model}" if job.provider_model else ""))
        meta.setProperty("class", "entityCardSubtitle")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        duration = format_duration(job.started_at, job.completed_at)
        time_label = QLabel(duration)
        time_label.setProperty("class", "muted")
        layout.addWidget(time_label)

        if job.error_message:
            error_label = QLabel(job.error_message)
            error_label.setProperty("class", "formError")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        actions = QHBoxLayout()
        if job.status in (GenerationJobStatus.PENDING, GenerationJobStatus.RUNNING):
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(lambda: on_cancel(job.id))
            actions.addWidget(cancel_btn)
        elif job.status == GenerationJobStatus.SUCCEEDED and asset is not None:
            if asset.approval_status == ApprovalStatus.DRAFT:
                reject_btn = QPushButton("Reject")
                reject_btn.setProperty("class", "danger")
                reject_btn.clicked.connect(lambda: on_reject(asset.id))
                actions.addWidget(reject_btn)
                approve_btn = QPushButton("Approve")
                approve_btn.setProperty("class", "primary")
                approve_btn.clicked.connect(lambda: on_approve(asset.id))
                actions.addWidget(approve_btn)
            elif asset.approval_status == ApprovalStatus.APPROVED and tertiary_action is not None:
                label, handler = tertiary_action
                action_btn = QPushButton(label)
                action_btn.setProperty("class", "primary")
                action_btn.clicked.connect(lambda: handler(asset.id))
                actions.addWidget(action_btn)
        elif job.status in (GenerationJobStatus.FAILED, GenerationJobStatus.CANCELLED):
            retry_btn = QPushButton("Retry")
            retry_btn.clicked.connect(lambda: on_retry(job.id))
            actions.addWidget(retry_btn)
        layout.addLayout(actions)


class CandidateReviewDialogBase(FormDialog):
    """Owns the ``GenerationWorker`` for the initial batch and every
    manual retry started from here — the dialog stays open for the
    whole review session, refreshing its grid from the database after
    every worker signal and every approve/reject/tertiary-action.

    Subclasses supply: the dialog title, the ``runner`` function
    (``run_character_reference_batch``/``run_scene_image_batch``), and
    :meth:`_tertiary_state` for their one caller-specific action.
    """

    def __init__(
        self,
        title: str,
        ctx: ApplicationContext,
        theme: ThemeManager,
        base_request,
        *,
        runner: Callable[..., list[GenerationJob]],
        min_width: int = 760,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, icon="🖼", show_save=False, min_width=min_width, parent=parent)
        self._ctx = ctx
        self._theme = theme
        self._base_request = base_request
        self._runner = runner
        self._batch_id: uuid.UUID | None = None
        self._worker: GenerationWorker | None = None
        self.changed = False  # test/caller hook: did any review decision happen?

        self._status_label = QLabel("Starting…")
        self.add_row("Status", self._status_label)

        self._grid = ResponsiveGrid(card_min_width=200)
        self.add_row("Candidates", self._grid)

        self._empty_state = EmptyState("No candidates yet.", icon="🖼")
        self.add_row("", self._empty_state)

        self._overlay = LoadingOverlay(self, theme)

        self._start_worker(base_request)

    # --- caller-specific hook ------------------------------------------------

    def _tertiary_state(
        self, session: Session, job: GenerationJob, asset: Asset | None
    ) -> tuple[str | None, TertiaryAction | None]:
        """Return ``(tertiary_badge, tertiary_action)`` for one tile.

        Base implementation supplies neither — a dialog with nothing
        beyond Approve/Reject/Retry/Cancel is a valid subclass too.
        """
        return None, None

    def _show_error(self, title: str, message: str) -> None:
        """Surface an error. Overridable so a subclass module can route
        this through its own ``show_error`` import (e.g. so tests that
        monkeypatch that module's ``show_error`` keep intercepting it,
        exactly as before this dialog's logic lived in that module)."""
        show_error(self, title, message)

    # --- worker orchestration -----------------------------------------------

    def _start_worker(self, request) -> None:
        self._status_label.setText("Generating…")
        self._overlay.start("Generating…")
        self._worker = GenerationWorker(self._ctx, request, runner=self._runner, parent=self)
        self._worker.job_updated.connect(self._on_job_updated)
        self._worker.batch_finished.connect(self._on_batch_finished)
        self._worker.batch_failed.connect(self._on_batch_failed)
        self._worker.start()

    def _on_job_updated(self, snapshot: JobSnapshot) -> None:
        self._batch_id = snapshot.batch_id
        self._refresh()

    def _on_batch_finished(self, snapshots: list[JobSnapshot]) -> None:
        self._overlay.stop()
        if snapshots:
            self._batch_id = snapshots[0].batch_id
        succeeded = sum(1 for s in snapshots if s.status == GenerationJobStatus.SUCCEEDED)
        self._status_label.setText(f"{succeeded} of {len(snapshots)} candidates generated.")
        self._refresh()

    def _on_batch_failed(self, message: str) -> None:
        self._overlay.stop()
        self._status_label.setText("Generation could not start.")
        self._show_error("Generate", message)

    # --- rendering -------------------------------------------------------------

    def _refresh(self) -> None:
        if self._batch_id is None:
            return
        try:
            with self._ctx.open_session() as session:
                jobs = self._ctx.generation_job_service.list_jobs_for_batch(session, self._batch_id)
                tiles = []
                for job in jobs:
                    asset = session.get(Asset, job.result_asset_id) if job.result_asset_id else None
                    badge, action = self._tertiary_state(session, job, asset)
                    tiles.append(
                        CandidateTile(
                            self._ctx,
                            job,
                            asset,
                            on_approve=self._on_approve,
                            on_reject=self._on_reject,
                            on_retry=self._on_retry,
                            on_cancel=self._on_cancel,
                            tertiary_badge=badge,
                            tertiary_action=action,
                        )
                    )
        except OperationalError:
            return
        self._grid.set_cards(tiles)
        self._empty_state.setVisible(not tiles)

    # --- actions -----------------------------------------------------------

    def _on_approve(self, asset_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.approval_service.decide_asset_review(
                    session, asset_id, ApprovalDecision.APPROVED
                )
        except ServiceError as err:
            self._show_error("Approve Candidate", str(err))
            return
        self.changed = True
        self._refresh()

    def _on_reject(self, asset_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.approval_service.decide_asset_review(
                    session, asset_id, ApprovalDecision.REJECTED, notes="Rejected during candidate review."
                )
        except ServiceError as err:
            self._show_error("Reject Candidate", str(err))
            return
        self.changed = True
        self._refresh()

    def _on_retry(self, job_id: uuid.UUID) -> None:
        retry_request = replace(self._base_request, candidate_count=1, retry_of_job_id=job_id)
        self._start_worker(retry_request)

    def _on_cancel(self, job_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.generation_job_service.request_cancel(session, job_id)
        except ServiceError as err:
            self._show_error("Cancel", str(err))
            return
        self._refresh()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(200)
        super().closeEvent(event)
