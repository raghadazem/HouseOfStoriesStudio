"""SectionHeader — a title (+ optional subtitle, + optional trailing action widget)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS


class SectionHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        trailing: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(METRICS.spacing_md)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "sectionTitle")
        text_column.addWidget(self._title_label)

        self._subtitle_label: QLabel | None = None
        if subtitle:
            self._subtitle_label = QLabel(subtitle)
            self._subtitle_label.setProperty("class", "sectionSubtitle")
            text_column.addWidget(self._subtitle_label)

        outer.addLayout(text_column)
        outer.addStretch(1)

        if trailing is not None:
            outer.addWidget(trailing)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        if self._subtitle_label is not None:
            self._subtitle_label.setText(subtitle)
