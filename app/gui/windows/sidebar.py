"""Sidebar — the app's permanent left-hand navigation rail.

Every item is listed here, in one place, so adding a Milestone 4B
screen later means adding one entry to :data:`NAV_ITEMS` — not editing
``MainWindow`` layout code.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


@dataclass(frozen=True)
class NavItem:
    key: str
    icon: str
    label: str
    implemented: bool = False


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("dashboard", "🏠", "Dashboard", implemented=True),
    NavItem("episodes", "🎬", "Episodes"),
    NavItem("characters", "👧", "Characters"),
    NavItem("assets", "🖼", "Assets"),
    NavItem("prompts", "📝", "Prompts"),
    NavItem("review_queue", "✅", "Review Queue"),
    NavItem("settings", "⚙", "Settings"),
)


class Sidebar(QWidget):
    """Emits :attr:`item_selected` with a :class:`NavItem` key when clicked."""

    item_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(METRICS.sidebar_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_lg, METRICS.spacing_sm, METRICS.spacing_lg
        )
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for item in NAV_ITEMS:
            button = QPushButton(f"{item.icon}   {item.label}")
            button.setProperty("class", "sidebarButton")
            button.setCheckable(True)
            button.setObjectName(f"navButton_{item.key}")
            button.clicked.connect(lambda _checked, key=item.key: self.item_selected.emit(key))
            self._group.addButton(button)
            self._buttons[item.key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.select("dashboard")

    def select(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def button_for(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)
