"""ErrorState — an inline "something went wrong" block with a Retry action.

Distinct from the modal dialogs in ``dialogs.py``: a list page whose
initial data load fails (e.g. the database has no tables yet) shows
this embedded in the page instead of a blocking ``QMessageBox`` every
time ``refresh()`` runs — the user can keep looking at the rest of the
app and retry in place.

v2 polish: the icon now sits in the same tinted circular chip
:class:`~app.gui.widgets.empty_state.EmptyState` uses — one shared
"nothing/something's wrong here" visual language across every page
instead of a bare, differently-sized icon per state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_ICON_BADGE_SIZE = 64


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
        icon_label.setProperty("class", "emptyStateIcon")
        icon_label.setFixedSize(_ICON_BADGE_SIZE, _ICON_BADGE_SIZE)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._message_label = QLabel(message)
        self._message_label.setProperty("class", "emptyStateMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setMaximumWidth(360)
        layout.addWidget(self._message_label)

        self._retry_button: QPushButton | None = None
        if retry_label is not None:
            self._retry_button = QPushButton(retry_label)
            self._retry_button.setProperty("class", "primary")
            self._retry_button.clicked.connect(self.retry_requested.emit)
            layout.addWidget(self._retry_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_message(self, message: str) -> None:
        self._message_label.setText(message)
