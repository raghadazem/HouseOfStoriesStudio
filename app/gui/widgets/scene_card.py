"""SceneCard — one scene in the Episode Workspace's Storyboard tab.

A ``QFrame``-based card (not :class:`~app.gui.widgets.entity_row.EntityRow`)
because a scene needs many independent inline actions at once (reorder,
duplicate, delete, approve/reject, expand/collapse) — the same reason
``ReviewQueuePage`` builds its own row instead of reusing ``EntityRow``,
which is documented as read-only-trailing-content only.

This widget only edits and emits — it never touches
``ApplicationContext``/a service/the database itself. The Storyboard tab
(``EpisodeWorkspacePage``) owns every signal this emits and performs the
actual service calls, exactly like every other page's create/detail
dialogs already do.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.db.enums import ApprovalDecision
from app.core.models import Character, Scene
from app.gui.theme.tokens import METRICS
from app.gui.widgets.elevated_card import ElevatedCard
from app.gui.widgets.status_badge import StatusBadge, Variant

_APPROVAL_BADGE: dict[ApprovalDecision | None, tuple[str, Variant]] = {
    None: ("Draft", "neutral"),
    ApprovalDecision.APPROVED: ("Approved", "success"),
    ApprovalDecision.NEEDS_CHANGES: ("Needs Changes", "warning"),
    ApprovalDecision.REJECTED: ("Rejected", "danger"),
}


class SceneCard(ElevatedCard):
    """One expandable/collapsible scene, with inline reorder/duplicate/delete/approval actions."""

    move_up_requested = Signal()
    move_down_requested = Signal()
    duplicate_requested = Signal()
    delete_requested = Signal()
    save_requested = Signal(dict)
    characters_changed_requested = Signal(list)
    compose_prompt_requested = Signal()
    approve_requested = Signal()
    request_changes_requested = Signal(str)
    reject_requested = Signal(str)

    def __init__(
        self,
        scene: Scene,
        all_characters: Iterable[Character],
        approval_state: ApprovalDecision | None,
        *,
        is_first: bool,
        is_last: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scene_id = scene.id
        self._expanded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_sm, METRICS.spacing_md, METRICS.spacing_sm
        )
        root.setSpacing(METRICS.spacing_sm)

        header = QHBoxLayout()
        header.setSpacing(METRICS.spacing_sm)

        self._toggle_button = QPushButton("▶")
        self._toggle_button.setFixedWidth(28)
        self._toggle_button.clicked.connect(self.toggle_expanded)
        header.addWidget(self._toggle_button)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self._title_label = QLabel(self._display_title(scene))
        self._title_label.setProperty("class", "entityRowTitle")
        title_column.addWidget(self._title_label)
        duration = f"{scene.estimated_duration_seconds}s" if scene.estimated_duration_seconds else "no estimate"
        self._subtitle_label = QLabel(duration)
        self._subtitle_label.setProperty("class", "entityRowSubtitle")
        title_column.addWidget(self._subtitle_label)
        header.addLayout(title_column, stretch=1)

        badge_text, badge_variant = _APPROVAL_BADGE[approval_state]
        self._status_badge = StatusBadge(badge_text, badge_variant)
        header.addWidget(self._status_badge)

        up_button = QPushButton("▲")
        up_button.setEnabled(not is_first)
        up_button.setFixedWidth(28)
        up_button.clicked.connect(self.move_up_requested.emit)
        header.addWidget(up_button)

        down_button = QPushButton("▼")
        down_button.setEnabled(not is_last)
        down_button.setFixedWidth(28)
        down_button.clicked.connect(self.move_down_requested.emit)
        header.addWidget(down_button)

        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self.duplicate_requested.emit)
        header.addWidget(duplicate_button)

        delete_button = QPushButton("Delete")
        delete_button.setProperty("class", "danger")
        delete_button.clicked.connect(self.delete_requested.emit)
        header.addWidget(delete_button)

        root.addLayout(header)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_sm, 0, METRICS.spacing_sm
        )
        body_layout.setSpacing(METRICS.spacing_sm)

        self._title_field = self._labeled_line_edit(body_layout, "Title", scene.title)
        self._narration_field = self._labeled_text_edit(body_layout, "Narration", scene.dialogue_ar)
        self._description_field = self._labeled_text_edit(
            body_layout, "Visual description", scene.description
        )
        self._camera_field = self._labeled_line_edit(
            body_layout, "Camera direction", scene.camera_direction
        )
        self._location_field = self._labeled_line_edit(body_layout, "Location", scene.location)
        self._duration_field = self._labeled_line_edit(
            body_layout, "Duration (seconds)",
            str(scene.estimated_duration_seconds) if scene.estimated_duration_seconds else "",
        )

        body_layout.addWidget(_field_label("Characters"))
        self._character_checkboxes: dict[object, QCheckBox] = {}
        present_ids = {c.id for c in scene.characters_present}
        for character in all_characters:
            checkbox = QCheckBox(character.name_en)
            checkbox.setChecked(character.id in present_ids)
            checkbox.stateChanged.connect(self._on_characters_changed)
            self._character_checkboxes[character.id] = checkbox
            body_layout.addWidget(checkbox)

        self._prompt_field = self._labeled_text_edit(body_layout, "Prompt", scene.prompt_text)
        self._negative_prompt_field = self._labeled_text_edit(
            body_layout, "Negative prompt", scene.negative_prompt_text
        )

        compose_row = QHBoxLayout()
        compose_button = QPushButton("Compose Prompt")
        compose_button.clicked.connect(self.compose_prompt_requested.emit)
        compose_row.addWidget(compose_button)
        compose_row.addStretch(1)
        body_layout.addLayout(compose_row)

        save_row = QHBoxLayout()
        save_button = QPushButton("Save Scene")
        save_button.setProperty("class", "primary")
        save_button.clicked.connect(self._on_save_clicked)
        save_row.addWidget(save_button)
        save_row.addStretch(1)
        body_layout.addLayout(save_row)

        approval_row = QHBoxLayout()
        approve_button = QPushButton("Approve")
        approve_button.setProperty("class", "primary")
        approve_button.clicked.connect(self.approve_requested.emit)
        approval_row.addWidget(approve_button)

        request_changes_button = QPushButton("Request Changes")
        request_changes_button.clicked.connect(self._on_request_changes_clicked)
        approval_row.addWidget(request_changes_button)

        reject_button = QPushButton("Reject")
        reject_button.setProperty("class", "danger")
        reject_button.clicked.connect(self._on_reject_clicked)
        approval_row.addWidget(reject_button)
        approval_row.addStretch(1)
        body_layout.addLayout(approval_row)

        root.addWidget(self._body)
        self._body.setVisible(False)

    # --- expand/collapse ----------------------------------------------------

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._toggle_button.setText("▼" if expanded else "▶")

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    # --- field access ---------------------------------------------------------

    def collected_fields(self) -> dict[str, object]:
        """Every editable field, ready for ``SceneService.update_scene(**fields)``."""
        duration_text = self._duration_field.text().strip()
        return {
            "title": self._title_field.text().strip() or None,
            "dialogue_ar": self._narration_field.toPlainText().strip() or None,
            "description": self._description_field.toPlainText().strip() or None,
            "camera_direction": self._camera_field.text().strip() or None,
            "location": self._location_field.text().strip() or None,
            "estimated_duration_seconds": int(duration_text) if duration_text.isdigit() else None,
            "prompt_text": self._prompt_field.toPlainText().strip() or None,
            "negative_prompt_text": self._negative_prompt_field.toPlainText().strip() or None,
        }

    def set_composed_prompt(self, prompt_text: str, negative_prompt_text: str) -> None:
        """Called by the Storyboard tab after ``PromptComposerService`` runs."""
        self._prompt_field.setPlainText(prompt_text)
        self._negative_prompt_field.setPlainText(negative_prompt_text)

    # --- internal -------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        self.save_requested.emit(self.collected_fields())

    def _on_characters_changed(self, *_args: object) -> None:
        selected = [char_id for char_id, box in self._character_checkboxes.items() if box.isChecked()]
        self.characters_changed_requested.emit(selected)

    def _on_request_changes_clicked(self) -> None:
        self.request_changes_requested.emit(_prompt_for_notes(self, "Request Changes"))

    def _on_reject_clicked(self) -> None:
        self.reject_requested.emit(_prompt_for_notes(self, "Reject Scene"))

    @staticmethod
    def _display_title(scene: Scene) -> str:
        base = f"Scene {scene.order_index}"
        return f"{base}: {scene.title}" if scene.title else base

    @staticmethod
    def _labeled_line_edit(layout: QVBoxLayout, label: str, value: str | None) -> QLineEdit:
        layout.addWidget(_field_label(label))
        field = QLineEdit(value or "")
        layout.addWidget(field)
        return field

    @staticmethod
    def _labeled_text_edit(layout: QVBoxLayout, label: str, value: str | None) -> QTextEdit:
        layout.addWidget(_field_label(label))
        field = QTextEdit(value or "")
        field.setMinimumHeight(70)
        layout.addWidget(field)
        return field


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "formLabel")
    return label


def _prompt_for_notes(parent: QWidget, title: str) -> str:
    """A minimal inline notes prompt — a full dialog would be one more
    modal for what's fundamentally a single required text field."""
    text, _ok = QInputDialog.getMultiLineText(parent, title, "Notes:")
    return text.strip()
