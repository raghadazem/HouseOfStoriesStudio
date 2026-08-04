"""EntityCard — one clickable grid tile for a card-grid screen (Characters, Assets).

Same accessibility rationale as :class:`~app.gui.widgets.entity_row.EntityRow`
(built as a ``QPushButton``, not a ``QFrame`` + mouse handler) and the
same read-only-trailing-content-only rule — see that module's docstring.

Supports either an emoji/icon-chip glyph (the common case — Characters
have no real portrait) or a real thumbnail image (``set_thumbnail``,
used by the Assets grid to show the actual imported file where one
exists on disk).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_THUMB_SIZE = 96


class EntityCard(QPushButton):
    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "entityCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(220)
        self.setMinimumWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        self._thumb_label = QLabel(icon)
        self._thumb_label.setProperty("class", "entityCardThumb")
        self._thumb_label.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setScaledContents(False)
        layout.addWidget(self._thumb_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "entityCardTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._subtitle_label = QLabel(subtitle or "")
        self._subtitle_label.setProperty("class", "entityCardSubtitle")
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self._subtitle_label)

        layout.addStretch(1)

        self._trailing_layout = QHBoxLayout()
        self._trailing_layout.setSpacing(METRICS.spacing_xs)
        self._trailing_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._trailing_layout)

    def add_trailing_widget(self, widget: QWidget) -> None:
        self._trailing_layout.addWidget(widget)

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._subtitle_label.setText(text)
        self._subtitle_label.setVisible(bool(text))

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        """Show a real image instead of the default icon-chip glyph."""
        self._thumb_label.setProperty("class", "entityCardThumb-image")
        self._thumb_label.setPixmap(
            pixmap.scaled(
                _THUMB_SIZE,
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._thumb_label.setStyleSheet(f"border-radius: {METRICS.radius_md}px;")
        self.style().unpolish(self._thumb_label)
        self.style().polish(self._thumb_label)
