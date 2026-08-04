"""ProgressStepper — a horizontal "which stage are we at" workflow indicator.

Purely presentational: it renders whatever ``steps``/``current_index``
(and optional per-step ``icons``) it is given. The Dashboard is the
only current caller, and it derives those from the existing
``Episode.pipeline_stage`` field (see
``app/gui/pages/dashboard_page.py::_STAGE_TO_STEP_INDEX``) — this
widget itself has no notion of episodes, pipelines, or any domain
concept.

v2 polish: each step can carry its own icon (a clearer visual identity
per stage than a bare number), and the current step's dot pulses with
a soft, looping glow so it "stands out immediately" without stealing
attention — see ``docs/24_UI_UX_POLISH_V2_STATUS.md`` §2.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.theme.manager import ThemeManager

_DOT_SIZE = 32
_PULSE_MIN_BLUR = 6
_PULSE_MAX_BLUR = 22
_PULSE_DURATION_MS = 1100


class ProgressStepper(QWidget):
    def __init__(
        self,
        steps: list[str],
        current_index: int | None,
        icons: list[str] | None = None,
        theme: ThemeManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._pulse_animations: list[QPropertyAnimation] = []
        self.set_progress(steps, current_index, icons)

    def set_progress(
        self, steps: list[str], current_index: int | None, icons: list[str] | None = None
    ) -> None:
        self._clear()
        for index, step in enumerate(steps):
            if current_index is None:
                state = "upcoming"
            elif index < current_index:
                state = "done"
            elif index == current_index:
                state = "current"
            else:
                state = "upcoming"

            if index > 0:
                connector = QWidget()
                connector.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                connector.setFixedHeight(2)
                connector.setProperty(
                    "class",
                    "stepConnectorDone" if index <= (current_index or -1) else "stepConnectorUpcoming",
                )
                self._layout.addWidget(connector, stretch=1)

            icon = icons[index] if icons and index < len(icons) else None
            self._layout.addWidget(self._step_widget(step, index, state, icon), stretch=0)

    def _clear(self) -> None:
        for anim in self._pulse_animations:
            anim.stop()
        self._pulse_animations.clear()
        # `deleteLater()` alone isn't enough here: it only schedules the
        # C++ object's destruction on the next event-loop pass, but a
        # widget just `takeAt()`'d out of its layout keeps its last
        # geometry and stays visible until then — reparenting it away
        # immediately (`setParent(None)`) is what actually stops it from
        # being painted, which matters because `set_progress()` can be
        # called again (from DashboardPage.refresh()) before the event
        # loop gets a turn, which without this left the *previous*
        # render's dots/labels visibly overlapping the new ones.
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _step_widget(self, label_text: str, index: int, state: str, icon: str | None) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        if state == "done":
            dot_text = "✓"
        elif icon:
            dot_text = icon
        else:
            dot_text = str(index + 1)

        dot = QLabel(dot_text)
        dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setProperty("class", f"stepDot-{state}")
        column.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)

        if state == "current":
            self._attach_pulse(dot)

        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("class", f"stepLabel-{state}")
        column.addWidget(label)

        return container

    def _attach_pulse(self, dot: QLabel) -> None:
        """A soft, looping glow on the current stage's dot — real motion,
        not just a static highlight, so "in progress" reads immediately."""
        accent = QColor(self._theme.tokens.accent if self._theme else "#6C5CE7")
        glow = QGraphicsDropShadowEffect(dot)
        glow.setColor(accent)
        glow.setOffset(0, 0)
        glow.setBlurRadius(_PULSE_MIN_BLUR)
        dot.setGraphicsEffect(glow)

        animation = QPropertyAnimation(glow, b"blurRadius", dot)
        animation.setDuration(_PULSE_DURATION_MS)
        animation.setStartValue(_PULSE_MIN_BLUR)
        animation.setKeyValueAt(0.5, _PULSE_MAX_BLUR)
        animation.setEndValue(_PULSE_MIN_BLUR)
        animation.setLoopCount(-1)
        animation.start()
        self._pulse_animations.append(animation)
