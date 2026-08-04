"""ErrorState — an inline "something went wrong" block with a Retry action.

Distinct from the modal dialogs in ``dialogs.py``: a list page whose
initial data load fails (e.g. the database has no tables yet) shows
this embedded in the page instead of a blocking ``QMessageBox`` every
time ``refresh()`` runs — the user can keep looking at the rest of the
app and retry in place.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


class ErrorState(QWidget):
    retry_requested = Signal()

    def __init__(
        self,
        message: str,
        *,
        icon: str = "⚠️",
        retry_label: str | None = "Retry",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg
        )
        layout.setSpacing(METRICS.spacing_sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"font-size: {METRICS.font_size_xl}px;")
        layout.addWidget(icon_label)

        self._message_label = QLabel(message)
        self._message_label.setProperty("class", "muted")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        self._retry_button: QPushButton | None = None
        if retry_label is not None:
            self._retry_button = QPushButton(retry_label)
            self._retry_button.setProperty("class", "primary")
            self._retry_button.clicked.connect(self.retry_requested.emit)
            layout.addWidget(self._retry_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_message(self, message: str) -> None:
        self._message_label.setText(message)
