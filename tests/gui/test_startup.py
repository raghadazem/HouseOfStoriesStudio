"""Application startup: the shell constructs and shows without error."""

from __future__ import annotations

from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.windows.main_window import MainWindow
from app.gui.windows.top_bar import APP_TITLE


def test_main_window_constructs_and_shows(qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)

    window.show()

    assert window.isVisible()
    assert window.windowTitle() == APP_TITLE


def test_main_window_has_all_shell_regions(qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)

    assert window.top_bar is not None
    assert window.sidebar is not None
    assert window.stack is not None
    assert window.statusBar() is not None
    assert window.stack.count() == 7  # one page per sidebar item


def test_dashboard_is_the_initial_page(qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)

    assert window.stack.currentWidget() is window.dashboard_page
