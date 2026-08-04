"""PageHeader — the title bar for a top-level screen (Episodes, Characters, ...).

Distinct from :class:`~app.gui.widgets.section_header.SectionHeader`,
which titles a *sub-section* within a page (Dashboard's "Overview",
"Quick Actions"). A page only ever has one ``PageHeader``, at the very
top, optionally followed by a :class:`~app.gui.widgets.search_box.SearchBox`
+ filter row built by the page itself (screens differ too much in what
they filter by for one shared filter-bar widget to fit all of them).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


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

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(METRICS.spacing_md)

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

        outer.addLayout(text_column)
        outer.addStretch(1)

        self._primary_button: QPushButton | None = None
        if primary_label is not None:
            self._primary_button = QPushButton(primary_label)
            self._primary_button.setProperty("class", "primary")
            self._primary_button.clicked.connect(self.primary_action_triggered.emit)
            outer.addWidget(self._primary_button)

    def set_subtitle(self, subtitle: str) -> None:
        if self._subtitle_label is not None:
            self._subtitle_label.setText(subtitle)

    def set_primary_enabled(self, enabled: bool) -> None:
        if self._primary_button is not None:
            self._primary_button.setEnabled(enabled)

    @property
    def primary_button(self) -> QPushButton | None:
        return self._primary_button
