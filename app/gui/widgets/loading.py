"""LoadingSpinner + LoadingOverlay — reusable "work in progress" indicators.

No external asset (gif/png) — the spinner is a small custom-painted
rotating arc, so it can pick up the active theme's accent color without
shipping per-theme image files.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS

_TICK_MS = 40
_STEP_DEGREES = 12


class LoadingSpinner(QWidget):
    """A small rotating arc. Call :meth:`start`/:meth:`stop`."""

    def __init__(self, theme: ThemeManager | None = None, size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._angle = 0
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._timer.start(_TICK_MS)
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle + _STEP_DEGREES) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._theme.tokens.accent if self._theme else "#6C5CE7")
        pen = QPen(color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        margin = 3
        rect = QRectF(margin, margin, self._size - 2 * margin, self._size - 2 * margin)
        painter.drawArc(rect, self._angle * 16, 120 * 16)
        painter.end()


class LoadingOverlay(QWidget):
    """Covers its parent with a semi-transparent scrim + centered spinner + message."""

    def __init__(
        self, parent: QWidget, theme: ThemeManager | None = None, message: str = "Working…"
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(METRICS.spacing_sm)

        self._spinner = LoadingSpinner(theme, parent=self)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self._message_label = QLabel(message)
        self._message_label.setStyleSheet("color: white; font-weight: 600;")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._message_label)

        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        overlay_color = QColor(self._theme.tokens.overlay if self._theme else "rgba(0,0,0,0.45)")
        painter.fillRect(self.rect(), overlay_color)
        painter.end()

    def set_message(self, message: str) -> None:
        self._message_label.setText(message)

    def start(self, message: str | None = None) -> None:
        if message is not None:
            self.set_message(message)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._spinner.start()

    def stop(self) -> None:
        self._spinner.stop()
        self.hide()
