"""PlaceholderPage — a full-page "not built yet" screen for un-implemented sidebar sections."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


class PlaceholderPage(QWidget):
    def __init__(
        self,
        title: str,
        message: str = "Coming in Milestone 4B.",
        icon: str = "🛠",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("placeholderPage")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(METRICS.spacing_sm)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setProperty("class", "sectionTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setProperty("class", "muted")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message_label)
