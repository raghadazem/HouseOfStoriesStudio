"""Status bar: shows database, provider, workspace, and current application state."""

from __future__ import annotations

from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.windows.main_window import MainWindow


def _window(qtbot, gui_context, gui_settings, qapp) -> MainWindow:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)
    return window


def test_status_bar_shows_database_name(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert gui_context.database_label in window._status_database.text()


def test_status_bar_shows_workspace_path(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert gui_context.workspace_label in window._status_workspace.text()


def test_status_bar_shows_ai_provider(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert "mock_provider" in window._status_provider.text()


def test_status_bar_state_starts_as_ready(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert window._status_state.text() == "Ready"


def test_status_bar_state_updates_on_navigation(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    window.sidebar.button_for("characters").click()
    assert window._status_state.text() == "Viewing Characters"


def test_set_state_updates_label_directly(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    window.set_state("Custom state")
    assert window._status_state.text() == "Custom state"


def test_top_bar_mirrors_status_bar_context(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert gui_context.database_label in window.top_bar._database_label.text()
    assert "mock_provider" in window.top_bar._provider_label.text()
