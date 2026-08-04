"""ThemeManager — applies a :class:`~app.gui.theme.tokens.ThemeTokens` set to the app.

The single place that turns design tokens into an actual Qt stylesheet.
Widgets never write ``setStyleSheet("color: #...")`` themselves; they
either rely on this global stylesheet (via object/property selectors)
or, for custom-painted widgets (e.g. a status dot), read
``ThemeManager.tokens`` at paint time and listen to
:attr:`ThemeManager.theme_changed` to repaint when the theme flips.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.gui.theme.tokens import DEFAULT_THEME_NAME, METRICS, THEMES, Metrics, ThemeTokens


class ThemeManager(QObject):
    """Owns the current theme, applies it to the whole ``QApplication``."""

    theme_changed = Signal(str)  # emits the new theme name

    def __init__(self, app: QApplication, *, initial_theme: str = DEFAULT_THEME_NAME) -> None:
        super().__init__()
        self._app = app
        self._theme_name = initial_theme if initial_theme in THEMES else DEFAULT_THEME_NAME
        self.metrics: Metrics = METRICS
        self.apply(self._theme_name)

    @property
    def theme_name(self) -> str:
        return self._theme_name

    @property
    def tokens(self) -> ThemeTokens:
        return THEMES[self._theme_name]

    def is_dark(self) -> bool:
        return self._theme_name == "dark"

    def toggle(self) -> str:
        """Flip between light and dark. Returns the new theme name."""
        next_name = "dark" if self._theme_name == "light" else "light"
        self.apply(next_name)
        return next_name

    def apply(self, theme_name: str) -> None:
        if theme_name not in THEMES:
            theme_name = DEFAULT_THEME_NAME
        self._theme_name = theme_name
        self._app.setStyleSheet(_build_stylesheet(THEMES[theme_name], METRICS))
        self.theme_changed.emit(theme_name)


def _build_stylesheet(t: ThemeTokens, m: Metrics) -> str:
    return f"""
    * {{
        font-family: {m.font_family};
        font-size: {m.font_size_base}px;
        color: {t.text_primary};
    }}

    QMainWindow, QWidget#centralArea, QWidget#dashboardPage, QWidget#scrollContent,
    QScrollArea, QScrollArea > QWidget {{
        background: {t.background};
    }}

    QScrollArea {{ border: none; }}

    /* --- Top bar ------------------------------------------------------ */
    QWidget#topBar {{
        background: {t.surface};
        border-bottom: 1px solid {t.border};
    }}
    QLabel#appTitle {{
        font-size: {m.font_size_lg}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QLabel#appSubtitle {{
        font-size: {m.font_size_base}px;
        color: {t.text_secondary};
    }}
    QLabel#topBarMeta {{
        font-size: {m.font_size_sm}px;
        color: {t.text_muted};
    }}
    QToolButton#topBarButton {{
        background: transparent;
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 6px 10px;
        color: {t.text_secondary};
    }}
    QToolButton#topBarButton:hover {{
        background: {t.surface_alt};
        color: {t.text_primary};
    }}
    QLabel[class="episodeChip"] {{
        color: {t.text_secondary};
        font-size: {m.font_size_base}px;
        font-weight: 500;
    }}
    QToolButton[class="diagnosticsToggle"] {{
        background: transparent;
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 4px 10px;
        color: {t.text_muted};
        font-size: {m.font_size_sm}px;
    }}
    QToolButton[class="diagnosticsToggle"]:hover {{
        background: {t.surface_alt};
        color: {t.text_secondary};
    }}
    QFrame#diagnosticsPopover {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_md}px;
    }}
    QLabel[class="diagnosticsLabel"] {{
        color: {t.text_muted};
        font-size: {m.font_size_xs}px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    QLabel[class="diagnosticsValue"] {{
        color: {t.text_secondary};
        font-size: {m.font_size_sm}px;
    }}

    /* --- Sidebar -------------------------------------------------------- */
    QWidget#sidebar {{
        background: {t.sidebar_background};
        border-right: 1px solid {t.border};
    }}
    QPushButton[class="sidebarButton"] {{
        text-align: left;
        padding: 10px 14px 10px 18px;
        border: none;
        border-radius: {m.radius_sm}px;
        color: {t.sidebar_text};
        background: transparent;
        font-size: {m.font_size_base}px;
    }}
    QPushButton[class="sidebarButton"]:hover {{
        background: rgba(255, 255, 255, 0.06);
    }}
    QPushButton[class="sidebarButton"]:checked {{
        background: {t.sidebar_selected_background};
        color: {t.sidebar_selected_text};
        font-weight: 600;
    }}
    QLabel#sidebarSectionLabel {{
        color: {t.sidebar_text_muted};
        font-size: {m.font_size_xs}px;
        padding: 14px 18px 4px 18px;
        letter-spacing: 1.2px;
        font-weight: 600;
    }}
    QFrame[class="sidebarSeparator"] {{
        background: rgba(255, 255, 255, 0.08);
        max-height: 1px;
        min-height: 1px;
        margin: 8px 18px;
    }}
    QFrame#sidebarIndicator {{
        background: {t.accent};
        border-radius: 2px;
    }}
    QLabel[class="sidebarBadge"] {{
        background: {t.danger};
        color: {t.text_on_accent};
        border-radius: 9px;
        font-size: {m.font_size_xs}px;
        font-weight: 700;
        padding: 0px 5px;
    }}

    /* --- Cards / surfaces ------------------------------------------------ */
    QFrame[class="card"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_lg}px;
    }}
    QFrame[class="card-hero"] {{
        background: {t.surface};
        border: 1px solid {t.accent};
        border-radius: {m.radius_lg}px;
    }}
    QLabel[class="sectionTitle"] {{
        font-size: {m.font_size_lg}px;
        font-weight: 700;
        color: {t.text_primary};
        letter-spacing: -0.2px;
    }}
    QLabel[class="sectionSubtitle"] {{
        font-size: {m.font_size_base}px;
        color: {t.text_secondary};
    }}
    QLabel[class="cardTitle"] {{
        font-size: {m.font_size_base}px;
        font-weight: 500;
        color: {t.text_secondary};
    }}
    QLabel[class="cardValue"] {{
        font-size: {m.font_size_xl}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QLabel[class="cardValue-hero"] {{
        font-size: {m.font_size_xxl}px;
        font-weight: 800;
        color: {t.text_primary};
        letter-spacing: -0.5px;
    }}
    QLabel[class="cardCaption"] {{
        font-size: {m.font_size_sm}px;
        font-weight: 500;
        color: {t.accent};
    }}
    QLabel[class="muted"] {{
        color: {t.text_muted};
        font-size: {m.font_size_base}px;
    }}
    QLabel[class="iconChip"] {{
        background: {t.accent_soft};
        border-radius: 12px;
        font-size: {m.font_size_lg}px;
    }}
    QLabel[class="iconChip-hero"] {{
        background: {t.accent_soft};
        border-radius: 14px;
        font-size: {m.font_size_xl}px;
    }}

    /* --- Card progress bar (SummaryCard) ------------------------------------ */
    QProgressBar[class="cardProgress"] {{
        background: {t.surface_alt};
        border: none;
        border-radius: 3px;
    }}
    QProgressBar[class="cardProgress"]::chunk {{
        background: {t.accent};
        border-radius: 3px;
    }}

    /* --- Action cards (Quick Actions panel) --------------------------------- */
    QFrame[class="actionCard"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_lg}px;
    }}
    QFrame[class="actionCard"]:hover {{
        border: 1px solid {t.accent};
        background: {t.accent_soft};
    }}
    QLabel[class="actionCardTitle"] {{
        font-size: {m.font_size_base}px;
        font-weight: 600;
        color: {t.text_primary};
    }}
    QLabel[class="actionCardDescription"] {{
        font-size: {m.font_size_sm}px;
        color: {t.text_muted};
    }}

    /* --- Production progress stepper --------------------------------------- */
    QLabel[class="stepDot-done"] {{
        background: {t.success};
        color: {t.text_on_accent};
        border-radius: 16px;
        font-weight: 700;
        font-size: {m.font_size_md}px;
    }}
    QLabel[class="stepDot-current"] {{
        background: {t.accent};
        color: {t.text_on_accent};
        border-radius: 16px;
        font-weight: 700;
        font-size: {m.font_size_md}px;
        border: 2px solid {t.accent_hover};
    }}
    QLabel[class="stepDot-upcoming"] {{
        background: {t.surface_alt};
        color: {t.text_muted};
        border-radius: 16px;
        font-weight: 600;
        font-size: {m.font_size_md}px;
        border: 1px solid {t.border};
    }}
    QLabel[class="stepLabel-done"], QLabel[class="stepLabel-current"] {{
        color: {t.text_primary};
        font-size: {m.font_size_sm}px;
        font-weight: 600;
    }}
    QLabel[class="stepLabel-upcoming"] {{
        color: {t.text_muted};
        font-size: {m.font_size_sm}px;
    }}
    QWidget[class="stepConnectorDone"] {{ background: {t.accent}; }}
    QWidget[class="stepConnectorUpcoming"] {{ background: {t.border}; }}

    /* --- Activity timeline --------------------------------------------------- */
    QWidget[class="activityRow"] {{
        border-radius: {m.radius_sm}px;
        background: transparent;
    }}
    QWidget[class="activityRow"]:hover {{
        background: {t.surface_alt};
    }}
    QLabel[class="activityIcon"] {{
        font-size: {m.font_size_md}px;
    }}
    QLabel[class="activityTitle"] {{
        color: {t.text_primary};
        font-size: {m.font_size_base}px;
    }}

    /* --- Buttons ---------------------------------------------------------- */
    QPushButton {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 8px 14px;
        color: {t.text_primary};
    }}
    QPushButton:hover {{ background: {t.surface_alt}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton[class="primary"] {{
        background: {t.accent};
        border: 1px solid {t.accent};
        color: {t.text_on_accent};
        font-weight: 600;
    }}
    QPushButton[class="primary"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[class="primary"]:pressed {{ background: {t.accent_pressed}; }}

    /* --- Inputs ------------------------------------------------------------- */
    QLineEdit {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 6px 10px;
        color: {t.text_primary};
        selection-background-color: {t.accent};
    }}
    QLineEdit:focus {{ border: 1px solid {t.accent}; }}

    /* --- Status badge ------------------------------------------------------- */
    QLabel[class="badge-success"], QLabel[class="badge-warning"],
    QLabel[class="badge-danger"], QLabel[class="badge-info"], QLabel[class="badge-neutral"] {{
        border-radius: {m.radius_sm}px;
        padding: 2px 10px;
        font-size: {m.font_size_sm}px;
        font-weight: 600;
    }}
    QLabel[class="badge-success"] {{ background: {t.success}; color: {t.text_on_accent}; }}
    QLabel[class="badge-warning"] {{ background: {t.warning}; color: {t.text_on_accent}; }}
    QLabel[class="badge-danger"]  {{ background: {t.danger};  color: {t.text_on_accent}; }}
    QLabel[class="badge-info"]    {{ background: {t.info};    color: {t.text_on_accent}; }}
    QLabel[class="badge-neutral"] {{ background: {t.surface_alt}; color: {t.text_secondary}; border: 1px solid {t.border}; }}

    /* --- Status bar ---------------------------------------------------------- */
    QStatusBar {{
        background: {t.surface};
        border-top: 1px solid {t.border};
        color: {t.text_secondary};
    }}
    QStatusBar QLabel {{
        color: {t.text_secondary};
        font-size: {m.font_size_sm}px;
        padding: 0 8px;
    }}

    /* --- Lists / activity ------------------------------------------------------ */
    QListWidget {{
        background: transparent;
        border: none;
    }}
    QListWidget::item {{
        padding: 6px 4px;
        color: {t.text_secondary};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.border};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t.border};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

    /* --- Milestone 4B: page header ------------------------------------------ */
    QLabel[class="pageTitle"] {{
        font-size: {m.font_size_xl}px;
        font-weight: 800;
        color: {t.text_primary};
        letter-spacing: -0.3px;
    }}
    QLabel[class="pageSubtitle"] {{
        font-size: {m.font_size_base}px;
        color: {t.text_secondary};
    }}

    /* --- Milestone 4B: entity rows (Episodes, Prompts, Review Queue) -------- */
    QPushButton[class="entityRow"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_md}px;
        text-align: left;
        padding: 0px;
    }}
    QPushButton[class="entityRow"]:hover {{
        border: 1px solid {t.accent};
        background: {t.accent_soft};
    }}
    QPushButton[class="entityRow"]:focus {{
        border: 1px solid {t.accent};
        outline: none;
    }}
    QLabel[class="entityRowTitle"] {{
        font-size: {m.font_size_base}px;
        font-weight: 600;
        color: {t.text_primary};
    }}
    QLabel[class="entityRowSubtitle"] {{
        font-size: {m.font_size_sm}px;
        color: {t.text_muted};
    }}

    /* --- Milestone 4B: entity cards (Characters, Assets grids) -------------- */
    QPushButton[class="entityCard"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_lg}px;
        text-align: left;
        padding: 0px;
    }}
    QPushButton[class="entityCard"]:hover {{
        border: 1px solid {t.accent};
        background: {t.accent_soft};
    }}
    QPushButton[class="entityCard"]:focus {{
        border: 1px solid {t.accent};
        outline: none;
    }}
    QLabel[class="entityCardThumb"] {{
        background: {t.accent_soft};
        border-radius: {m.radius_md}px;
        font-size: 36px;
    }}
    QLabel[class="entityCardThumb-image"] {{
        border-radius: {m.radius_md}px;
    }}
    QLabel[class="entityCardTitle"] {{
        font-size: {m.font_size_base}px;
        font-weight: 600;
        color: {t.text_primary};
    }}
    QLabel[class="entityCardSubtitle"] {{
        font-size: {m.font_size_sm}px;
        color: {t.text_muted};
    }}

    /* --- Milestone 4B: plain (non-clickable) rows — Review Queue ------------ */
    QFrame[class="reviewRow"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_md}px;
    }}
    QPushButton[class="danger"] {{
        background: transparent;
        border: 1px solid {t.danger};
        color: {t.danger};
        font-weight: 600;
    }}
    QPushButton[class="danger"]:hover {{ background: {t.danger}; color: {t.text_on_accent}; }}

    /* --- Milestone 4B: dialogs / forms --------------------------------------- */
    QDialog {{
        background: {t.background};
    }}
    QLabel[class="dialogTitle"] {{
        font-size: {m.font_size_lg}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QLabel[class="formLabel"] {{
        font-size: {m.font_size_sm}px;
        font-weight: 600;
        color: {t.text_secondary};
    }}
    QLabel[class="formError"] {{
        color: {t.danger};
        font-size: {m.font_size_sm}px;
        font-weight: 500;
    }}
    QWidget#formDialogScroll, QScrollArea#formDialogScroll > QWidget {{
        background: transparent;
    }}

    /* --- Milestone 4B: form inputs -------------------------------------------- */
    QComboBox {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 6px 10px;
        color: {t.text_primary};
    }}
    QComboBox:focus {{ border: 1px solid {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        selection-background-color: {t.accent_soft};
        selection-color: {t.text_primary};
        outline: none;
        padding: 4px;
    }}
    QTextEdit, QPlainTextEdit {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 6px 10px;
        color: {t.text_primary};
        selection-background-color: {t.accent};
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {t.accent}; }}
    QSpinBox {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_sm}px;
        padding: 4px 8px;
        color: {t.text_primary};
    }}
    QSpinBox:focus {{ border: 1px solid {t.accent}; }}
    QCheckBox {{
        color: {t.text_primary};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t.border};
        border-radius: 4px;
        background: {t.surface};
    }}
    QCheckBox::indicator:checked {{
        background: {t.accent};
        border: 1px solid {t.accent};
    }}
    """
