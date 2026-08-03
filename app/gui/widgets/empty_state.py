"""EmptyState — a small, friendly "nothing here yet" block, embedded inside a card/panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


class EmptyState(QWidget):
    def __init__(
        self,
        message: str,
        icon: str = "🗂",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg
        )
        layout.setSpacing(METRICS.spacing_xs)
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

    def set_message(self, message: str) -> None:
        self._message_label.setText(message)
