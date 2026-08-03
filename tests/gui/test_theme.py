"""Theme switching: ThemeManager applies tokens, toggles, and signals the change."""

from __future__ import annotations

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS


def test_initial_theme_applies_light_by_default(qapp) -> None:
    theme = ThemeManager(qapp)
    assert theme.theme_name == "light"
    assert theme.tokens == LIGHT_TOKENS
    assert not theme.is_dark()
    assert qapp.styleSheet() != ""


def test_initial_theme_honors_requested_dark(qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="dark")
    assert theme.theme_name == "dark"
    assert theme.tokens == DARK_TOKENS
    assert theme.is_dark()


def test_unknown_theme_name_falls_back_to_default(qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="not_a_real_theme")
    assert theme.theme_name == "light"


def test_toggle_flips_between_light_and_dark(qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    assert theme.toggle() == "dark"
    assert theme.theme_name == "dark"
    assert theme.toggle() == "light"
    assert theme.theme_name == "light"


def test_theme_changed_signal_emits_on_toggle(qapp, qtbot) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    with qtbot.waitSignal(theme.theme_changed, timeout=1000) as blocker:
        theme.toggle()
    assert blocker.args == ["dark"]


def test_apply_updates_application_stylesheet(qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    light_sheet = qapp.styleSheet()
    theme.apply("dark")
    dark_sheet = qapp.styleSheet()
    assert light_sheet != dark_sheet
    assert DARK_TOKENS.background in dark_sheet
