"""ResponsiveGrid — reflows a list of cards into however many columns fit the width.

Shared by the Characters and Assets grids (Milestone 4B) so "responsive
resizing" is solved once instead of twice. Qt has no built-in flow
layout; this recomputes the column count on every resize and re-places
the same card widgets (cheap — it never rebuilds them) into a
``QGridLayout``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QWidget

from app.gui.theme.tokens import METRICS


class ResponsiveGrid(QWidget):
    def __init__(
        self, card_min_width: int = 180, spacing: int = METRICS.spacing_md, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._card_min_width = card_min_width
        self._spacing = spacing
        self._cards: list[QWidget] = []
        self._columns = 0

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def set_cards(self, cards: list[QWidget]) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        self._cards = cards
        self._columns = 0  # force a re-layout even if the width hasn't changed
        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        if not self._cards:
            return
        columns = max(1, (self.width() + self._spacing) // (self._card_min_width + self._spacing))
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            row, col = divmod(index, columns)
            self._grid.addWidget(card, row, col)
