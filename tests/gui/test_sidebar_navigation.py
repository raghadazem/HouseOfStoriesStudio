"""Sidebar navigation: clicking an item switches the central page and status text."""

from __future__ import annotations

from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.widgets.placeholder_page import PlaceholderPage
from app.gui.windows.main_window import MainWindow
from app.gui.windows.sidebar import NAV_ITEMS


def _window(qtbot, gui_context, gui_settings, qapp) -> MainWindow:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)
    return window


def test_sidebar_has_all_seven_nav_items(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    assert {item.key for item in NAV_ITEMS} == {
        "dashboard", "episodes", "characters", "assets", "prompts", "review_queue", "settings",
    }
    for item in NAV_ITEMS:
        assert window.sidebar.button_for(item.key) is not None


def test_clicking_dashboard_shows_dashboard_page(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    window.sidebar.button_for("episodes").click()

    window.sidebar.button_for("dashboard").click()

    assert window.stack.currentWidget() is window.dashboard_page
    assert window._status_state.text() == "Viewing Dashboard"


def test_clicking_unimplemented_item_shows_placeholder_page(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)

    window.sidebar.button_for("episodes").click()

    assert isinstance(window.stack.currentWidget(), PlaceholderPage)
    assert window._status_state.text() == "Viewing Episodes"


def test_every_non_dashboard_item_is_a_placeholder(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    for item in NAV_ITEMS:
        if item.key == "dashboard":
            continue
        window.sidebar.button_for(item.key).click()
        assert isinstance(window.stack.currentWidget(), PlaceholderPage)


def test_sidebar_selection_is_exclusive(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    window = _window(qtbot, gui_context, gui_settings, qapp)
    window.sidebar.button_for("characters").click()

    checked = [item.key for item in NAV_ITEMS if window.sidebar.button_for(item.key).isChecked()]
    assert checked == ["characters"]
