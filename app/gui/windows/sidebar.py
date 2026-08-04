"""Sidebar — the app's permanent left-hand navigation rail.

Every item is listed here, in one place, so adding a Milestone 4B
screen later means adding one entry to :data:`NAV_ITEMS` — not editing
``MainWindow`` layout code.

v2 polish: items are grouped under small section labels with
separators, the selected item is tracked by an animated sliding
indicator bar (not just an instant background swap), and one item
(Review Queue) can carry a real notification badge (the actual pending-
review count — never a fabricated number). Nav icons are the custom
vector glyphs from ``nav_icon.py`` rendered as ``QIcon``s — deliberately
still plain, checkable ``QPushButton``s underneath so keyboard focus/
activation (Tab, Space/Enter) keeps working exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets.nav_icon import render_nav_icon

_INDICATOR_ANIM_MS = 220
_ICON_SIZE = 18


@dataclass(frozen=True)
class NavItem:
    key: str
    glyph: str
    label: str
    group: str
    implemented: bool = False


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("dashboard", "dashboard", "Dashboard", "Workspace", implemented=True),
    NavItem("episodes", "episodes", "Episodes", "Production", implemented=True),
    NavItem("characters", "characters", "Characters", "Production", implemented=True),
    NavItem("assets", "assets", "Assets", "Production", implemented=True),
    NavItem("prompts", "prompts", "Prompts", "Production", implemented=True),
    NavItem("review_queue", "review_queue", "Review Queue", "Review", implemented=True),
    NavItem("settings", "settings", "Settings", "System", implemented=True),
)


class Sidebar(QWidget):
    """Emits :attr:`item_selected` with a :class:`NavItem` key when clicked."""

    item_selected = Signal(str)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(METRICS.sidebar_width)
        self._theme = theme
        self._selected_key = "dashboard"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_md, METRICS.spacing_sm, METRICS.spacing_lg
        )
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}

        current_group: str | None = None
        for item in NAV_ITEMS:
            if item.group != current_group:
                if current_group is not None:
                    layout.addWidget(self._build_separator())
                layout.addWidget(self._build_group_label(item.group))
                current_group = item.group
            layout.addWidget(self._build_row(item))

        layout.addStretch(1)

        self._indicator = QFrame(self)
        self._indicator.setObjectName("sidebarIndicator")
        self._indicator.hide()

        self._indicator_anim = QPropertyAnimation(self._indicator, b"geometry", self)
        self._indicator_anim.setDuration(_INDICATOR_ANIM_MS)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._theme.theme_changed.connect(self._refresh_all_icons)
        self.select("dashboard")

    # --- construction --------------------------------------------------------

    def _build_group_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("sidebarSectionLabel")
        return label

    def _build_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setProperty("class", "sidebarSeparator")
        return line

    def _build_row(self, item: NavItem) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        button = QPushButton(f"  {item.label}")
        button.setProperty("class", "sidebarButton")
        button.setCheckable(True)
        button.setObjectName(f"navButton_{item.key}")
        button.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        button.setIcon(render_nav_icon(item.glyph, self._theme.tokens.sidebar_text_muted, _ICON_SIZE))
        button.clicked.connect(lambda _checked, key=item.key: self._on_clicked(key))
        self._group.addButton(button)
        self._buttons[item.key] = button
        row_layout.addWidget(button, stretch=1)

        badge = QLabel("")
        badge.setProperty("class", "sidebarBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setVisible(False)
        self._badges[item.key] = badge
        row_layout.addWidget(badge)

        return row

    # --- selection -------------------------------------------------------------

    def _on_clicked(self, key: str) -> None:
        self.select(key)
        self.item_selected.emit(key)

    def select(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is None:
            return
        was_visible = self._indicator.isVisible()
        self._selected_key = key
        button.setChecked(True)
        self._refresh_icon(key, active=True)
        for other_key in self._buttons:
            if other_key != key:
                self._refresh_icon(other_key, active=False)
        self._move_indicator_to(button, animate=was_visible)

    def button_for(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)

    def set_badge(self, key: str, count: int) -> None:
        """A real notification count (e.g. pending review assets) — 0 hides it."""
        badge = self._badges.get(key)
        if badge is None:
            return
        if count <= 0:
            badge.setVisible(False)
            return
        badge.setText(str(count) if count <= 99 else "99+")
        badge.setVisible(True)

    # --- indicator --------------------------------------------------------------

    def _move_indicator_to(self, button: QPushButton, *, animate: bool) -> None:
        # The indicator lives in the sidebar's row, at the button's y —
        # `button.pos()` is already relative to `self` since the row
        # widgets have no extra offset of their own.
        target = QRect(0, button.mapTo(self, button.rect().topLeft()).y(), 3, button.height())
        self._indicator.raise_()
        if not animate:
            self._indicator.setGeometry(target)
            self._indicator.show()
            return
        self._indicator_anim.stop()
        self._indicator_anim.setStartValue(self._indicator.geometry())
        self._indicator_anim.setEndValue(target)
        self._indicator_anim.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        button = self._buttons.get(self._selected_key)
        if button is not None:
            self._move_indicator_to(button, animate=False)

    # --- icons -------------------------------------------------------------------

    def _refresh_icon(self, key: str, *, active: bool) -> None:
        button = self._buttons.get(key)
        if button is None:
            return
        item = next(i for i in NAV_ITEMS if i.key == key)
        color = self._theme.tokens.sidebar_selected_text if active else self._theme.tokens.sidebar_text_muted
        button.setIcon(render_nav_icon(item.glyph, color, _ICON_SIZE))

    def _refresh_all_icons(self, _theme_name: str) -> None:
        for key in self._buttons:
            self._refresh_icon(key, active=(key == self._selected_key))
