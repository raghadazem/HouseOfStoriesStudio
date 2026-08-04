"""SettingsPage — preferences, workspace/database diagnostics, and about.

Every value here is either a real, currently-persisted preference
(``AppSettings``' theme, the same one the top bar's toggle button
already writes) or a read-only fact read straight from ``AppConfig``/
``AIOrchestrator`` — nothing here is a setting that looks editable but
doesn't actually persist anywhere.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import PageHeader, SectionHeader, StatusBadge
from app.gui.windows.top_bar import APP_SUBTITLE_AR, APP_TITLE

_MODALITIES: tuple[tuple[str, str], ...] = (
    ("image", "Image generation"),
    ("video", "Video generation"),
    ("voice", "Voice synthesis"),
    ("song", "Music/song generation"),
    ("text", "Text generation"),
)


def _section_card(title: str, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("class", "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(
        METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_lg
    )
    layout.setSpacing(METRICS.spacing_sm)
    layout.addWidget(SectionHeader(title, subtitle))
    return card, layout


class SettingsPage(QWidget):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._ctx = ctx
        self._theme = theme
        self._settings = settings
        self._info_values: dict[str, QLabel] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_lg, METRICS.spacing_xl, METRICS.spacing_xl
        )
        layout.setSpacing(METRICS.spacing_lg)

        layout.addWidget(PageHeader("Settings", "Preferences, workspace, and diagnostics"))

        layout.addWidget(self._build_appearance_section())
        layout.addWidget(self._build_workspace_section())
        layout.addWidget(self._build_providers_section())
        layout.addWidget(self._build_about_section())
        layout.addStretch(1)

        self._theme.theme_changed.connect(self._on_theme_changed)

    # --- info rows (shared by Workspace/Providers/About) ------------------------

    def _info_row(self, label: str, value: str, *, badge_variant: str | None = None) -> QWidget:
        row = QHBoxLayout()
        row.setSpacing(METRICS.spacing_sm)
        caption = QLabel(label)
        caption.setProperty("class", "formLabel")
        caption.setFixedWidth(160)
        row.addWidget(caption)
        value_label: QLabel = StatusBadge(value, badge_variant) if badge_variant else QLabel(value)
        if badge_variant is None:
            value_label.setWordWrap(True)
        row.addWidget(value_label, stretch=1 if badge_variant is None else 0)
        row.addStretch(1)
        self._info_values[label] = value_label
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _info_text(self, label: str) -> str:
        """Test hook: the current displayed value for a given row's label."""
        return self._info_values[label].text()

    # --- Appearance ----------------------------------------------------------

    def _build_appearance_section(self) -> QFrame:
        card, layout = _section_card("Appearance", "Applies instantly across the whole app")

        row = QHBoxLayout()
        self._theme_label = QLabel()
        row.addWidget(self._theme_label, stretch=1)
        self._theme_button = QPushButton()
        self._theme_button.setProperty("class", "primary")
        self._theme_button.clicked.connect(self._on_toggle_theme)
        row.addWidget(self._theme_button)
        row_wrap = QWidget()
        row_wrap.setLayout(row)
        layout.addWidget(row_wrap)

        self._update_theme_labels()
        return card

    def _update_theme_labels(self) -> None:
        is_dark = self._theme.is_dark()
        self._theme_label.setText(f"Current theme: {'Dark' if is_dark else 'Light'}")
        self._theme_button.setText("Switch to Light" if is_dark else "Switch to Dark")

    def _on_toggle_theme(self) -> None:
        new_theme = self._theme.toggle()
        self._settings.save_theme(new_theme)

    def _on_theme_changed(self, _theme_name: str) -> None:
        self._update_theme_labels()

    # --- Workspace & Database --------------------------------------------------

    def _build_workspace_section(self) -> QFrame:
        card, layout = _section_card("Workspace & Database", "Where this studio's files live")
        config = self._ctx.config
        layout.addWidget(self._info_row("Project root", str(config.project_root)))
        layout.addWidget(self._info_row("Production folder", str(config.production_dir)))
        layout.addWidget(self._info_row("Data folder", str(config.data_dir)))
        layout.addWidget(self._info_row("Database file", str(config.db_path)))
        layout.addWidget(self._info_row("Log folder", str(config.log_dir)))
        layout.addWidget(self._info_row("Log level", config.log_level))
        return card

    # --- AI Providers ------------------------------------------------------------

    def _build_providers_section(self) -> QFrame:
        card, layout = _section_card("AI Providers", "What's configured for each generation type")
        for modality, label in _MODALITIES:
            providers = self._ctx.ai_orchestrator.list_available_providers(modality)
            text = ", ".join(providers) if providers else "Not configured"
            variant = "success" if providers else "neutral"
            layout.addWidget(self._info_row(label, text, badge_variant=variant))
        return card

    # --- About ------------------------------------------------------------------

    def _build_about_section(self) -> QFrame:
        card, layout = _section_card("About")
        title = QLabel(f"{APP_TITLE}  ·  {APP_SUBTITLE_AR}")
        title.setProperty("class", "entityRowTitle")
        layout.addWidget(title)
        layout.addWidget(self._info_row("Version", __version__))
        description = QLabel(
            "A production-management desktop app for an Arabic children's YouTube studio."
        )
        description.setProperty("class", "muted")
        description.setWordWrap(True)
        layout.addWidget(description)
        return card
