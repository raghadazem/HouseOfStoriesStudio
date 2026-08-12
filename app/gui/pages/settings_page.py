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
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core.ai.providers.elevenlabs_provider import (
    DEFAULT_MODEL as ELEVENLABS_DEFAULT_MODEL,
)
from app.core.ai.providers.elevenlabs_provider import ENV_API_KEY as ELEVENLABS_ENV_API_KEY
from app.core.ai.providers.elevenlabs_provider import ENV_MODEL as ELEVENLABS_ENV_MODEL
from app.core.ai.providers.gemini_provider import DEFAULT_MODEL, ENV_API_KEY, ENV_MODEL
from app.core.services.exceptions import ServiceError
from app.core.services.pronunciation_override_service import PronunciationOverrideService
from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import PageHeader, SectionHeader, StatusBadge, show_error
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
        layout.addWidget(self._build_gemini_section())
        layout.addWidget(self._build_elevenlabs_section())
        layout.addWidget(self._build_pronunciation_overrides_section())
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

    # --- Google Gemini Image ------------------------------------------------------

    def _build_gemini_section(self) -> QFrame:
        """Model/configuration status only — never the secret itself.

        The API key lives in the ``GEMINI_API_KEY`` environment
        variable (never the database, source, tests, or QSettings) per
        the founder's Milestone 7 secrets policy; this section shows
        whether one is present and which model is configured, with no
        editable secret field and no way to display the key's value.
        """
        card, layout = _section_card(
            "Google Gemini Image", "Real AI character-reference generation"
        )
        provider = self._ctx.ai_orchestrator.get_provider("gemini")
        configured = provider.is_configured()
        layout.addWidget(
            self._info_row(
                "Status",
                "Configured" if configured else "Not configured",
                badge_variant="success" if configured else "neutral",
            )
        )
        layout.addWidget(self._info_row("Model", provider.model))
        guidance = QLabel(
            f"Set the {ENV_API_KEY} environment variable to configure. Optionally set "
            f"{ENV_MODEL} to override the model (defaults to {DEFAULT_MODEL})."
        )
        guidance.setProperty("class", "muted")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        return card

    # --- ElevenLabs Voice --------------------------------------------------------

    def _build_elevenlabs_section(self) -> QFrame:
        """Model/configuration status only — never the secret itself.

        Exact mirror of :meth:`_build_gemini_section`'s pattern: the API
        key lives in the ``ELEVENLABS_API_KEY`` environment variable
        (never the database, source, tests, or QSettings), same policy
        as every real provider in this app. No editable secret field,
        no way to display the key's value.
        """
        card, layout = _section_card("ElevenLabs Voice", "Real AI voice-line generation")
        provider = self._ctx.ai_orchestrator.get_provider("elevenlabs")
        configured = provider.is_configured()
        # Distinct keys from the Gemini section's "Status"/"Model" --
        # self._info_values is keyed by label across the whole page, so
        # two sections sharing a bare "Status"/"Model" key would silently
        # overwrite each other's test hook entry (_info_text lookup).
        layout.addWidget(
            self._info_row(
                "Voice Status",
                "Configured" if configured else "Not configured",
                badge_variant="success" if configured else "neutral",
            )
        )
        layout.addWidget(self._info_row("Voice Model", provider.model))
        guidance = QLabel(
            f"Set the {ELEVENLABS_ENV_API_KEY} environment variable to configure. Optionally set "
            f"{ELEVENLABS_ENV_MODEL} to override the model (defaults to {ELEVENLABS_DEFAULT_MODEL})."
        )
        guidance.setProperty("class", "muted")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        return card

    # --- Pronunciation Overrides ---------------------------------------------

    def _build_pronunciation_overrides_section(self) -> QFrame:
        """A small, global term -> replacement table any future character's
        name can be added to without a source-code release — see
        ``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md``."""
        card, layout = _section_card(
            "Pronunciation Overrides", "Applied to every voice line, regardless of speaker"
        )
        self._pronunciation_list_layout = QVBoxLayout()
        layout.addLayout(self._pronunciation_list_layout)

        add_row = QHBoxLayout()
        self._pronunciation_term_field = QLineEdit()
        self._pronunciation_term_field.setPlaceholderText("Term, e.g. تورتور")
        add_row.addWidget(self._pronunciation_term_field)
        self._pronunciation_replacement_field = QLineEdit()
        self._pronunciation_replacement_field.setPlaceholderText("Replacement, e.g. طُرطُر")
        add_row.addWidget(self._pronunciation_replacement_field)
        add_button = QPushButton("+ Add")
        add_button.setProperty("class", "primary")
        add_button.clicked.connect(self._on_add_pronunciation_override)
        add_row.addWidget(add_button)
        add_wrap = QWidget()
        add_wrap.setLayout(add_row)
        layout.addWidget(add_wrap)

        self._refresh_pronunciation_overrides()
        return card

    def _refresh_pronunciation_overrides(self) -> None:
        while self._pronunciation_list_layout.count():
            item = self._pronunciation_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        with self._ctx.open_session() as session:
            overrides = PronunciationOverrideService().list_overrides(session)
            rows = [(o.id, o.term, o.replacement) for o in overrides]

        if not rows:
            self._pronunciation_list_layout.addWidget(QLabel("No overrides configured yet."))
        for override_id, term, replacement in rows:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{term} → {replacement}"), stretch=1)
            remove_button = QPushButton("Remove")
            remove_button.setProperty("class", "danger")
            remove_button.clicked.connect(
                lambda _checked=False, oid=override_id: self._on_remove_pronunciation_override(oid)
            )
            row.addWidget(remove_button)
            wrap = QWidget()
            wrap.setLayout(row)
            self._pronunciation_list_layout.addWidget(wrap)

    def _on_add_pronunciation_override(self) -> None:
        term = self._pronunciation_term_field.text().strip()
        replacement = self._pronunciation_replacement_field.text().strip()
        if not term or not replacement:
            show_error(self, "Add Pronunciation Override", "Both term and replacement are required.")
            return
        try:
            with self._ctx.session_scope() as session:
                PronunciationOverrideService().create_override(session, term=term, replacement=replacement)
        except ServiceError as err:
            show_error(self, "Add Pronunciation Override", str(err))
            return
        self._pronunciation_term_field.clear()
        self._pronunciation_replacement_field.clear()
        self._refresh_pronunciation_overrides()

    def _on_remove_pronunciation_override(self, override_id) -> None:
        try:
            with self._ctx.session_scope() as session:
                PronunciationOverrideService().remove_override(session, override_id)
        except ServiceError as err:
            show_error(self, "Remove Pronunciation Override", str(err))
            return
        self._refresh_pronunciation_overrides()

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
