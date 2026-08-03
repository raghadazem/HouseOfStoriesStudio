"""TopBar — application title/subtitle, current context, theme + about buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

APP_TITLE = "House of Stories Studio"
APP_SUBTITLE_AR = "بيت الحكايات"


class TopBar(QWidget):
    theme_toggle_requested = Signal()
    about_requested = Signal()

    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFixedHeight(METRICS.topbar_height)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(METRICS.spacing_lg, 0, METRICS.spacing_lg, 0)
        layout.setSpacing(METRICS.spacing_md)

        title_column = QVBoxLayout()
        title_column.setSpacing(0)
        title_label = QLabel(APP_TITLE)
        title_label.setObjectName("appTitle")
        subtitle_label = QLabel(APP_SUBTITLE_AR)
        subtitle_label.setObjectName("appSubtitle")
        subtitle_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        title_column.addWidget(title_label)
        title_column.addWidget(subtitle_label)
        layout.addLayout(title_column)

        layout.addStretch(1)

        self._database_label = _meta_label()
        self._workspace_label = _meta_label()
        self._provider_label = _meta_label()
        layout.addWidget(self._database_label)
        layout.addWidget(_vertical_divider())
        layout.addWidget(self._workspace_label)
        layout.addWidget(_vertical_divider())
        layout.addWidget(self._provider_label)
        layout.addWidget(_vertical_divider())

        version_label = _meta_label()
        version_label.setText(f"v{version}")
        layout.addWidget(version_label)

        self._theme_button = QToolButton()
        self._theme_button.setObjectName("topBarButton")
        self._theme_button.setText("🌙")
        self._theme_button.setToolTip("Toggle light / dark theme")
        self._theme_button.clicked.connect(self.theme_toggle_requested.emit)
        layout.addWidget(self._theme_button)

        self._about_button = QToolButton()
        self._about_button.setObjectName("topBarButton")
        self._about_button.setText("ⓘ")
        self._about_button.setToolTip("About House of Stories Studio")
        self._about_button.clicked.connect(self.about_requested.emit)
        layout.addWidget(self._about_button)

    def set_database_label(self, text: str) -> None:
        self._database_label.setText(f"🗄  {text}")

    def set_workspace_label(self, text: str) -> None:
        self._workspace_label.setText(f"📁  {text}")

    def set_provider_label(self, text: str) -> None:
        self._provider_label.setText(f"🤖  {text}")

    def set_theme_icon(self, *, is_dark: bool) -> None:
        self._theme_button.setText("☀" if is_dark else "🌙")


def _meta_label() -> QLabel:
    label = QLabel()
    label.setObjectName("topBarMeta")
    return label


def _vertical_divider() -> QFrame:
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.VLine)
    divider.setFixedHeight(18)
    return divider
