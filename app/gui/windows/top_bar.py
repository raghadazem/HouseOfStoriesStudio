"""TopBar — application branding (primary) + current production context.

v2 polish: the header now focuses on the studio and what's actually in
production — the current episode and its stage, plus the workspace
name — instead of raw technical fields. Database file, full workspace
path, AI provider, and app version are still available in full, just
one click away behind a small "Details" toggle
(:class:`_DiagnosticsPopover`) rather than sitting in the header by
default. The same details also remain in the status bar. See
``docs/24_UI_UX_POLISH_V2_STATUS.md`` §4.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets.app_logo import AppLogo

APP_TITLE = "House of Stories Studio"
APP_SUBTITLE_AR = "بيت الحكايات"

_DIAGNOSTICS_ROWS: tuple[tuple[str, str], ...] = (
    ("database", "Database"),
    ("workspace", "Workspace"),
    ("provider", "AI Provider"),
    ("version", "Version"),
)


class _DiagnosticsPopover(QFrame):
    """The technical details, one click away instead of always-on in the header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # Real window flags (not just a plain child widget) — a plain
        # child gets clipped to its parent's rect, and TopBar is only
        # ``topbar_height`` tall, which cut this popover down to a
        # sliver. ``parent`` is kept only as the transient-parent/owner
        # for stacking, not as a clipping ancestor.
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("diagnosticsPopover")
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_sm)

        self._values: dict[str, QLabel] = {}
        for key, caption_text in _DIAGNOSTICS_ROWS:
            row = QVBoxLayout()
            row.setSpacing(1)
            caption = QLabel(caption_text)
            caption.setProperty("class", "diagnosticsLabel")
            row.addWidget(caption)
            value = QLabel("—")
            value.setProperty("class", "diagnosticsValue")
            value.setWordWrap(True)
            row.addWidget(value)
            layout.addLayout(row)
            self._values[key] = value

        self.hide()

    def set_value(self, key: str, text: str) -> None:
        if key in self._values:
            self._values[key].setText(text)


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

        self._episode_chip = QLabel("No active episode")
        self._episode_chip.setProperty("class", "episodeChip")
        layout.addWidget(self._episode_chip)

        self._diagnostics_button = QToolButton()
        self._diagnostics_button.setProperty("class", "diagnosticsToggle")
        self._diagnostics_button.setText("Details  ▾")
        self._diagnostics_button.setToolTip("Database, workspace, AI provider, version")
        self._diagnostics_button.clicked.connect(self._toggle_diagnostics)
        layout.addWidget(self._diagnostics_button)

        self._diagnostics = _DiagnosticsPopover(self)
        self._diagnostics.set_value("version", f"v{version}")

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

    # --- content ------------------------------------------------------------------

    def set_current_episode(self, title: str | None, stage_label: str | None) -> None:
        if not title:
            self._episode_chip.setText("No active episode")
            return
        self._episode_chip.setText(f"🎬 {title}" + (f"  ·  {stage_label}" if stage_label else ""))

    def set_database_label(self, text: str) -> None:
        self._diagnostics.set_value("database", text)

    def set_workspace_label(self, text: str) -> None:
        self._diagnostics.set_value("workspace", text)

    def set_provider_label(self, text: str) -> None:
        self._diagnostics.set_value("provider", text)

    def set_theme_icon(self, *, is_dark: bool) -> None:
        self._theme_button.setText("☀" if is_dark else "🌙")

    # --- diagnostics popover --------------------------------------------------------

    def _toggle_diagnostics(self) -> None:
        if self._diagnostics.isVisible():
            self._diagnostics.hide()
            return
        anchor = self._diagnostics_button.mapToGlobal(self._diagnostics_button.rect().bottomRight())
        self._diagnostics.move(anchor.x() - self._diagnostics.width(), anchor.y() + 6)
        self._diagnostics.show()
        self._diagnostics.raise_()
