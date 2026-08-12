"""EpisodeWorkspacePage — the complete 8-stage production workflow for one Episode.

Opened from ``EpisodesPage`` (row click) or the Dashboard's "Open
Episode" quick action, via ``MainWindow.open_episode_workspace`` — a
full page pushed onto the shared ``QStackedWidget``, not a modal dialog
(no existing dialog hosts anywhere near this much content: 8 tabs, a
full scene editor). Never touches ``app.core`` directly — every read
and write goes through ``ApplicationContext``, exactly like every other
page.

No AI provider is called directly from this file. The Images tab
(Milestone 8) and the Voice tab (Milestone 9) are real production
workspaces — see ``app/gui/pages/scene_image_workflow.py`` and
``app/gui/pages/voice_workflow.py`` for the actual
``AIOrchestrator``/``GenerationWorker`` wiring; this file only embeds
``SceneImagesPanel``/``VoiceWorkspacePanel`` and refreshes them.
Music/Video remain real, working asset lists + import forms, landing
through the exact same ``Asset`` rows and approval flow as always — a
future milestone's real generation for those modalities is expected to
follow the same pattern Images/Voice just did. See
``docs/29_EPISODE_WORKSPACE_STATUS.md``,
``docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md``, and
``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.db.enums import AssetType, PipelineStage
from app.core.models import Asset, Episode
from app.core.services.asset_import_service import ImportRequest
from app.core.services.exceptions import (
    ChecklistError,
    ConflictError,
    InvalidTransitionError,
    PrivacyViolationError,
    ServiceError,
    ValidationError,
)
from app.gui.context import ApplicationContext
from app.gui.pages.scene_image_workflow import SceneImagesPanel
from app.gui.pages.voice_workflow import VoiceWorkspacePanel
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    EntityRow,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    SceneCard,
    StatusBadge,
    show_error,
)

_ASSET_TAB_TYPES = {
    "music": AssetType.MUSIC,
    "video": AssetType.VIDEO,
}
_ASSET_TAB_ICON = {"music": "🎵", "video": "🎬"}
_STAGE_LABEL = {
    "script": "Script", "storyboard": "Storyboard", "images": "Images", "voice": "Voice",
    "music": "Music", "video": "Video", "seo": "SEO", "export": "Export",
}
_STAGE_STATE_VARIANT = {
    "not_started": "neutral", "in_progress": "info", "ready": "success",
    "blocked": "danger", "completed": "success",
}


class _ImportSceneAssetDialog(FormDialog):
    """A lighter version of the Assets page's import dialog: the asset
    type is fixed by which tab you're importing into, so it isn't asked
    for again."""

    def __init__(self, asset_type: AssetType, parent: QWidget | None = None) -> None:
        super().__init__(
            f"Import {asset_type.value.title()}", icon="📥",
            subtitle="Bring a file into managed storage for this episode",
            save_label="Import", parent=parent,
        )
        self._asset_type = asset_type
        self.selected_path: Path | None = None

        file_row = QHBoxLayout()
        self._file_label = QLabel("No file selected")
        self._file_label.setProperty("class", "muted")
        file_row.addWidget(self._file_label, stretch=1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._on_browse)
        file_row.addWidget(browse_button)
        file_wrap = QWidget()
        file_wrap.setLayout(file_row)
        self.add_row("Source file", file_wrap)

        self.role_field = QLineEdit()
        self.role_field.setPlaceholderText('e.g. "final_video" (leave blank for a draft candidate)')
        self.add_row("Role (optional)", self.role_field)

    def _on_browse(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(self, "Select a file to import")
        if path_str:
            self.selected_path = Path(path_str)
            self._file_label.setText(self.selected_path.name)

    def validate(self) -> str | None:
        if self.selected_path is None:
            return "Choose a file to import first."
        return None

    def result_request(self, episode_id: uuid.UUID) -> ImportRequest:
        assert self.selected_path is not None
        return ImportRequest(
            source_path=self.selected_path,
            asset_type=self._asset_type,
            episode_id=episode_id,
            role=self.role_field.text().strip() or None,
        )


class EpisodeWorkspacePage(QWidget):
    """The full production workspace for one episode: Script, Storyboard,
    Images, Voice, Music, Video, SEO, Export."""

    back_requested = Signal()

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        episode_id: uuid.UUID,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("episodeWorkspacePage")
        self._ctx = ctx
        self._theme = theme
        self._episode_id = episode_id
        self._on_feedback = on_feedback
        self._overlay = LoadingOverlay(self, theme)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_md, METRICS.spacing_xl, 0
        )
        back_button = QPushButton("← Episodes")
        back_button.clicked.connect(self.back_requested.emit)
        top_row.addWidget(back_button)
        top_row.addStretch(1)
        outer.addLayout(top_row)

        self._header = PageHeader("Episode Workspace", "Loading…")
        header_wrap = QWidget()
        header_layout = QVBoxLayout(header_wrap)
        header_layout.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_sm, METRICS.spacing_xl, 0
        )
        header_layout.addWidget(self._header)
        outer.addWidget(header_wrap)

        self._tabs = QTabWidget()
        outer.addWidget(self._tabs, stretch=1)

        self._build_script_tab()
        self._build_storyboard_tab()
        self._build_images_tab()
        self._build_voice_tab()
        for key in ("music", "video"):
            self._build_asset_tab(key)
        self._build_seo_tab()
        self._build_export_tab()

        self.refresh()

    def set_episode(self, episode_id: uuid.UUID) -> None:
        """Re-target this page at a different episode (see MainWindow)."""
        self._episode_id = episode_id
        self.refresh()

    # --- top-level refresh ---------------------------------------------------

    def refresh(self) -> None:
        try:
            # session_scope (commit-on-success), not open_session — both
            # get_or_create_script and get_or_create_song below insert a
            # row the first time a tab is opened, and a non-committing
            # session would silently roll that insert back the moment
            # this block exits, leaving _script_id/_song_id pointing at a
            # row that doesn't actually exist yet (the next Save then
            # raises NotFoundError). See docs/30_MILESTONE_6_EPISODE_001_PRODUCTION_STATUS.md.
            with self._ctx.session_scope() as session:
                episode = self._ctx.episode_service.get_episode(session, self._episode_id)
                self._header.set_title(f"#{episode.number}  {episode.title_en}")
                self._header.set_subtitle(episode.title_ar)
                script = self._ctx.script_service.get_or_create_script(session, self._episode_id)
                stage_summary = self._ctx.production_checklist_service.evaluate_stage_summary(
                    session, self._episode_id
                )
        except OperationalError:
            return

        self.setWindowTitle(episode.title_en)
        self._refresh_script_tab(episode, script)
        self._refresh_storyboard_tab()
        self._images_panel.refresh(self._episode_id)
        self._voice_panel.refresh(self._episode_id)
        self._refresh_song_fields()
        for key, asset_type in _ASSET_TAB_TYPES.items():
            self._refresh_asset_tab(key, asset_type)
        self._refresh_seo_tab(episode)
        self._refresh_export_tab(episode, stage_summary)

    def _notify(self, message: str, variant: str = "success") -> None:
        if self._on_feedback:
            self._on_feedback(message, variant)

    # ================================================================= SCRIPT

    def _build_script_tab(self) -> None:
        tab, layout = self._new_tab()
        self._script_title_en = QLineEdit()
        layout.addWidget(QLabel("Title (English)"))
        layout.addWidget(self._script_title_en)
        self._script_title_ar = QLineEdit()
        self._script_lesson = QLineEdit()
        layout.addWidget(QLabel("Lesson"))
        layout.addWidget(self._script_lesson)
        self._script_language = QLineEdit()
        layout.addWidget(QLabel("Language"))
        layout.addWidget(self._script_language)

        self._script_status_badge = StatusBadge("Draft", "neutral")
        layout.addWidget(self._script_status_badge)

        self._script_summary = QTextEdit()
        layout.addWidget(QLabel("Summary"))
        layout.addWidget(self._script_summary)
        self._script_full = QTextEdit()
        self._script_full.setMinimumHeight(160)
        layout.addWidget(QLabel("Full script"))
        layout.addWidget(self._script_full)
        self._script_notes = QTextEdit()
        layout.addWidget(QLabel("Notes"))
        layout.addWidget(self._script_notes)

        button_row = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.setProperty("class", "primary")
        save_button.clicked.connect(self._on_save_script)
        button_row.addWidget(save_button)
        ready_button = QPushButton("Mark Ready")
        ready_button.clicked.connect(self._on_script_ready)
        button_row.addWidget(ready_button)
        approve_button = QPushButton("Approve")
        approve_button.clicked.connect(self._on_script_approve)
        button_row.addWidget(approve_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

        self._tabs.addTab(tab, "📝 Script")

    def _refresh_script_tab(self, episode: Episode, script) -> None:
        self._script_title_en.setText(episode.title_en)
        self._script_lesson.setText(episode.lesson)
        self._script_language.setText(episode.dialogue_language)
        self._script_summary.setPlainText(script.summary or "")
        self._script_full.setPlainText(script.full_script or "")
        self._script_notes.setPlainText(script.notes or "")
        variant = {"draft": "neutral", "ready": "info", "approved": "success"}[script.status.value]
        self._script_status_badge.set_text(script.status.value.title())
        self._script_status_badge.set_variant(variant)
        self._script_id = script.id

    def _on_save_script(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.episode_service.update_episode(
                    session, self._episode_id,
                    lesson=self._script_lesson.text().strip(),
                    dialogue_language=self._script_language.text().strip(),
                )
                self._ctx.script_service.update_script(
                    session, self._script_id,
                    summary=self._script_summary.toPlainText().strip() or None,
                    full_script=self._script_full.toPlainText().strip() or None,
                    notes=self._script_notes.toPlainText().strip() or None,
                )
        except (ValidationError, ServiceError) as err:
            show_error(self, "Save Script", str(err))
            return
        self.refresh()
        self._notify("Script saved.")

    def _on_script_ready(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.script_service.submit_script_ready(session, self._script_id)
        except (InvalidTransitionError, ServiceError) as err:
            show_error(self, "Mark Ready", str(err))
            return
        self.refresh()
        self._notify("Script marked ready.")

    def _on_script_approve(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.script_service.approve_script(session, self._script_id)
        except (InvalidTransitionError, ServiceError) as err:
            show_error(self, "Approve Script", str(err))
            return
        self.refresh()
        self._notify("Script approved.")

    # ============================================================= STORYBOARD

    def _build_storyboard_tab(self) -> None:
        tab, layout = self._new_tab()
        header_row = QHBoxLayout()
        add_button = QPushButton("+ Add Scene")
        add_button.setProperty("class", "primary")
        add_button.clicked.connect(self._on_add_scene)
        header_row.addWidget(add_button)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        self._scene_list_layout = QVBoxLayout()
        self._scene_list_layout.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._scene_list_layout)

        self._scenes_empty_state = EmptyState(
            "No scenes yet — add the first one to start the storyboard.",
            icon="🧩", action_label="+ Add Scene",
        )
        self._scenes_empty_state.action_triggered.connect(self._on_add_scene)
        layout.addWidget(self._scenes_empty_state)
        layout.addStretch(1)

        self._tabs.addTab(tab, "🧩 Storyboard")

    def _refresh_storyboard_tab(self) -> None:
        while self._scene_list_layout.count():
            item = self._scene_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            with self._ctx.open_session() as session:
                scenes = self._ctx.scene_service.list_episode_scenes(session, self._episode_id)
                characters = self._ctx.character_service.list_characters(session)
                approvals = {
                    scene.id: self._ctx.approval_service.get_current_approval_state(
                        session, "scene", scene.id
                    )
                    for scene in scenes
                }
                # Detach the values this widget needs after the session closes.
                scene_data = [
                    (scene, list(scene.characters_present), approvals[scene.id]) for scene in scenes
                ]
                character_list = list(characters)
        except OperationalError:
            return

        self._scenes_empty_state.setVisible(not scene_data)
        for index, (scene, _present, approval_state) in enumerate(scene_data):
            card = SceneCard(
                scene, character_list, approval_state,
                is_first=(index == 0), is_last=(index == len(scene_data) - 1),
            )
            card.move_up_requested.connect(lambda s=scene: self._on_move_scene(s.id, -1))
            card.move_down_requested.connect(lambda s=scene: self._on_move_scene(s.id, 1))
            card.duplicate_requested.connect(lambda s=scene: self._on_duplicate_scene(s.id))
            card.delete_requested.connect(lambda s=scene: self._on_delete_scene(s.id))
            card.save_requested.connect(lambda fields, s=scene: self._on_save_scene(s.id, fields))
            card.characters_changed_requested.connect(
                lambda ids, s=scene: self._on_scene_characters_changed(s.id, ids)
            )
            card.compose_prompt_requested.connect(lambda s=scene, c=card: self._on_compose_prompt(s.id, c))
            card.approve_requested.connect(lambda s=scene: self._on_scene_approve(s.id))
            card.request_changes_requested.connect(
                lambda notes, s=scene: self._on_scene_request_changes(s.id, notes)
            )
            card.reject_requested.connect(lambda notes, s=scene: self._on_scene_reject(s.id, notes))
            self._scene_list_layout.addWidget(card)

    def _on_add_scene(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.add_scene(session, self._episode_id)
        except ServiceError as err:
            show_error(self, "Add Scene", str(err))
            return
        self._refresh_storyboard_tab()
        self._notify("Scene added.")

    def _on_move_scene(self, scene_id: uuid.UUID, direction: int) -> None:
        try:
            with self._ctx.session_scope() as session:
                scenes = self._ctx.scene_service.list_episode_scenes(session, self._episode_id)
                ids = [s.id for s in scenes]
                pos = ids.index(scene_id)
                new_pos = pos + direction
                if 0 <= new_pos < len(ids):
                    ids[pos], ids[new_pos] = ids[new_pos], ids[pos]
                    self._ctx.scene_service.reorder_scenes(session, self._episode_id, ids)
        except ServiceError as err:
            show_error(self, "Reorder Scene", str(err))
            return
        self._refresh_storyboard_tab()

    def _on_duplicate_scene(self, scene_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.duplicate_scene(session, scene_id)
        except ServiceError as err:
            show_error(self, "Duplicate Scene", str(err))
            return
        self._refresh_storyboard_tab()
        self._notify("Scene duplicated.")

    def _on_delete_scene(self, scene_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.delete_scene(session, scene_id)
        except ConflictError as err:
            show_error(self, "Delete Scene", str(err))
            return
        except ServiceError as err:
            show_error(self, "Delete Scene", str(err))
            return
        self._refresh_storyboard_tab()
        self._notify("Scene deleted.", "info")

    def _on_save_scene(self, scene_id: uuid.UUID, fields: dict[str, object]) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.update_scene(session, scene_id, **fields)
        except ServiceError as err:
            show_error(self, "Save Scene", str(err))
            return
        self._refresh_storyboard_tab()
        self._notify("Scene saved.")

    def _on_scene_characters_changed(self, scene_id: uuid.UUID, character_ids: list) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.set_scene_characters(session, scene_id, character_ids)
        except ServiceError as err:
            show_error(self, "Update Scene Cast", str(err))

    def _on_compose_prompt(self, scene_id: uuid.UUID, card: SceneCard) -> None:
        try:
            with self._ctx.session_scope() as session:
                scene = self._ctx.scene_service.generate_and_store_prompt(session, scene_id)
                prompt_text, negative_prompt_text = scene.prompt_text, scene.negative_prompt_text
        except ServiceError as err:
            show_error(self, "Compose Prompt", str(err))
            return
        card.set_composed_prompt(prompt_text or "", negative_prompt_text or "")
        self._notify("Prompt composed.")

    def _on_scene_approve(self, scene_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.approve_scene(session, scene_id)
        except ServiceError as err:
            show_error(self, "Approve Scene", str(err))
            return
        self._refresh_storyboard_tab()
        self._notify("Scene approved.")

    def _on_scene_request_changes(self, scene_id: uuid.UUID, notes: str) -> None:
        if not notes:
            return
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.request_scene_changes(session, scene_id, notes=notes)
        except ServiceError as err:
            show_error(self, "Request Changes", str(err))
            return
        self._refresh_storyboard_tab()

    def _on_scene_reject(self, scene_id: uuid.UUID, notes: str) -> None:
        if not notes:
            return
        try:
            with self._ctx.session_scope() as session:
                self._ctx.scene_service.reject_scene(session, scene_id, notes=notes)
        except ServiceError as err:
            show_error(self, "Reject Scene", str(err))
            return
        self._refresh_storyboard_tab()

    # =========================================================== IMAGES

    def _build_images_tab(self) -> None:
        scroll, layout = self._new_tab()
        self._images_panel = SceneImagesPanel(self._ctx, self._theme)
        layout.addWidget(self._images_panel)
        self._tabs.addTab(scroll, "🖼 Images")

    # ================================================================== VOICE

    def _build_voice_tab(self) -> None:
        scroll, layout = self._new_tab()
        self._voice_panel = VoiceWorkspacePanel(self._ctx, self._theme)
        layout.addWidget(self._voice_panel)
        self._tabs.addTab(scroll, "🎙️ Voice")

    # =============================================================== MUSIC / VIDEO

    def _build_asset_tab(self, key: str) -> None:
        tab, layout = self._new_tab()
        if key == "music":
            self._build_song_fields(layout)
            layout.addWidget(QLabel("Produced Music Assets"))
        header_row = QHBoxLayout()
        import_button = QPushButton(f"+ Import {key.title()}")
        import_button.setProperty("class", "primary")
        import_button.clicked.connect(lambda _checked=False, k=key: self._on_import_asset(k))
        header_row.addWidget(import_button)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        list_layout = QVBoxLayout()
        list_layout.setSpacing(METRICS.spacing_sm)
        layout.addLayout(list_layout)
        setattr(self, f"_{key}_list_layout", list_layout)

        empty_state = EmptyState(f"No {key} assets yet for this episode.", icon=_ASSET_TAB_ICON[key])
        layout.addWidget(empty_state)
        setattr(self, f"_{key}_empty_state", empty_state)
        layout.addStretch(1)

        self._tabs.addTab(tab, f"{_ASSET_TAB_ICON[key]} {key.title()}")

    def _refresh_asset_tab(self, key: str, asset_type: AssetType) -> None:
        list_layout: QVBoxLayout = getattr(self, f"_{key}_list_layout")
        empty_state: EmptyState = getattr(self, f"_{key}_empty_state")
        while list_layout.count():
            item = list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            with self._ctx.open_session() as session:
                assets = (
                    session.query(Asset)
                    .filter_by(episode_id=self._episode_id, asset_type=asset_type)
                    .order_by(Asset.created_at.desc())
                    .all()
                )
                rows = [(a.original_filename, a.approval_status.value, a.role) for a in assets]
        except OperationalError:
            return

        empty_state.setVisible(not rows)
        for filename, status, role in rows:
            row = EntityRow(_ASSET_TAB_ICON[key], filename, role or "draft candidate")
            variant = {
                "draft": "neutral", "in_review": "info", "approved": "success", "rejected": "danger",
            }[status]
            row.add_trailing_widget(StatusBadge(status.replace("_", " ").title(), variant))
            list_layout.addWidget(row)

    def _on_import_asset(self, key: str) -> None:
        asset_type = _ASSET_TAB_TYPES[key]
        dialog = _ImportSceneAssetDialog(asset_type, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        request = dialog.result_request(self._episode_id)
        self._overlay.start("Importing…")
        try:
            with self._ctx.open_session() as session:
                self._ctx.asset_import_service.import_asset(session, request)
        except (ConflictError, ValidationError, PrivacyViolationError, ServiceError) as err:
            show_error(self, "Import Asset", str(err))
            return
        finally:
            self._overlay.stop()
        self._refresh_asset_tab(key, asset_type)
        self._notify(f"{key.title()} asset imported.")

    # --- Music tab's Song package (written content, not the produced audio file) --

    def _build_song_fields(self, layout: QVBoxLayout) -> None:
        layout.addWidget(QLabel("Song Package"))
        self._song_lyrics = QTextEdit()
        self._song_lyrics.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._song_lyrics.setMinimumHeight(140)
        layout.addWidget(QLabel("Lyrics (Arabic)"))
        layout.addWidget(self._song_lyrics)
        self._song_purpose = QTextEdit()
        layout.addWidget(QLabel("Purpose"))
        layout.addWidget(self._song_purpose)
        self._song_duration = QLineEdit()
        self._song_duration.setPlaceholderText("Approximate duration in seconds")
        layout.addWidget(QLabel("Duration (seconds)"))
        layout.addWidget(self._song_duration)
        self._song_notes = QTextEdit()
        layout.addWidget(QLabel("Production notes"))
        layout.addWidget(self._song_notes)
        self._song_suno_prompt = QTextEdit()
        layout.addWidget(QLabel("Suno-ready style prompt"))
        layout.addWidget(self._song_suno_prompt)

        save_button = QPushButton("Save Song")
        save_button.setProperty("class", "primary")
        save_button.clicked.connect(self._on_save_song)
        layout.addWidget(save_button)

    def _refresh_song_fields(self) -> None:
        try:
            # session_scope, not open_session — see the comment in refresh().
            with self._ctx.session_scope() as session:
                song = self._ctx.song_service.get_or_create_song(session, self._episode_id)
                lyrics, purpose, duration, notes, suno_prompt, song_id = (
                    song.lyrics_ar, song.purpose, song.duration_seconds,
                    song.production_notes, song.suno_style_prompt, song.id,
                )
        except OperationalError:
            return
        self._song_lyrics.setPlainText(lyrics or "")
        self._song_purpose.setPlainText(purpose or "")
        self._song_duration.setText(str(duration) if duration else "")
        self._song_notes.setPlainText(notes or "")
        self._song_suno_prompt.setPlainText(suno_prompt or "")
        self._song_id = song_id

    def _on_save_song(self) -> None:
        duration_text = self._song_duration.text().strip()
        try:
            with self._ctx.session_scope() as session:
                self._ctx.song_service.update_song(
                    session, self._song_id,
                    lyrics_ar=self._song_lyrics.toPlainText().strip() or None,
                    purpose=self._song_purpose.toPlainText().strip() or None,
                    duration_seconds=int(duration_text) if duration_text.isdigit() else None,
                    production_notes=self._song_notes.toPlainText().strip() or None,
                    suno_style_prompt=self._song_suno_prompt.toPlainText().strip() or None,
                )
        except ServiceError as err:
            show_error(self, "Save Song", str(err))
            return
        self._notify("Song saved.")

    # =================================================================== SEO

    def _build_seo_tab(self) -> None:
        tab, layout = self._new_tab()
        self._seo_description_ar = QTextEdit()
        self._seo_description_ar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(QLabel("Description (Arabic)"))
        layout.addWidget(self._seo_description_ar)
        self._seo_description_en = QTextEdit()
        layout.addWidget(QLabel("Description (English)"))
        layout.addWidget(self._seo_description_en)
        self._seo_hashtags = QLineEdit()
        self._seo_hashtags.setPlaceholderText("#kids, #arabic, #storytime")
        layout.addWidget(QLabel("Hashtags (comma-separated)"))
        layout.addWidget(self._seo_hashtags)
        self._seo_credits = QTextEdit()
        layout.addWidget(QLabel("Credits"))
        layout.addWidget(self._seo_credits)

        save_button = QPushButton("Save")
        save_button.setProperty("class", "primary")
        save_button.clicked.connect(self._on_save_seo)
        layout.addWidget(save_button)
        layout.addStretch(1)

        self._tabs.addTab(tab, "🔍 SEO")

    def _refresh_seo_tab(self, episode: Episode) -> None:
        self._seo_description_ar.setPlainText(episode.description_ar or "")
        self._seo_description_en.setPlainText(episode.description_en or "")
        self._seo_hashtags.setText(", ".join(episode.hashtags))
        self._seo_credits.setPlainText(episode.credits_text or "")

    def _on_save_seo(self) -> None:
        hashtags = [tag.strip() for tag in self._seo_hashtags.text().split(",") if tag.strip()]
        try:
            with self._ctx.session_scope() as session:
                self._ctx.episode_service.update_episode(
                    session, self._episode_id,
                    description_ar=self._seo_description_ar.toPlainText().strip() or None,
                    description_en=self._seo_description_en.toPlainText().strip() or None,
                    hashtags=hashtags,
                    credits_text=self._seo_credits.toPlainText().strip() or None,
                )
        except ServiceError as err:
            show_error(self, "Save SEO", str(err))
            return
        self.refresh()
        self._notify("SEO metadata saved.")

    # ================================================================ EXPORT

    def _build_export_tab(self) -> None:
        tab, layout = self._new_tab()
        layout.addWidget(QLabel("Stage summary"))
        self._stage_summary_layout = QVBoxLayout()
        layout.addLayout(self._stage_summary_layout)

        layout.addWidget(QLabel("Readiness checklist"))
        self._checklist_layout = QVBoxLayout()
        layout.addLayout(self._checklist_layout)

        button_row = QHBoxLayout()
        self._ready_button = QPushButton("Move to Ready to Publish")
        self._ready_button.setProperty("class", "primary")
        self._ready_button.clicked.connect(self._on_mark_ready_to_publish)
        button_row.addWidget(self._ready_button)
        self._publish_button = QPushButton("Publish")
        self._publish_button.clicked.connect(self._on_publish)
        button_row.addWidget(self._publish_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

        self._tabs.addTab(tab, "🚀 Export")

    def _refresh_export_tab(self, episode: Episode, stage_summary: list) -> None:
        while self._stage_summary_layout.count():
            item = self._stage_summary_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for status in stage_summary:
            row = QHBoxLayout()
            row.addWidget(QLabel(_STAGE_LABEL[status.stage]))
            variant = _STAGE_STATE_VARIANT[status.status.value]
            row.addWidget(StatusBadge(status.status.value.replace("_", " ").title(), variant))
            if status.reason:
                reason_label = QLabel(status.reason)
                reason_label.setProperty("class", "entityRowSubtitle")
                row.addWidget(reason_label, stretch=1)
            else:
                row.addStretch(1)
            wrap = QWidget()
            wrap.setLayout(row)
            self._stage_summary_layout.addWidget(wrap)

        while self._checklist_layout.count():
            item = self._checklist_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        try:
            with self._ctx.open_session() as session:
                report = self._ctx.production_checklist_service.evaluate(session, self._episode_id)
        except OperationalError:
            return
        for check in report.checks:
            icon = "✅" if check.passed else ("⛔" if check.blocking else "⚠️")
            line = QLabel(f"{icon}  {check.message}")
            line.setWordWrap(True)
            self._checklist_layout.addWidget(line)

        self._ready_button.setEnabled(
            episode.pipeline_stage != PipelineStage.READY_TO_PUBLISH
            and episode.pipeline_stage != PipelineStage.PUBLISHED
            and report.is_ready
        )
        self._publish_button.setEnabled(episode.pipeline_stage == PipelineStage.READY_TO_PUBLISH)

    def _on_mark_ready_to_publish(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.episode_service.change_episode_status(
                    session, self._episode_id, PipelineStage.READY_TO_PUBLISH
                )
        except (ChecklistError, InvalidTransitionError, ServiceError) as err:
            show_error(self, "Move to Ready to Publish", str(err))
            return
        self.refresh()
        self._notify("Episode is ready to publish.")

    def _on_publish(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.episode_service.change_episode_status(
                    session, self._episode_id, PipelineStage.PUBLISHED
                )
        except (ChecklistError, InvalidTransitionError, ServiceError) as err:
            show_error(self, "Publish", str(err))
            return
        self.refresh()
        self._notify("Episode published.")

    # --- shared tab scaffolding -----------------------------------------------

    @staticmethod
    def _new_tab() -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg
        )
        layout.setSpacing(METRICS.spacing_md)
        scroll.setWidget(content)
        return scroll, layout
