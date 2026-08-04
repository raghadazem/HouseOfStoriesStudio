"""Tests for SettingsPage: real theme toggle, workspace/database facts, providers."""

from __future__ import annotations

from app import __version__
from app.gui.context import ApplicationContext
from app.gui.pages.settings_page import SettingsPage
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager


def test_shows_current_theme(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)
    assert "Light" in page._theme_label.text()
    assert page._theme_button.text() == "Switch to Dark"


def test_toggle_theme_updates_theme_manager_and_persists_setting(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    page._on_toggle_theme()

    assert theme.theme_name == "dark"
    assert gui_settings.load_theme() == "dark"
    assert "Dark" in page._theme_label.text()
    assert page._theme_button.text() == "Switch to Light"


def test_theme_changed_elsewhere_updates_this_pages_labels(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    """The label must stay in sync even when the theme is toggled from
    somewhere else (e.g. the top bar's own toggle button)."""
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    theme.toggle()

    assert "Dark" in page._theme_label.text()


def test_shows_real_workspace_paths(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert str(gui_context.config.db_path) in page._info_text("Database file")


def test_shows_app_version_in_about_section(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert __version__ in page._info_text("Version")


def test_shows_mock_provider_as_configured(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert "mock_provider" in page._info_text("Image generation")
