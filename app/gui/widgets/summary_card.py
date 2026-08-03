"""SummaryCard — a rounded card showing one dashboard metric."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS
from app.gui.widgets.status_badge import StatusBadge, Variant


class SummaryCard(QFrame):
    """Icon + title, a large value, and an optional subtitle/badge footer.

    ``set_value``/``set_subtitle``/``set_badge`` let the Dashboard update
    an already-built card in place (e.g. after a refresh) instead of
    rebuilding the whole card.
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
        self.setProperty("class", "card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        header = QHBoxLayout()
        header.setSpacing(METRICS.spacing_sm)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"font-size: {METRICS.font_size_lg}px;")
        header.addWidget(icon_label)
        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "cardTitle")
        header.addWidget(self._title_label)
        header.addStretch(1)
        layout.addLayout(header)

        self._value_label = QLabel(value)
        self._value_label.setProperty("class", "cardValue")
        layout.addWidget(self._value_label)

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

    def set_badge(self, text: str, variant: Variant = "neutral") -> None:
        if self._badge is None:
            self._badge = StatusBadge(text, variant)
            self._footer_layout.addWidget(self._badge)
        else:
            self._badge.set_text(text)
            self._badge.set_variant(variant)
        self._badge.setVisible(True)
