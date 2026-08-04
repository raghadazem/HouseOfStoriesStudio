"""ToolbarRow — a horizontal control row that wraps to vertical at narrow widths.

Every list page (Episodes, Characters, Assets, Prompts, Review Queue)
builds its toolbar the same way: a ``SearchBox`` plus one or two
``QComboBox`` filters. A plain ``QHBoxLayout`` squeezes those filters
unreadably once the window gets narrow; below ``_WRAP_BELOW_WIDTH`` this
stacks them vertically instead, with the search field spanning the full
width — solved once here rather than duplicated per page.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_WRAP_BELOW_WIDTH = 640


class ToolbarRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[QWidget, int]] = []
        self._inner: QHBoxLayout | QVBoxLayout | None = None
        self._wrapped: bool | None = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        widget.setParent(self)
        self._items.append((widget, stretch))
        self._relayout(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, *, force: bool = False) -> None:
        should_wrap = self.width() < _WRAP_BELOW_WIDTH
        if not force and should_wrap == self._wrapped:
            return
        self._wrapped = should_wrap

        if self._inner is not None:
            while self._inner.count():
                self._inner.takeAt(0)
            self._root.removeItem(self._inner)

        self._inner = QVBoxLayout() if should_wrap else QHBoxLayout()
        self._inner.setContentsMargins(0, 0, 0, 0)
        self._inner.setSpacing(METRICS.spacing_sm)
        for widget, stretch in self._items:
            self._inner.addWidget(widget, 0 if should_wrap else stretch)
        self._root.addLayout(self._inner)
