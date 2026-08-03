"""AppLogo — a small, custom-painted brand mark. No external image asset.

A minimal geometric "house" glyph (roofline + base) on a rounded,
accent-colored badge — a literal, understated nod to "House of
Stories" rather than a storybook/cartoon illustration. Drawn with
``QPainterPath`` so it never ships a bitmap/SVG file, stays crisp at
any size, and re-colors itself automatically when the theme changes
(it reads :class:`~app.gui.theme.manager.ThemeManager` at paint time,
like ``LoadingSpinner``/``LoadingOverlay``).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.gui.theme.manager import ThemeManager


class AppLogo(QWidget):
    def __init__(self, theme: ThemeManager, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tokens = self._theme.tokens
        badge_rect = QRectF(0, 0, self._size, self._size)
        radius = self._size * 0.28

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.accent))
        painter.drawRoundedRect(badge_rect, radius, radius)

        glyph_color = QColor(tokens.text_on_accent)
        pen = QPen(glyph_color, max(1.6, self._size * 0.075))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # A simple open-book / roofline glyph: two strokes meeting at a
        # peak, plus a short "spine" — reads as both a roof (house) and
        # an open book (story) without being literally either.
        cx, cy = self._size / 2, self._size / 2
        span = self._size * 0.30
        top = cy - self._size * 0.16
        bottom = cy + self._size * 0.20

        path = QPainterPath()
        path.moveTo(QPointF(cx - span, bottom))
        path.lineTo(QPointF(cx, top))
        path.lineTo(QPointF(cx + span, bottom))
        painter.drawPath(path)

        spine_pen = QPen(glyph_color, max(1.2, self._size * 0.06))
        painter.setPen(spine_pen)
        painter.drawLine(QPointF(cx, top), QPointF(cx, bottom + self._size * 0.02))

        painter.end()
