"""Design tokens: the only place a color, spacing, or radius value is a literal.

Every widget in ``app/gui`` reads colors through :class:`ThemeTokens`
(via :class:`~app.gui.theme.manager.ThemeManager`) instead of writing a
hex code — this is what "do not hardcode colors throughout widgets"
means in practice. Spacing/radius/typography live in :class:`Metrics`,
shared by both themes (only color changes between light and dark).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    """Named colors for one theme (light or dark). Every value is a `#rrggbb(aa)` string."""

    name: str

    # Surfaces
    background: str
    surface: str
    surface_alt: str
    border: str

    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_accent: str

    # Brand / accent
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # a tinted accent background — icon chips, the "current" step dot

    # Status colors — used by StatusBadge and summary-card indicators
    success: str
    warning: str
    danger: str
    info: str

    # Sidebar (kept distinct from `surface` — usually a touch darker/lighter
    # than the main content area, like Notion/Figma's side rail)
    sidebar_background: str
    sidebar_text: str
    sidebar_text_muted: str
    sidebar_selected_background: str
    sidebar_selected_text: str

    # Overlays
    overlay: str  # semi-transparent scrim, e.g. behind LoadingOverlay
    shadow: str


LIGHT_TOKENS = ThemeTokens(
    name="light",
    background="#F5F6F8",
    surface="#FFFFFF",
    surface_alt="#F0F1F4",
    border="#E2E4E9",
    text_primary="#1F2430",
    text_secondary="#5B6270",
    text_muted="#9AA0AC",
    text_on_accent="#FFFFFF",
    accent="#6C5CE7",
    accent_hover="#7D6EF0",
    accent_pressed="#5B4BD6",
    accent_soft="#EFECFD",
    success="#2FB380",
    warning="#E8A93B",
    danger="#E5594F",
    info="#3E8EDE",
    sidebar_background="#1F2430",
    sidebar_text="#D7DAE3",
    sidebar_text_muted="#8B90A0",
    sidebar_selected_background="#332F52",
    sidebar_selected_text="#FFFFFF",
    overlay="rgba(20, 22, 30, 0.45)",
    shadow="rgba(31, 36, 48, 0.12)",
)

DARK_TOKENS = ThemeTokens(
    name="dark",
    background="#15171F",
    surface="#1D2029",
    surface_alt="#242833",
    border="#30333F",
    text_primary="#EDEFF4",
    text_secondary="#B0B4C1",
    text_muted="#767B8A",
    text_on_accent="#FFFFFF",
    accent="#8A7CF0",
    accent_hover="#9A8DF5",
    accent_pressed="#7566E0",
    accent_soft="#292447",
    success="#3FCB98",
    warning="#F0B94F",
    danger="#F0685E",
    info="#5AA2ED",
    sidebar_background="#0F1116",
    sidebar_text="#D7DAE3",
    sidebar_text_muted="#767B8A",
    sidebar_selected_background="#2A2745",
    sidebar_selected_text="#FFFFFF",
    overlay="rgba(0, 0, 0, 0.55)",
    shadow="rgba(0, 0, 0, 0.35)",
)

THEMES: dict[str, ThemeTokens] = {
    LIGHT_TOKENS.name: LIGHT_TOKENS,
    DARK_TOKENS.name: DARK_TOKENS,
}

DEFAULT_THEME_NAME = "light"


@dataclass(frozen=True)
class Metrics:
    """Spacing/radius/typography shared by every theme."""

    spacing_xs: int = 4
    spacing_sm: int = 8
    spacing_md: int = 16
    spacing_lg: int = 24
    spacing_xl: int = 32

    radius_sm: int = 8
    radius_md: int = 12
    radius_lg: int = 16

    font_family: str = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
    font_size_sm: int = 11
    font_size_base: int = 13
    font_size_md: int = 15
    font_size_lg: int = 21
    font_size_xl: int = 28

    sidebar_width: int = 232
    topbar_height: int = 64


METRICS = Metrics()
