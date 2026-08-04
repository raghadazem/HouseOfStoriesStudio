"""ElevatedCard — a themed card surface with an animated hover elevation.

Qt Style Sheets have no equivalent of CSS ``transition``/``box-shadow``,
so the "card lifts on hover" effect used throughout the Dashboard is
built with a real :class:`~PySide6.QtWidgets.QGraphicsDropShadowEffect`
whose ``blurRadius``/``yOffset`` are animated with
:class:`~PySide6.QtCore.QPropertyAnimation` on hover enter/leave — the
one place in this codebase that reaches past QSS for an animation QSS
itself cannot express.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QWidget

_RESTING_BLUR = 0
_HOVER_BLUR = 24
_RESTING_OFFSET = 0.0
_HOVER_OFFSET = 6.0
_DURATION_MS = 160


class ElevatedCard(QFrame):
    """A ``QFrame`` styled as a card (``class="card"``) that lifts on hover."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(_RESTING_BLUR)
        self._shadow.setOffset(0, _RESTING_OFFSET)
        self._shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(self._shadow)

        self._blur_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_anim.setDuration(_DURATION_MS)
        self._blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._offset_anim = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._offset_anim.setDuration(_DURATION_MS)
        self._offset_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def enterEvent(self, event) -> None:
        self.animate_hover()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.animate_resting()
        super().leaveEvent(event)

    def animate_hover(self) -> None:
        """Lift to the hover elevation. Exposed for subclasses (e.g. ``ActionCard``'s
        press/release feedback) that need to trigger the same motion outside of a
        real mouse enter/leave — see that module for why."""
        self._animate_to(_HOVER_BLUR, _HOVER_OFFSET)

    def animate_resting(self) -> None:
        """Settle back to the resting (no-shadow) elevation. See :meth:`animate_hover`."""
        self._animate_to(_RESTING_BLUR, _RESTING_OFFSET)

    def _animate_to(self, blur: float, offset: float) -> None:
        self._blur_anim.stop()
        self._blur_anim.setStartValue(self._shadow.blurRadius())
        self._blur_anim.setEndValue(blur)
        self._blur_anim.start()

        self._offset_anim.stop()
        self._offset_anim.setStartValue(self._shadow.yOffset())
        self._offset_anim.setEndValue(offset)
        self._offset_anim.start()
