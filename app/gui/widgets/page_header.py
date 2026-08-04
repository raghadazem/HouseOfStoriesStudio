"""PageHeader — the title bar for a top-level screen (Episodes, Characters, ...).

Distinct from :class:`~app.gui.widgets.section_header.SectionHeader`,
which titles a *sub-section* within a page (Dashboard's "Overview",
"Quick Actions"). A page only ever has one ``PageHeader``, at the very
top, optionally followed by a :class:`~app.gui.widgets.toolbar_row.ToolbarRow`
built by the page itself (screens differ too much in what they filter
by for one shared filter-bar widget to fit all of them).

v2 polish: below ``_WRAP_BELOW_WIDTH`` the primary action button drops
onto its own line under the title instead of squeezing against it — the
same narrow-window concern ``ToolbarRow`` solves for the filter row
below this header.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_WRAP_BELOW_WIDTH = 420


class PageHeader(QWidget):
    primary_action_triggered = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        primary_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._wrapped: bool | None = None
        self._inner: QHBoxLayout | QVBoxLayout | None = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "pageTitle")
        text_column.addWidget(self._title_label)

        self._subtitle_label: QLabel | None = None
        if subtitle:
            self._subtitle_label = QLabel(subtitle)
            self._subtitle_label.setProperty("class", "pageSubtitle")
            text_column.addWidget(self._subtitle_label)

        self._text_column = text_column

        self._primary_button: QPushButton | None = None
        if primary_label is not None:
            self._primary_button = QPushButton(primary_label)
            self._primary_button.setProperty("class", "primary")
            self._primary_button.clicked.connect(self.primary_action_triggered.emit)

        self._relayout(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, *, force: bool = False) -> None:
        should_wrap = self._primary_button is not None and self.width() < _WRAP_BELOW_WIDTH
        if not force and should_wrap == self._wrapped:
            return
        self._wrapped = should_wrap

        if self._inner is not None:
            while self._inner.count():
                self._inner.takeAt(0)
            self._root.removeItem(self._inner)

        self._inner = QVBoxLayout() if should_wrap else QHBoxLayout()
        self._inner.setContentsMargins(0, 0, 0, 0)
        self._inner.setSpacing(METRICS.spacing_md)
        self._inner.addLayout(self._text_column)
        if should_wrap:
            if self._primary_button is not None:
                self._inner.addWidget(self._primary_button)
        else:
            self._inner.addStretch(1)
            if self._primary_button is not None:
                self._inner.addWidget(self._primary_button)
        self._root.addLayout(self._inner)

    def set_subtitle(self, subtitle: str) -> None:
        if self._subtitle_label is not None:
            self._subtitle_label.setText(subtitle)

    def set_primary_enabled(self, enabled: bool) -> None:
        if self._primary_button is not None:
            self._primary_button.setEnabled(enabled)

    @property
    def primary_button(self) -> QPushButton | None:
        return self._primary_button
