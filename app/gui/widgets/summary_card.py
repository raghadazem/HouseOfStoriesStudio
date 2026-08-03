"""SummaryCard — a rounded, hover-elevated card showing one dashboard metric.

Redesigned for the UI/UX polish pass: a larger icon in its own tinted
chip, a clearer type hierarchy (title → value → optional progress →
subtitle/badge), and the same hover-lift every card on the Dashboard
now shares via :class:`~app.gui.widgets.elevated_card.ElevatedCard`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.tokens import METRICS
from app.gui.widgets.elevated_card import ElevatedCard
from app.gui.widgets.status_badge import StatusBadge, Variant


class SummaryCard(ElevatedCard):
    """Icon chip + title, a large value, an optional progress bar, and a footer.

    ``set_value``/``set_subtitle``/``set_badge``/``set_progress`` let the
    Dashboard update an already-built card in place (e.g. on refresh)
    instead of rebuilding it.
    """

    def __init__(
        self,
        icon: str,
        title: str,
        value: str = "—",
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(148)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        header = QHBoxLayout()
        header.setSpacing(METRICS.spacing_sm)

        self._icon_chip = QLabel(icon)
        self._icon_chip.setProperty("class", "iconChip")
        self._icon_chip.setFixedSize(40, 40)
        self._icon_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._icon_chip)

        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "cardTitle")
        header.addWidget(self._title_label)
        header.addStretch(1)
        layout.addLayout(header)

        self._value_label = QLabel(value)
        self._value_label.setProperty("class", "cardValue")
        layout.addWidget(self._value_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setProperty("class", "cardProgress")
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(METRICS.spacing_sm)
        self._subtitle_label = QLabel(subtitle or "")
        self._subtitle_label.setProperty("class", "muted")
        self._subtitle_label.setVisible(bool(subtitle))
        footer.addWidget(self._subtitle_label)
        footer.addStretch(1)
        self._badge: StatusBadge | None = None
        self._footer_layout = footer
        layout.addLayout(footer)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))

    def set_progress(self, ratio: float) -> None:
        """Show a thin progress bar. ``ratio`` is clamped to [0, 1]."""
        self._progress_bar.setValue(round(max(0.0, min(1.0, ratio)) * 100))
        self._progress_bar.setVisible(True)

    def set_badge(self, text: str, variant: Variant = "neutral") -> None:
        if self._badge is None:
            self._badge = StatusBadge(text, variant)
            self._footer_layout.addWidget(self._badge)
        else:
            self._badge.set_text(text)
            self._badge.set_variant(variant)
        self._badge.setVisible(True)
