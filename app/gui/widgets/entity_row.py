"""EntityRow — one clickable list row for a list-style screen (Episodes, Prompts, ...).

Built as a ``QPushButton`` (empty native text, everything drawn via a
child layout) rather than a ``QFrame`` + ``mousePressEvent`` override —
the same accessibility-first choice documented on
``app/gui/widgets/nav_icon.py``: a real ``QPushButton`` gets keyboard
focus, Tab order, and Enter/Space activation for free, which a custom
mouse-only click handler does not.

Deliberately holds only *read-only* trailing content (a label, a
:class:`~app.gui.widgets.status_badge.StatusBadge`) — never another
interactive widget. Qt does not cleanly support a clickable child
inside a ``QPushButton``, so a row that needs its own inline action
buttons (Review Queue's Approve/Reject) is built directly with a
``QFrame`` instead of this widget. See ``docs/25_MILESTONE_4B_STATUS.md``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


class EntityRow(QPushButton):
    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "entityRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_sm, METRICS.spacing_md, METRICS.spacing_sm
        )
        layout.setSpacing(METRICS.spacing_md)

        self._icon_label = QLabel(icon)
        self._icon_label.setProperty("class", "iconChip")
        self._icon_label.setFixedSize(40, 40)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "entityRowTitle")
        text_column.addWidget(self._title_label)
        self._subtitle_label = QLabel(subtitle or "")
        self._subtitle_label.setProperty("class", "entityRowSubtitle")
        self._subtitle_label.setVisible(bool(subtitle))
        text_column.addWidget(self._subtitle_label)
        layout.addLayout(text_column, stretch=1)

        self._trailing_layout = QHBoxLayout()
        self._trailing_layout.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._trailing_layout)

    def add_trailing_widget(self, widget: QWidget) -> None:
        self._trailing_layout.addWidget(widget)

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle_label.setText(text)
        self._subtitle_label.setVisible(bool(text))

    def set_icon_glyph(self, icon: str) -> None:
        self._icon_label.setText(icon)
