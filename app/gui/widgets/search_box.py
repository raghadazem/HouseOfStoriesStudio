"""SearchBox — a labeled search input, reusable across future list screens.

Not wired to any real search in Milestone 4A (no list screen exists
yet to search) — ``returnPressed`` is exposed so a future screen can
connect it without changing this widget.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from app.gui.theme.tokens import METRICS


class SearchBox(QWidget):
    return_pressed = Signal(str)

    def __init__(self, placeholder: str = "Search…", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.spacing_xs)

        self._field = QLineEdit()
        self._field.setPlaceholderText(placeholder)
        self._field.returnPressed.connect(self._on_return_pressed)

        icon = QLabel("🔍")
        icon.setStyleSheet("padding-left: 2px;")

        layout.addWidget(icon)
        layout.addWidget(self._field)

    def _on_return_pressed(self) -> None:
        self.return_pressed.emit(self._field.text())

    def text(self) -> str:
        return self._field.text()

    def clear(self) -> None:
        self._field.clear()
