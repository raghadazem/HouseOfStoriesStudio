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
        font-size: {m.font_size_md}px;
        font-weight: 600;
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

    /* --- Sidebar -------------------------------------------------------- */
    QWidget#sidebar {{
        background: {t.sidebar_background};
        border-right: 1px solid {t.border};
    }}
    QPushButton[class="sidebarButton"] {{
        text-align: left;
        padding: 10px 16px;
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
        font-size: {m.font_size_sm}px;
        padding: 12px 16px 4px 16px;
        letter-spacing: 1px;
    }}

    /* --- Cards / surfaces ------------------------------------------------ */
    QFrame[class="card"] {{
        background: {t.surface};
        border: 1px solid {t.border};
        border-radius: {m.radius_lg}px;
    }}
    QLabel[class="sectionTitle"] {{
        font-size: {m.font_size_lg}px;
        font-weight: 600;
        color: {t.text_primary};
    }}
    QLabel[class="sectionSubtitle"] {{
        font-size: {m.font_size_base}px;
        color: {t.text_secondary};
    }}
    QLabel[class="cardTitle"] {{
        font-size: {m.font_size_base}px;
        color: {t.text_secondary};
    }}
    QLabel[class="cardValue"] {{
        font-size: {m.font_size_xl}px;
        font-weight: 700;
        color: {t.text_primary};
    }}
    QLabel[class="muted"] {{
        color: {t.text_muted};
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
    """
