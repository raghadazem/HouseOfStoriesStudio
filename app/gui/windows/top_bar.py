"""TopBar — application branding (primary) + current context (secondary).

UI/UX polish pass: branding (the logo mark + title/subtitle) is now the
dominant visual element; database/workspace/provider/version are
consolidated into a single small, muted line instead of three
separate labeled fields with icons and dividers — still fully visible,
just no longer competing with the brand for attention. The same
information remains available, unabridged, in the status bar (see
``app/gui/windows/main_window.py``), which is where a "technical
details" reader would look first anyway.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets.app_logo import AppLogo

APP_TITLE = "House of Stories Studio"
APP_SUBTITLE_AR = "بيت الحكايات"


class TopBar(QWidget):
    theme_toggle_requested = Signal()
    about_requested = Signal()

    def __init__(self, version: str, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._version = version
        self.setObjectName("topBar")
        self.setFixedHeight(METRICS.topbar_height)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(METRICS.spacing_lg, 0, METRICS.spacing_lg, 0)
        layout.setSpacing(METRICS.spacing_md)

        layout.addWidget(AppLogo(theme))

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

        self._meta_label = QLabel()
        self._meta_label.setObjectName("topBarMeta")
        layout.addWidget(self._meta_label)

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

        self._database = ""
        self._workspace = ""
        self._provider = ""

    def set_database_label(self, text: str) -> None:
        self._database = text
        self._refresh_meta()

    def set_workspace_label(self, text: str) -> None:
        self._workspace = text
        self._refresh_meta()

    def set_provider_label(self, text: str) -> None:
        self._provider = text
        self._refresh_meta()

    def _refresh_meta(self) -> None:
        parts = [p for p in (self._database, self._workspace, self._provider) if p]
        parts.append(f"v{self._version}")
        self._meta_label.setText("  ·  ".join(parts))

    def set_theme_icon(self, *, is_dark: bool) -> None:
        self._theme_button.setText("☀" if is_dark else "🌙")
