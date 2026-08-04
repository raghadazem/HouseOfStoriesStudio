"""FormDialog — the base for every create-form and read-only detail dialog.

One consistent shell instead of each page building its own ad hoc
``QDialog``. A create-form subclass overrides :meth:`validate` to check
its fields before ``accept()``; a read-only detail dialog passes
``show_save=False`` and gets a single "Close" button.

v2 polish: the plain title label became a header row (an optional icon
chip + title + subtitle) so a dialog reads less like a bare form and
more like the rest of the app's cards; a thin accent-colored top edge
and a divider before the footer give it a defined shape instead of
flowing content edge-to-edge; and the whole shell fades in on open — a
purely cosmetic touch, so it is applied to an inner content widget
rather than the top-level ``QDialog`` itself, which keeps native window
behavior (positioning, modality, close-on-Escape) untouched.

``QDialog`` gives Escape-to-close and Enter-triggers-the-default-button
for free — no extra keyboard wiring needed here.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.tokens import METRICS

_OPEN_ANIM_MS = 160


class FormDialog(QDialog):
    def __init__(
        self,
        title: str,
        *,
        icon: str | None = None,
        subtitle: str | None = None,
        save_label: str = "Save",
        show_save: bool = True,
        min_width: int = 460,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)

        # Everything lives inside `shell`, not directly on the QDialog —
        # so the open-fade effect below animates the content, never the
        # top-level window (opacity effects on a real OS window can
        # misbehave/flicker on some platforms; on a plain child widget
        # they're always safe).
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        shell = QFrame()
        shell.setObjectName("formDialogShell")
        dialog_layout.addWidget(shell)

        outer = QVBoxLayout(shell)
        outer.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg
        )
        outer.setSpacing(METRICS.spacing_md)

        header = QHBoxLayout()
        header.setSpacing(METRICS.spacing_sm)
        if icon is not None:
            icon_chip = QLabel(icon)
            icon_chip.setProperty("class", "iconChip")
            icon_chip.setFixedSize(40, 40)
            icon_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(icon_chip)

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title_label = QLabel(title)
        title_label.setProperty("class", "dialogTitle")
        title_label.setWordWrap(True)
        title_column.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("class", "dialogSubtitle")
            subtitle_label.setWordWrap(True)
            title_column.addWidget(subtitle_label)
        header.addLayout(title_column, stretch=1)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("formDialogScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(METRICS.spacing_md)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self._error_label = QLabel("")
        self._error_label.setProperty("class", "formError")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setProperty("class", "dialogDivider")
        outer.addWidget(divider)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._save_button: QPushButton | None = None
        if show_save:
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject)
            footer.addWidget(cancel_button)

            self._save_button = QPushButton(save_label)
            self._save_button.setProperty("class", "primary")
            self._save_button.setDefault(True)
            self._save_button.clicked.connect(self._on_save_clicked)
            footer.addWidget(self._save_button)
        else:
            close_button = QPushButton("Close")
            close_button.setDefault(True)
            close_button.clicked.connect(self.accept)
            footer.addWidget(close_button)
        outer.addLayout(footer)

        self._opacity_effect = QGraphicsOpacityEffect(shell)
        self._opacity_effect.setOpacity(1.0)
        shell.setGraphicsEffect(self._opacity_effect)
        self._open_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._open_anim.setDuration(_OPEN_ANIM_MS)
        self._open_anim.setStartValue(0.0)
        self._open_anim.setEndValue(1.0)
        self._open_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._opacity_effect.setOpacity(0.0)
        self._open_anim.stop()
        self._open_anim.start()

    def add_row(self, label: str, widget: QWidget) -> None:
        """A labeled field row: a caption above the input, added to `content_layout`."""
        row = QVBoxLayout()
        row.setSpacing(4)
        caption = QLabel(label)
        caption.setProperty("class", "formLabel")
        row.addWidget(caption)
        row.addWidget(widget)
        self.content_layout.addLayout(row)

    def validate(self) -> str | None:
        """Override to check fields before accept(). Return an error message, or None if valid."""
        return None

    def show_form_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_save_clicked(self) -> None:
        error = self.validate()
        if error:
            self.show_form_error(error)
            return
        self._error_label.setVisible(False)
        self.accept()
