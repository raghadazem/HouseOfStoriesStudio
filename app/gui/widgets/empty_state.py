"""EmptyState — a friendly "nothing here yet" block, embedded inside a card/panel.

v2 polish: the icon now sits in the same tinted circular chip treatment
used everywhere else in the app (``EntityRow``, ``ActionCard``,
``SummaryCard``) instead of floating as bare, differently-sized text —
one consistent icon language across the whole app. An optional
``action_label`` lets a list page's own "nothing here yet" state carry
its own primary action (e.g. "+ New Episode") right where the user is
already looking, in addition to the page header's button — a common,
deliberate duplication in empty-state design, not an accident.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_ICON_BADGE_SIZE = 64


class EmptyState(QWidget):
    action_triggered = Signal()

    def __init__(
        self,
        message: str,
        icon: str = "🗂",
        *,
        action_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg
        )
        layout.setSpacing(METRICS.spacing_sm)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_badge = QLabel(icon)
        icon_badge.setProperty("class", "emptyStateIcon")
        icon_badge.setFixedSize(_ICON_BADGE_SIZE, _ICON_BADGE_SIZE)
        icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._message_label = QLabel(message)
        self._message_label.setProperty("class", "emptyStateMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setMaximumWidth(360)
        layout.addWidget(self._message_label)

        self._action_button: QPushButton | None = None
        if action_label is not None:
            self._action_button = QPushButton(action_label)
            self._action_button.setProperty("class", "primary")
            self._action_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._action_button.clicked.connect(self.action_triggered.emit)
            layout.addSpacing(METRICS.spacing_xs)
            layout.addWidget(self._action_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def set_message(self, message: str, *, show_action: bool = True) -> None:
        self._message_label.setText(message)
        if self._action_button is not None:
            self._action_button.setVisible(show_action)
