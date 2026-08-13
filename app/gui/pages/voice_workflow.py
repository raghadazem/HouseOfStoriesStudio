"""Voice workspace: real per-line generation, review, and final-take selection.

Milestone 9's Voice tab (see ``episode_workspace_page.py``) replaces the
generic import-only asset list that tab used to be with a real
production workspace, mirroring Milestone 8's Images tab exactly:
per-line readiness (naming the exact blocker), a read-only authored/
normalized-text preview, real generation via the same
``GenerationWorker``/``CandidateReviewDialogBase`` infrastructure
(with the new ``AudioCandidateTile`` for playback), and an explicit
"Set as Final Take" action — never automatic.

Voice identity management (creating/approving/activating a
``VoiceProfile`` per character or the Narrator) lives here too, at the
top of the panel — the smallest reasonable home, since it's a
voice-specific concern with no other natural page.

No AI provider is called anywhere in this file except through the
same ``AIOrchestrator``/``run_voice_line_batch`` path every other real
generation flow uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    VoiceLineBatchRequest,
    run_voice_line_batch,
)
from app.core.ai.text_normalization import normalize_arabic_line
from app.core.db.enums import ApprovalDecision, ApprovalStatus
from app.core.models import Asset, DialogueLine
from app.core.models.asset import ROLE_FINAL_LINE_VOICE
from app.core.models.voice_profile import NON_CHARACTER_SPEAKERS
from app.core.services.exceptions import ServiceError
from app.core.services.pronunciation_override_service import PronunciationOverrideService
from app.core.services.voice_generation_readiness_service import (
    SONG_SCENE_MESSAGE,
    VoiceGenerationReadinessService,
)
from app.core.services.voice_profile_service import VoiceProfileService
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    AudioCandidateTile,
    CandidateReviewDialogBase,
    EmptyState,
    FormDialog,
    StatusBadge,
    confirm,
    show_error,
)
from app.gui.workers.generation_worker import GenerationWorker

# --- Voice Profile create/edit ------------------------------------------------


class _VoiceProfileDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        *,
        character_id: uuid.UUID | None,
        speaker_key: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "New Voice Profile", icon="🎙️",
            subtitle="A real ElevenLabs voice identity for this speaker",
            save_label="Create", parent=parent,
        )
        self._ctx = ctx
        self._character_id = character_id
        self._speaker_key = speaker_key

        self.display_name_field = QLineEdit()
        self.display_name_field.setPlaceholderText('e.g. "Melissa — Warm Young Girl"')
        self.add_row("Display name", self.display_name_field)

        self.provider_field = QComboBox()
        providers = ctx.ai_orchestrator.list_available_providers("voice")
        for name in providers:
            self.provider_field.addItem(name, name)
        self.add_row("Provider", self.provider_field)
        if not providers:
            self.show_form_error(
                "No voice provider is configured. Set one up in Settings → Voice."
            )

        self.provider_voice_id_field = QLineEdit()
        self.provider_voice_id_field.setPlaceholderText("The provider's real voice id")
        self.add_row("Provider voice ID", self.provider_voice_id_field)

        self.provider_model_field = QLineEdit()
        self.provider_model_field.setPlaceholderText("Leave blank for the provider's default")
        self.add_row("Model (optional)", self.provider_model_field)

        self.voice_direction_field = QPlainTextEdit()
        self.voice_direction_field.setPlaceholderText(
            "Age impression, speaking style, pace, emotional range…"
        )
        self.voice_direction_field.setFixedHeight(80)
        self.add_row("Voice direction (optional)", self.voice_direction_field)

        self.stability_field = QDoubleSpinBox()
        self.stability_field.setRange(0.0, 1.0)
        self.stability_field.setSingleStep(0.05)
        self.stability_field.setValue(0.5)
        self.add_row("Stability", self.stability_field)

        self.similarity_boost_field = QDoubleSpinBox()
        self.similarity_boost_field.setRange(0.0, 1.0)
        self.similarity_boost_field.setSingleStep(0.05)
        self.similarity_boost_field.setValue(0.75)
        self.add_row("Similarity boost", self.similarity_boost_field)

    def validate(self) -> str | None:
        if not self.display_name_field.text().strip():
            return "A display name is required."
        if self.provider_field.currentData() is None:
            return "No voice provider is configured."
        if not self.provider_voice_id_field.text().strip():
            return "A provider voice ID is required."
        return None

    def create(self, session) -> None:
        VoiceProfileService().create_voice_profile(
            session,
            character_id=self._character_id,
            speaker_key=self._speaker_key,
            display_name=self.display_name_field.text().strip(),
            provider_name=self.provider_field.currentData(),
            provider_voice_id=self.provider_voice_id_field.text().strip(),
            provider_model=self.provider_model_field.text().strip() or None,
            voice_direction=self.voice_direction_field.toPlainText().strip() or None,
            default_parameters={
                "stability": self.stability_field.value(),
                "similarity_boost": self.similarity_boost_field.value(),
            },
        )


# --- Voice Profile manager: list + create + approve + set active -------------


class _VoiceProfileManagerDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        *,
        character_id: uuid.UUID | None,
        speaker_key: str | None,
        speaker_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(f"Voice Profiles — {speaker_label}", icon="🎙️", show_save=False, parent=parent)
        self._ctx = ctx
        self._character_id = character_id
        self._speaker_key = speaker_key
        self.changed = False

        self._list_layout = QVBoxLayout()
        list_container = QWidget()
        list_container.setLayout(self._list_layout)
        self.add_row("Profiles", list_container)

        add_button = QPushButton("+ New Profile")
        add_button.setProperty("class", "primary")
        add_button.clicked.connect(self._on_add)
        self.content_layout.addWidget(add_button)

        self._refresh()

    def _refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        with self._ctx.open_session() as session:
            profiles = VoiceProfileService().list_voice_profiles(
                session, character_id=self._character_id, speaker_key=self._speaker_key
            )
            rows = [
                (
                    p.id,
                    p.display_name,
                    p.provider_name,
                    p.is_active,
                    self._ctx.approval_service.get_current_approval_state(session, "voice_profile", p.id)
                    == ApprovalDecision.APPROVED,
                )
                for p in profiles
            ]

        if not rows:
            self._list_layout.addWidget(QLabel("No voice profiles yet."))
        for profile_id, display_name, provider_name, is_active, is_approved in rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{display_name} ({provider_name})"), stretch=1)
            if is_active:
                row.addWidget(StatusBadge("★ Active", "success"))
            row.addWidget(StatusBadge("Approved" if is_approved else "Not Approved", "success" if is_approved else "neutral"))
            if not is_active:
                activate_btn = QPushButton("Set Active")
                activate_btn.clicked.connect(lambda _c=False, pid=profile_id: self._on_set_active(pid))
                row.addWidget(activate_btn)
            if not is_approved:
                approve_btn = QPushButton("Approve")
                approve_btn.setProperty("class", "primary")
                approve_btn.clicked.connect(lambda _c=False, pid=profile_id: self._on_approve(pid))
                row.addWidget(approve_btn)
            wrap = QWidget()
            wrap.setLayout(row)
            self._list_layout.addWidget(wrap)

    def _on_add(self) -> None:
        dialog = _VoiceProfileDialog(
            self._ctx, character_id=self._character_id, speaker_key=self._speaker_key, parent=self
        )
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        try:
            with self._ctx.session_scope() as session:
                dialog.create(session)
        except ServiceError as err:
            show_error(self, "Create Voice Profile", str(err))
            return
        self.changed = True
        self._refresh()

    def _on_set_active(self, profile_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                VoiceProfileService().set_active_voice_profile(session, profile_id)
        except ServiceError as err:
            show_error(self, "Set Active", str(err))
            return
        self.changed = True
        self._refresh()

    def _on_approve(self, profile_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.approval_service.approve_entity(
                    session, "voice_profile", profile_id, decided_by="founder"
                )
        except ServiceError as err:
            show_error(self, "Approve Voice Profile", str(err))
            return
        self.changed = True
        self._refresh()


# --- Generate dialog: candidate count, authored/normalized preview -----------


class _GenerateVoiceLineDialog(FormDialog):
    def __init__(self, ctx: ApplicationContext, dialogue_line_id: uuid.UUID, parent: QWidget | None = None) -> None:
        super().__init__(
            "Generate Voice Line", icon="🎙️",
            subtitle="Real AI-generated voice-line candidates",
            save_label="Generate", min_width=520, parent=parent,
        )
        self._ctx = ctx
        self._dialogue_line_id = dialogue_line_id

        self.provider_field = QComboBox()
        providers = ctx.ai_orchestrator.list_available_providers("voice")
        for name in providers:
            self.provider_field.addItem(name, name)
        self.add_row("Provider", self.provider_field)
        if not providers:
            self.show_form_error(
                "No voice provider is configured. Set one up in Settings → Voice."
            )

        with ctx.open_session() as session:
            line = session.get(DialogueLine, dialogue_line_id)
            authored_text = line.authored_text if line else ""
            overrides = {o.term: o.replacement for o in PronunciationOverrideService().list_overrides(session)}
            normalized_text = normalize_arabic_line(authored_text, pronunciation_overrides=overrides)

        authored_preview = QPlainTextEdit(authored_text)
        authored_preview.setReadOnly(True)
        authored_preview.setFixedHeight(70)
        self.add_row("Authored text", authored_preview)

        if normalized_text != authored_text:
            normalized_preview = QPlainTextEdit(normalized_text)
            normalized_preview.setReadOnly(True)
            normalized_preview.setFixedHeight(70)
            self.add_row("Normalized text (sent to provider)", normalized_preview)

        self.candidate_count_field = QSpinBox()
        self.candidate_count_field.setRange(MIN_CANDIDATE_COUNT, MAX_CANDIDATE_COUNT)
        self.candidate_count_field.setValue(1)
        self.add_row("Candidates to generate", self.candidate_count_field)

    def validate(self) -> str | None:
        if self.provider_field.currentData() is None:
            return "No voice provider is configured."
        return None

    def build_request(self, episode_id: uuid.UUID) -> VoiceLineBatchRequest:
        return VoiceLineBatchRequest(
            provider_name=self.provider_field.currentData(),
            dialogue_line_id=self._dialogue_line_id,
            episode_id=episode_id,
            candidate_count=self.candidate_count_field.value(),
        )


# --- candidate review: reuses the shared Milestone 7/8 grid/worker -----------


class _VoiceCandidateReviewDialog(CandidateReviewDialogBase):
    """Voice-line candidates: Approve/Reject plus "Set as Final Take" for
    an approved candidate not already the line's final take. Uses
    ``AudioCandidateTile`` (playback + real duration) instead of the
    image-thumbnail default."""

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        dialogue_line_id: uuid.UUID,
        base_request: VoiceLineBatchRequest,
        parent: QWidget | None = None,
    ) -> None:
        self._dialogue_line_id = dialogue_line_id
        super().__init__(
            "Voice Line Candidates", ctx, theme, base_request, runner=run_voice_line_batch, parent=parent
        )

    def _build_tile(self, job, asset, *, tertiary_badge, tertiary_action):
        return AudioCandidateTile(
            self._ctx, job, asset,
            on_approve=self._on_approve, on_reject=self._on_reject,
            on_retry=self._on_retry, on_cancel=self._on_cancel,
            tertiary_badge=tertiary_badge, tertiary_action=tertiary_action,
        )

    def _tertiary_state(self, session, job, asset):
        if asset is None:
            return None, None
        is_final = asset.role == ROLE_FINAL_LINE_VOICE
        badge = "Final Take" if is_final else None
        action = None
        if asset.approval_status == ApprovalStatus.APPROVED and not is_final:
            action = ("Set as Final Take", self._on_set_final_take)
        return badge, action

    def _on_set_final_take(self, asset_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.set_line_final_take(session, self._dialogue_line_id, asset_id)
        except ServiceError as err:
            self._show_error("Set as Final Take", str(err))
            return
        self.changed = True
        self._refresh()

    def _show_error(self, title: str, message: str) -> None:
        show_error(self, title, message)


# --- "Generate all READY lines in this scene" --------------------------------


class _GenerateAllDialog(FormDialog):
    """Sequentially runs one single-candidate batch per READY line, on a
    background GenerationWorker (never blocking the UI thread) — never
    a candidate-review grid of its own; each line's own row still opens
    its normal review flow afterward. No episode-wide equivalent exists
    yet (Milestone 9 Decision 5) — this is scene-scoped only."""

    def __init__(
        self,
        ctx: ApplicationContext,
        episode_id: uuid.UUID,
        line_ids: list[uuid.UUID],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Generate All Ready Lines", icon="🎙️", show_save=False, parent=parent)
        self._ctx = ctx
        self._episode_id = episode_id
        self._line_ids = line_ids
        self._index = 0
        self._succeeded = 0
        self._failed = 0
        self._worker: GenerationWorker | None = None
        self.changed = False

        self._status_label = QLabel(f"0 of {len(line_ids)} lines generated…")
        self.add_row("Status", self._status_label)
        self._run_next()

    def _run_next(self) -> None:
        if self._index >= len(self._line_ids):
            self._status_label.setText(
                f"Done — {self._succeeded} succeeded, {self._failed} failed out of {len(self._line_ids)}."
            )
            return
        line_id = self._line_ids[self._index]
        request = VoiceLineBatchRequest(
            provider_name=self._ctx.ai_orchestrator.list_available_providers("voice")[0],
            dialogue_line_id=line_id,
            episode_id=self._episode_id,
            candidate_count=1,
        )
        self._worker = GenerationWorker(self._ctx, request, runner=run_voice_line_batch, parent=self)
        self._worker.batch_finished.connect(self._on_finished)
        self._worker.batch_failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, snapshots) -> None:
        self._succeeded += 1
        self.changed = True
        self._advance()

    def _on_failed(self, message: str) -> None:
        self._failed += 1
        self._advance()

    def _advance(self) -> None:
        self._index += 1
        self._status_label.setText(f"{self._index} of {len(self._line_ids)} lines processed…")
        self._run_next()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(200)
        super().closeEvent(event)


# --- one dialogue line's row --------------------------------------------------


class _DialogueLineRow(QFrame):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        line: DialogueLine,
        *,
        is_ready: bool,
        blocking_messages: list[str],
        has_final_take: bool,
        job_count: int,
        is_song_scene: bool,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self._ctx = ctx
        self._theme = theme
        self._line = line
        self._on_changed = on_changed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_xs, METRICS.spacing_sm, METRICS.spacing_xs
        )
        layout.setSpacing(METRICS.spacing_sm)

        layout.addWidget(StatusBadge(line.speaker_raw, "info"))
        text_label = QLabel(line.authored_text)
        text_label.setWordWrap(True)
        layout.addWidget(text_label, stretch=1)
        if has_final_take:
            layout.addWidget(StatusBadge("✓ Final Take", "success"))

        if is_song_scene:
            song_badge = StatusBadge("🎵 Song", "neutral")
            song_badge.setToolTip(SONG_SCENE_MESSAGE)
            layout.addWidget(song_badge)
            note = QLabel("Handled by Song/Music production")
            note.setProperty("class", "muted")
            layout.addWidget(note)
        else:
            layout.addWidget(
                StatusBadge("Ready" if is_ready else "Blocked", "success" if is_ready else "warning")
            )
            generate_btn = QPushButton("Generate")
            generate_btn.setProperty("class", "primary")
            generate_btn.setEnabled(is_ready)
            if not is_ready:
                generate_btn.setToolTip("; ".join(blocking_messages))
            generate_btn.clicked.connect(self._on_generate)
            layout.addWidget(generate_btn)

    def _on_generate(self) -> None:
        dialog = _GenerateVoiceLineDialog(self._ctx, self._line.id, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        request = dialog.build_request(self._line.scene.episode_id)
        review_dialog = _VoiceCandidateReviewDialog(self._ctx, self._theme, self._line.id, request, parent=self)
        review_dialog.exec()
        self._on_changed()


# --- one scene's card ---------------------------------------------------------


class _SceneVoiceCard(QFrame):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        scene,
        *,
        line_rows: list[tuple],
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self._ctx = ctx
        self._theme = theme
        self._scene = scene
        self._on_changed = on_changed
        self._ready_line_ids = [
            line.id for line, is_ready, _msgs, _final, _count, _song in line_rows if is_ready
        ]
        self._tts_eligible_count = sum(
            1 for _line, _ready, _msgs, _final, _count, is_song in line_rows if not is_song
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        header = QHBoxLayout()
        title = QLabel(f"Scene {scene.order_index}: {scene.title or '(untitled)'}")
        title.setProperty("class", "entityRowTitle")
        header.addWidget(title, stretch=1)
        ready_count = len(self._ready_line_ids)
        header.addWidget(
            StatusBadge(
                f"{ready_count}/{self._tts_eligible_count} ready", "success" if ready_count else "neutral"
            )
        )
        generate_all_btn = QPushButton("Generate All Ready")
        generate_all_btn.setEnabled(ready_count > 0)
        generate_all_btn.clicked.connect(self._on_generate_all)
        header.addWidget(generate_all_btn)
        layout.addLayout(header)

        if not line_rows:
            layout.addWidget(QLabel("No dialogue in this scene yet."))
        for line, is_ready, blocking_messages, has_final_take, job_count, is_song_scene in line_rows:
            layout.addWidget(
                _DialogueLineRow(
                    ctx, theme, line,
                    is_ready=is_ready, blocking_messages=blocking_messages,
                    has_final_take=has_final_take, job_count=job_count,
                    is_song_scene=is_song_scene,
                    on_changed=on_changed,
                )
            )

    def _on_generate_all(self) -> None:
        count = len(self._ready_line_ids)
        if not confirm(
            self, "Generate All Ready Lines",
            f"This will make {count} real paid voice-generation call(s) for this scene. Continue?",
        ):
            return
        dialog = _GenerateAllDialog(self._ctx, self._scene.episode_id, self._ready_line_ids, parent=self)
        dialog.exec()
        if dialog.changed:
            self._on_changed()


# --- Voice Profiles summary section -------------------------------------------


class _VoiceProfilesSummary(QFrame):
    def __init__(self, ctx: ApplicationContext, on_changed: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self._ctx = ctx
        self._on_changed = on_changed
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        title = QLabel("Voice Profiles")
        title.setProperty("class", "entityRowTitle")
        self._layout.addWidget(title)
        self._rows_layout = QVBoxLayout()
        self._layout.addLayout(self._rows_layout)

    def refresh(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        with self._ctx.open_session() as session:
            characters = self._ctx.character_service.list_characters(session)
            speakers: list[tuple[uuid.UUID | None, str | None, str]] = [
                (c.id, None, c.name_en) for c in characters
            ]
            speakers.extend(
                (None, speaker.speaker_key, speaker.display_label)
                for speaker in NON_CHARACTER_SPEAKERS
            )
            vps = VoiceProfileService()
            rows = []
            for character_id, speaker_key, label in speakers:
                active = vps.get_active_voice_profile(session, character_id=character_id, speaker_key=speaker_key)
                if active is not None:
                    approved = self._ctx.approval_service.get_current_approval_state(
                        session, "voice_profile", active.id
                    ) == ApprovalDecision.APPROVED
                    status = active.display_name + (" (approved)" if approved else " (not approved)")
                    variant = "success" if approved else "warning"
                else:
                    status = "Not configured"
                    variant = "neutral"
                rows.append((character_id, speaker_key, label, status, variant))

        for character_id, speaker_key, label, status, variant in rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(label), stretch=1)
            row.addWidget(StatusBadge(status, variant))
            manage_btn = QPushButton("Manage")
            manage_btn.clicked.connect(
                lambda _c=False, cid=character_id, skey=speaker_key, lbl=label: self._on_manage(cid, skey, lbl)
            )
            row.addWidget(manage_btn)
            wrap = QWidget()
            wrap.setLayout(row)
            self._rows_layout.addWidget(wrap)

    def _on_manage(self, character_id: uuid.UUID | None, speaker_key: str | None, label: str) -> None:
        dialog = _VoiceProfileManagerDialog(
            self._ctx, character_id=character_id, speaker_key=speaker_key, speaker_label=label, parent=self
        )
        dialog.exec()
        if dialog.changed:
            self.refresh()
            self._on_changed()


# --- the panel embedded as the Voice tab --------------------------------------


class VoiceWorkspacePanel(QWidget):
    """The Voice tab's full content: voice-profile summary + one
    :class:`_SceneVoiceCard` per scene."""

    def __init__(self, ctx: ApplicationContext, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._theme = theme
        self._episode_id: uuid.UUID | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.spacing_sm)

        self._profiles_summary = _VoiceProfilesSummary(ctx, self._on_profiles_changed)
        layout.addWidget(self._profiles_summary)

        self._card_layout = QVBoxLayout()
        self._card_layout.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._card_layout)

        self._empty_state = EmptyState(
            "No scenes yet — add scenes with dialogue in the Storyboard tab first.", icon="🎙️"
        )
        layout.addWidget(self._empty_state)
        layout.addStretch(1)

    def refresh(self, episode_id: uuid.UUID) -> None:
        self._episode_id = episode_id
        self._profiles_summary.refresh()
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            with self._ctx.open_session() as session:
                scenes = self._ctx.scene_service.list_episode_scenes(session, episode_id)
                providers = self._ctx.ai_orchestrator.list_available_providers("voice")
                provider_name = providers[0] if providers else None
                readiness_service = VoiceGenerationReadinessService()
                card_data = []
                for scene in scenes:
                    lines = self._ctx.scene_service.sync_dialogue_lines(session, scene.id)
                    line_rows = []
                    for line in lines:
                        is_song_scene = scene.is_song_scene
                        if is_song_scene:
                            # Never subject to ordinary TTS readiness --
                            # no provider/profile checks apply.
                            is_ready = False
                            blocking_messages: list[str] = []
                        elif provider_name is None:
                            is_ready = False
                            blocking_messages = ["No voice provider is configured."]
                        else:
                            report = readiness_service.evaluate(
                                session, line.id, provider_name=provider_name,
                                orchestrator=self._ctx.ai_orchestrator,
                            )
                            is_ready = report.is_ready
                            blocking_messages = report.blocking_messages
                        has_final_take = (
                            session.query(Asset)
                            .filter_by(dialogue_line_id=line.id, role=ROLE_FINAL_LINE_VOICE)
                            .count()
                            > 0
                        )
                        job_count = len(
                            self._ctx.generation_job_service.list_jobs(session, dialogue_line_id=line.id)
                        )
                        line_rows.append(
                            (line, is_ready, blocking_messages, has_final_take, job_count, is_song_scene)
                        )
                    card_data.append((scene, line_rows))
        except OperationalError:
            return

        self._empty_state.setVisible(not card_data)
        for scene, line_rows in card_data:
            card = _SceneVoiceCard(
                self._ctx, self._theme, scene, line_rows=line_rows, on_changed=self._on_card_changed
            )
            self._card_layout.addWidget(card)

    def _on_card_changed(self) -> None:
        if self._episode_id is not None:
            self.refresh(self._episode_id)

    def _on_profiles_changed(self) -> None:
        if self._episode_id is not None:
            self.refresh(self._episode_id)
