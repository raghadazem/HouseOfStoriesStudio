"""ActionCard — one clickable "production shortcut" card for the Quick Actions panel.

Same click semantics as a ``QPushButton`` (one ``clicked`` signal, no
extra behavior) — the redesign is purely visual: a bigger icon, a
title, an optional one-line description, and the same hover-lift every
``ElevatedCard`` gets, instead of a plain toolbar-style button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS
from app.gui.widgets.elevated_card import ElevatedCard


class ActionCard(ElevatedCard):
    clicked = Signal()

    def __init__(
        self,
        icon: str,
        title: str,
        description: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "actionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(4)

        icon_label = QLabel(icon)
        icon_label.setProperty("class", "actionCardIcon")
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setProperty("class", "actionCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setProperty("class", "muted")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
