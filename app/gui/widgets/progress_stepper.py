"""ProgressStepper — a horizontal "which stage are we at" workflow indicator.

Purely presentational: it renders whatever ``steps``/``current_index``
it is given. The Dashboard is the only current caller, and it derives
those from the existing ``Episode.pipeline_stage`` field (see
``app/gui/pages/dashboard_page.py::_PIPELINE_STAGE_GROUPS``) — this
widget itself has no notion of episodes, pipelines, or any domain
concept.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

_DOT_SIZE = 30


class ProgressStepper(QWidget):
    def __init__(
        self,
        steps: list[str],
        current_index: int | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.set_progress(steps, current_index)

    def set_progress(self, steps: list[str], current_index: int | None) -> None:
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

            self._layout.addWidget(self._step_widget(step, index, state), stretch=0)

    def _clear(self) -> None:
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

    @staticmethod
    def _step_widget(label_text: str, index: int, state: str) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        dot = QLabel("✓" if state == "done" else str(index + 1))
        dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setProperty("class", f"stepDot-{state}")
        column.addWidget(dot, alignment=Qt.AlignmentFlag.AlignHCenter)

        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("class", f"stepLabel-{state}")
        column.addWidget(label)

        return container
