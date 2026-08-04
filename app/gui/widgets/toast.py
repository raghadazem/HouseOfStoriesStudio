"""Toast + ToastHost — small non-blocking notifications for post-action feedback.

Before this pass, a successful create/approve/reject action gave the
user nothing but the list silently refreshing — only *failures* got a
visible response (a blocking ``QMessageBox`` from ``dialogs.show_error``).
A ``Toast`` is the success/info counterpart: a small, auto-dismissing,
color-coded bubble that fades in, sits in the corner for a few seconds,
and fades back out — closable early, never blocking input the way a
modal dialog does. ``ToastHost`` stacks 0+ active toasts in a window's
top-right corner and repositions itself as that window resizes.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.tokens import METRICS

Variant = Literal["success", "warning", "danger", "info"]

_VALID_VARIANTS: tuple[Variant, ...] = ("success", "warning", "danger", "info")
_ICONS: dict[str, str] = {"success": "✓", "warning": "!", "danger": "✕", "info": "i"}
_VISIBLE_MS = 4000
_FADE_MS = 200
_HOST_WIDTH = 340


class Toast(QFrame):
    """One dismissible notification bubble. Call :meth:`start` after adding it to a layout."""

    dismissed = Signal(object)  # emits self, once fully faded out

    def __init__(self, message: str, variant: Variant = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if variant not in _VALID_VARIANTS:
            variant = "info"
        self.setProperty("class", f"toast-{variant}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_sm, METRICS.spacing_xs, METRICS.spacing_sm
        )
        layout.setSpacing(METRICS.spacing_sm)

        icon = QLabel(_ICONS[variant])
        icon.setProperty("class", f"toastIcon-{variant}")
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        message_label = QLabel(message)
        message_label.setProperty("class", "toastMessage")
        message_label.setWordWrap(True)
        layout.addWidget(message_label, stretch=1)

        close_button = QPushButton("✕")
        close_button.setProperty("class", "toastClose")
        close_button.setFixedSize(20, 20)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.dismiss)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignTop)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(_FADE_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(_FADE_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(lambda: self.dismissed.emit(self))

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

    def start(self) -> None:
        self._fade_in.start()
        self._dismiss_timer.start(_VISIBLE_MS)

    def dismiss(self) -> None:
        self._dismiss_timer.stop()
        if self._fade_out.state() != QPropertyAnimation.State.Running:
            self._fade_out.start()


class ToastHost(QWidget):
    """Overlays ``anchor`` and stacks active toasts in its top-right corner."""

    def __init__(self, anchor: QWidget, *, top_offset: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent or anchor)
        self._anchor = anchor
        self._top_offset = top_offset
        self._toasts: list[Toast] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(METRICS.spacing_sm)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        anchor.installEventFilter(self)
        self._reposition()

    def eventFilter(self, watched: QWidget, event) -> bool:
        if watched is self._anchor and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self._reposition()
        return super().eventFilter(watched, event)

    def show_toast(self, message: str, variant: Variant = "info") -> None:
        toast = Toast(message, variant, parent=self)
        toast.dismissed.connect(self._on_dismissed)
        self._layout.addWidget(toast)
        self._toasts.append(toast)
        toast.show()
        self._reposition()
        self.show()
        self.raise_()
        toast.start()

    def _on_dismissed(self, toast: Toast) -> None:
        self._layout.removeWidget(toast)
        toast.setParent(None)
        toast.deleteLater()
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition()

    def _reposition(self) -> None:
        # At the app's minimum window width a flat 340px host would eat over
        # half the width and sit on top of a left-aligned page title (see
        # the narrow-window screenshot this was caught in) — shrink toward
        # a third of the anchor's width instead of staying fixed once the
        # window gets narrow; full-size at any normal desktop width.
        width = max(220, min(_HOST_WIDTH, self._anchor.width() // 3))
        self.setFixedWidth(width)
        # A fresh QWidget's sizeHint() can under-report a word-wrapped
        # child's height until its layout has actually been activated at
        # this width at least once — activate() before adjustSize() so a
        # toast added and grabbed in the same tick (e.g. screenshot
        # tooling) isn't measured as zero-height.
        self._layout.activate()
        self.adjustSize()
        x = self._anchor.width() - self.width() - METRICS.spacing_lg
        self.move(max(0, x), self._top_offset + METRICS.spacing_lg)
