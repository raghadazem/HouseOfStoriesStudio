"""SearchBox — a labeled search input, reusable across every list screen.

Milestone 4B is the first real caller: every list page (Episodes,
Characters, Assets, Prompts, Review Queue) connects ``text_changed`` to
filter its rows live as the user types, rather than waiting for Enter.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from app.gui.theme.tokens import METRICS


class SearchBox(QWidget):
    return_pressed = Signal(str)
    text_changed = Signal(str)

    def __init__(self, placeholder: str = "Search…", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.spacing_xs)

        self._field = QLineEdit()
        self._field.setPlaceholderText(placeholder)
        self._field.returnPressed.connect(self._on_return_pressed)
        self._field.textChanged.connect(self.text_changed.emit)

        icon = QLabel("🔍")
        icon.setStyleSheet("padding-left: 2px;")

        layout.addWidget(icon)
        layout.addWidget(self._field)

        # Ctrl+F focuses the search field from anywhere on the page.
        self._focus_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._focus_shortcut.activated.connect(self._focus_field)

    def _on_return_pressed(self) -> None:
        self.return_pressed.emit(self._field.text())

    def _focus_field(self) -> None:
        self._field.setFocus()
        self._field.selectAll()

    def text(self) -> str:
        return self._field.text()

    def clear(self) -> None:
        self._field.clear()

    def set_focus(self) -> None:
        self._field.setFocus()
