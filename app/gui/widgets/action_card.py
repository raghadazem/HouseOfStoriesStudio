"""ActionCard — one clickable "production shortcut" tile for the Quick Actions panel.

Same click semantics as a ``QPushButton`` (one ``clicked`` signal, no
extra behavior). v2 polish: the icon now sits in the same tinted chip
``SummaryCard`` uses (``class="iconChip"``) — one consistent icon
treatment across the whole Dashboard instead of a bare, differently-
sized emoji per widget — plus a larger minimum footprint for a bigger
clickable target and a dedicated (not generic "muted") description
style, matching the deliberate type hierarchy in
``docs/24_UI_UX_POLISH_V2_STATUS.md`` §7.
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
        self.setMinimumHeight(128)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        icon_label = QLabel(icon)
        icon_label.setProperty("class", "iconChip")
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setProperty("class", "actionCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setProperty("class", "actionCardDescription")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # A quick "sink" using the hover-shadow animation this card
            # already has (via ElevatedCard) — cheap, visible press
            # feedback without introducing a second animation system.
            self.animate_resting()
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.underMouse():
            self.animate_hover()
        super().mouseReleaseEvent(event)
