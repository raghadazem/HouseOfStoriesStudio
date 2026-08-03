"""StatusBadge — a small colored pill label (success/warning/danger/info/neutral)."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

Variant = Literal["success", "warning", "danger", "info", "neutral"]

_VALID_VARIANTS: tuple[Variant, ...] = ("success", "warning", "danger", "info", "neutral")


class StatusBadge(QLabel):
    """A pill-shaped status indicator. Color comes entirely from the active theme's QSS."""

    def __init__(self, text: str, variant: Variant = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_variant(variant)

    def set_variant(self, variant: Variant) -> None:
        if variant not in _VALID_VARIANTS:
            variant = "neutral"
        self.setProperty("class", f"badge-{variant}")
        self._repolish()

    def set_text(self, text: str) -> None:
        self.setText(text)

    def _repolish(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
