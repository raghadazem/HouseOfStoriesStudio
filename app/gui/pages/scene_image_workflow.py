"""Scene Images workspace: real per-scene generation, review, and key-image selection.

Milestone 8's Images tab (see ``episode_workspace_page.py``) replaces the
generic import-only asset list that tab used to be with a real
production workspace: per-scene readiness (naming the exact blocker),
a read-only prompt/reference preview, real generation via the same
``GenerationWorker``/``CandidateReviewDialogBase`` infrastructure
Milestone 7 built (see ``app/gui/widgets/candidate_review.py``), and an
explicit "Set as Key Image" action — never automatic. Voice/Music/Video
tabs are untouched; only Images changes in this milestone.

No AI provider is called anywhere in this file except through the same
``AIOrchestrator``/``run_scene_image_batch`` path every other real
generation flow uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.ai.generation_runner import (
    MAX_CANDIDATE_COUNT,
    MIN_CANDIDATE_COUNT,
    SceneImageBatchRequest,
    run_scene_image_batch,
)
from app.core.db.enums import ApprovalStatus
from app.core.models import Asset, Scene
from app.core.models.asset import ROLE_FINAL_SCENE_IMAGE
from app.core.services.exceptions import ServiceError
from app.core.services.reference_selection_service import ReferenceSelectionService
from app.core.services.scene_generation_readiness_service import SceneGenerationReadinessService
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    CandidateReviewDialogBase,
    EmptyState,
    FormDialog,
    StatusBadge,
    show_error,
)
from app.gui.widgets.candidate_review import load_thumbnail

# Milestone 8's approved default/opt-in pair — deliberately only two
# choices (never 512px/4K) to keep candidate exploration cheap by
# default across up to 15 scenes. See
# docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md.
_IMAGE_SIZE_CHOICES = [("Standard (1K)", "1K"), ("High Quality (2K)", "2K")]


# --- Generate dialog: candidate count, quality, prompt/reference preview ----


class _GenerateSceneImageDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        scene_id: uuid.UUID,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Generate Scene Image",
            icon="🖼",
            subtitle="Real AI-generated scene image candidates",
            save_label="Generate",
            min_width=560,
            parent=parent,
        )
        self._ctx = ctx
        self._scene_id = scene_id

        self.provider_field = QComboBox()
        providers = ctx.ai_orchestrator.list_available_providers("image")
        for name in providers:
            self.provider_field.addItem(name, name)
        self.add_row("Provider", self.provider_field)
        if not providers:
            self.show_form_error(
                "No image provider is configured. Set one up in Settings → AI Providers."
            )

        with ctx.open_session() as session:
            scene = session.get(Scene, scene_id)
            prompt_text = scene.prompt_text or ""
            selection = ReferenceSelectionService().select_references(session, scene)
            reference_names = [item.character.name_en for item in selection.selected]

        prompt_preview = QPlainTextEdit(prompt_text)
        prompt_preview.setReadOnly(True)
        prompt_preview.setFixedHeight(110)
        self.add_row("Prompt (from Storyboard)", prompt_preview)

        references_label = QLabel(", ".join(reference_names) if reference_names else "None")
        references_label.setWordWrap(True)
        self.add_row("References to send", references_label)

        self.candidate_count_field = QSpinBox()
        self.candidate_count_field.setRange(MIN_CANDIDATE_COUNT, MAX_CANDIDATE_COUNT)
        self.candidate_count_field.setValue(1)
        self.add_row("Candidates to generate", self.candidate_count_field)

        self.image_size_field = QComboBox()
        for label, value in _IMAGE_SIZE_CHOICES:
            self.image_size_field.addItem(label, value)
        self.add_row("Quality", self.image_size_field)

    def validate(self) -> str | None:
        if self.provider_field.currentData() is None:
            return "No image provider is configured."
        return None

    def build_request(self, episode_id: uuid.UUID) -> SceneImageBatchRequest:
        return SceneImageBatchRequest(
            provider_name=self.provider_field.currentData(),
            scene_id=self._scene_id,
            episode_id=episode_id,
            candidate_count=self.candidate_count_field.value(),
            image_size=self.image_size_field.currentData(),
        )


# --- candidate review: reuses the shared Milestone 7 grid/worker ------------


class _SceneCandidateReviewDialog(CandidateReviewDialogBase):
    """Scene-image candidates: Approve/Reject plus "Set as Key Image"
    for an approved candidate not already the scene's key image."""

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        scene_id: uuid.UUID,
        base_request: SceneImageBatchRequest,
        parent: QWidget | None = None,
    ) -> None:
        self._scene_id = scene_id
        super().__init__(
            "Scene Image Candidates",
            ctx,
            theme,
            base_request,
            runner=run_scene_image_batch,
            parent=parent,
        )

    def _tertiary_state(self, session, job, asset):
        if asset is None:
            return None, None
        is_key_image = asset.role == ROLE_FINAL_SCENE_IMAGE
        badge = "Key Image" if is_key_image else None
        action = None
        if asset.approval_status == ApprovalStatus.APPROVED and not is_key_image:
            action = ("Set as Key Image", self._on_set_key_image)
        return badge, action

    def _on_set_key_image(self, asset_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.set_scene_key_image(session, self._scene_id, asset_id)
        except ServiceError as err:
            self._show_error("Set as Key Image", str(err))
            return
        self.changed = True
        self._refresh()

    def _show_error(self, title: str, message: str) -> None:
        show_error(self, title, message)


# --- one scene's card --------------------------------------------------------


class _SceneImageCard(QFrame):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        scene: Scene,
        *,
        is_ready: bool,
        blocking_messages: list[str],
        character_names: list[str],
        key_image_asset: Asset | None,
        job_count: int,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self._ctx = ctx
        self._theme = theme
        self._scene = scene
        self._on_changed = on_changed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        header = QHBoxLayout()
        title = QLabel(f"Scene {scene.order_index}: {scene.title or '(untitled)'}")
        title.setProperty("class", "entityRowTitle")
        header.addWidget(title, stretch=1)
        if key_image_asset is not None:
            header.addWidget(StatusBadge("✓ Key Image Set", "success"))
        header.addWidget(
            StatusBadge("Ready" if is_ready else "Blocked", "success" if is_ready else "warning")
        )
        layout.addLayout(header)

        chip_row = QHBoxLayout()
        if character_names:
            for name in character_names:
                chip_row.addWidget(StatusBadge(name, "info"))
        else:
            chip_row.addWidget(StatusBadge("No characters", "neutral"))
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        if key_image_asset is not None:
            thumb = QLabel("🖼")
            thumb.setProperty("class", "entityCardThumb")
            thumb.setFixedSize(80, 80)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = load_thumbnail(ctx, key_image_asset)
            if pixmap is not None:
                thumb.setPixmap(
                    pixmap.scaled(
                        80,
                        80,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            layout.addWidget(thumb)

        if not is_ready:
            reason = QLabel(" · ".join(blocking_messages))
            reason.setWordWrap(True)
            reason.setProperty("class", "formError")
            layout.addWidget(reason)

        history_label = QLabel(
            f"{job_count} generation attempt(s) so far." if job_count else "No generations yet."
        )
        history_label.setProperty("class", "muted")
        layout.addWidget(history_label)

        actions = QHBoxLayout()
        generate_btn = QPushButton("Generate")
        generate_btn.setProperty("class", "primary")
        generate_btn.setEnabled(is_ready)
        if not is_ready:
            generate_btn.setToolTip("; ".join(blocking_messages))
        generate_btn.clicked.connect(self._on_generate)
        actions.addWidget(generate_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _on_generate(self) -> None:
        dialog = _GenerateSceneImageDialog(self._ctx, self._scene.id, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        request = dialog.build_request(self._scene.episode_id)
        review_dialog = _SceneCandidateReviewDialog(
            self._ctx, self._theme, self._scene.id, request, parent=self
        )
        review_dialog.exec()
        self._on_changed()


# --- the panel embedded as the Images tab ------------------------------------


class SceneImagesPanel(QWidget):
    """The Images tab's full content: one :class:`_SceneImageCard` per scene."""

    def __init__(self, ctx: ApplicationContext, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._theme = theme
        self._episode_id: uuid.UUID | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.spacing_sm)

        self._card_layout = QVBoxLayout()
        self._card_layout.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._card_layout)

        self._empty_state = EmptyState(
            "No scenes yet — add scenes in the Storyboard tab first.", icon="🖼"
        )
        layout.addWidget(self._empty_state)
        layout.addStretch(1)

    def refresh(self, episode_id: uuid.UUID) -> None:
        self._episode_id = episode_id
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            with self._ctx.open_session() as session:
                scenes = self._ctx.scene_service.list_episode_scenes(session, episode_id)
                providers = self._ctx.ai_orchestrator.list_available_providers("image")
                provider_name = providers[0] if providers else None
                readiness_service = SceneGenerationReadinessService()
                card_data = []
                for scene in scenes:
                    character_names = [c.name_en for c in scene.characters_present]
                    if provider_name is None:
                        is_ready = False
                        blocking_messages = ["No image provider is configured."]
                    else:
                        report = readiness_service.evaluate(
                            session,
                            scene.id,
                            provider_name=provider_name,
                            orchestrator=self._ctx.ai_orchestrator,
                        )
                        is_ready = report.is_ready
                        blocking_messages = report.blocking_messages
                    key_image_asset = (
                        session.query(Asset)
                        .filter_by(scene_id=scene.id, role=ROLE_FINAL_SCENE_IMAGE)
                        .one_or_none()
                    )
                    job_count = len(
                        self._ctx.generation_job_service.list_jobs(session, scene_id=scene.id)
                    )
                    card_data.append(
                        (scene, is_ready, blocking_messages, character_names, key_image_asset, job_count)
                    )
        except OperationalError:
            return

        self._empty_state.setVisible(not card_data)
        for scene, is_ready, blocking_messages, character_names, key_image_asset, job_count in card_data:
            card = _SceneImageCard(
                self._ctx,
                self._theme,
                scene,
                is_ready=is_ready,
                blocking_messages=blocking_messages,
                character_names=character_names,
                key_image_asset=key_image_asset,
                job_count=job_count,
                on_changed=self._on_card_changed,
            )
            self._card_layout.addWidget(card)

    def _on_card_changed(self) -> None:
        if self._episode_id is not None:
            self.refresh(self._episode_id)
