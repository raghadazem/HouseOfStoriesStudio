"""render_nav_icon — a small set of custom-painted, minimal line-art glyphs for the sidebar.

Sidebar navigation is the one piece of chrome that's visible on every
screen, in every state, for the whole session — the highest-leverage
place to replace mixed emoji rendering (which looks different per
platform/font) with one deliberately consistent icon system. Drawn the
same way as :class:`~app.gui.widgets.app_logo.AppLogo` (``QPainterPath``,
no image asset), so every icon shares the same stroke weight and reads
as one family.

Card/action icons elsewhere in the app still use emoji — see
``docs/24_UI_UX_POLISH_V2_STATUS.md`` §8 for why building a full custom
icon set for every icon in the app (20+) was judged out of scope for a
polish pass, while the 7 sidebar icons (highest visibility, always
on-screen) were judged worth the investment.

Renders to a :class:`~PySide6.QtGui.QIcon` (not a live custom widget)
specifically so ``Sidebar`` can keep using plain, checkable
``QPushButton``s — preserving their built-in keyboard focus/activation
behavior — while still getting a custom vector glyph via
``QPushButton.setIcon()``.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GLYPHS: tuple[str, ...] = (
    "dashboard", "episodes", "characters", "assets", "prompts", "review_queue", "settings",
)


def render_nav_icon(glyph: str, color: QColor | str, size: int = 18) -> QIcon:
    if glyph not in GLYPHS:
        raise ValueError(f"Unknown nav icon glyph {glyph!r}. Expected one of {GLYPHS}.")

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.4, size * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    _DRAW_FUNCTIONS[glyph](painter, size)
    painter.end()
    return QIcon(pixmap)


def _canvas(size: int, margin_ratio: float = 0.14) -> QRectF:
    margin = size * margin_ratio
    return QRectF(margin, margin, size - 2 * margin, size - 2 * margin)


def _draw_dashboard(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    gap = rect.width() * 0.18
    cell = (rect.width() - gap) / 2
    for row in range(2):
        for col in range(2):
            x = rect.left() + col * (cell + gap)
            y = rect.top() + row * (cell + gap)
            painter.drawRoundedRect(QRectF(x, y, cell, cell), cell * 0.25, cell * 0.25)


def _draw_episodes(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    painter.drawRoundedRect(rect, rect.width() * 0.18, rect.width() * 0.18)
    cx, cy = rect.center().x(), rect.center().y()
    w, h = rect.width() * 0.28, rect.height() * 0.34
    triangle = QPainterPath()
    triangle.moveTo(QPointF(cx - w * 0.4, cy - h))
    triangle.lineTo(QPointF(cx - w * 0.4, cy + h))
    triangle.lineTo(QPointF(cx + w * 0.7, cy))
    triangle.closeSubpath()
    painter.drawPath(triangle)


def _draw_characters(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    head_d = rect.width() * 0.42
    head_rect = QRectF(rect.center().x() - head_d / 2, rect.top(), head_d, head_d)
    painter.drawEllipse(head_rect)

    shoulders = QPainterPath()
    top_y = rect.top() + head_d * 1.15
    shoulders.moveTo(QPointF(rect.left(), rect.bottom()))
    shoulders.quadTo(
        QPointF(rect.center().x(), top_y),
        QPointF(rect.right(), rect.bottom()),
    )
    painter.drawPath(shoulders)


def _draw_assets(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    painter.drawRoundedRect(rect, rect.width() * 0.16, rect.width() * 0.16)
    sun_center = QPointF(rect.left() + rect.width() * 0.28, rect.top() + rect.height() * 0.3)
    sun_radius = rect.width() * 0.11
    painter.drawEllipse(sun_center, sun_radius, sun_radius)

    mountains = QPainterPath()
    mountains.moveTo(QPointF(rect.left(), rect.bottom() - rect.height() * 0.15))
    mountains.lineTo(QPointF(rect.left() + rect.width() * 0.38, rect.top() + rect.height() * 0.45))
    mountains.lineTo(QPointF(rect.left() + rect.width() * 0.62, rect.bottom() - rect.height() * 0.3))
    mountains.lineTo(QPointF(rect.left() + rect.width() * 0.8, rect.top() + rect.height() * 0.6))
    mountains.lineTo(QPointF(rect.right(), rect.bottom() - rect.height() * 0.15))
    painter.drawPath(mountains)


def _draw_prompts(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    body = QPainterPath()
    body.moveTo(QPointF(rect.left(), rect.bottom()))
    body.lineTo(QPointF(rect.right() - rect.width() * 0.18, rect.top()))
    painter.drawPath(body)

    tip = QPainterPath()
    tip.moveTo(QPointF(rect.left(), rect.bottom()))
    tip.lineTo(QPointF(rect.left() + rect.width() * 0.22, rect.bottom() - rect.height() * 0.08))
    painter.drawPath(tip)

    nib = QPainterPath()
    nib.moveTo(QPointF(rect.right() - rect.width() * 0.28, rect.top() + rect.height() * 0.18))
    nib.lineTo(QPointF(rect.right(), rect.top() + rect.height() * 0.42))
    painter.drawPath(nib)


def _draw_review_queue(painter: QPainter, size: int) -> None:
    rect = _canvas(size)
    painter.drawRoundedRect(rect, rect.width() * 0.22, rect.width() * 0.22)
    check = QPainterPath()
    check.moveTo(QPointF(rect.left() + rect.width() * 0.24, rect.center().y()))
    check.lineTo(QPointF(rect.center().x() - rect.width() * 0.05, rect.bottom() - rect.height() * 0.28))
    check.lineTo(QPointF(rect.right() - rect.width() * 0.18, rect.top() + rect.height() * 0.28))
    painter.drawPath(check)


def _draw_settings(painter: QPainter, size: int) -> None:
    rect = _canvas(size, margin_ratio=0.22)
    center = rect.center()
    radius = rect.width() / 2
    painter.drawEllipse(center, radius, radius)
    painter.drawEllipse(center, radius * 0.32, radius * 0.32)

    tick_length = radius * 0.45
    for i in range(8):
        angle = math.radians(i * 45)
        inner = QPointF(
            center.x() + math.cos(angle) * (radius + tick_length * 0.25),
            center.y() + math.sin(angle) * (radius + tick_length * 0.25),
        )
        outer = QPointF(
            center.x() + math.cos(angle) * (radius + tick_length),
            center.y() + math.sin(angle) * (radius + tick_length),
        )
        painter.drawLine(inner, outer)


_DRAW_FUNCTIONS: dict[str, Callable[[QPainter, int], None]] = {
    "dashboard": _draw_dashboard,
    "episodes": _draw_episodes,
    "characters": _draw_characters,
    "assets": _draw_assets,
    "prompts": _draw_prompts,
    "review_queue": _draw_review_queue,
    "settings": _draw_settings,
}
