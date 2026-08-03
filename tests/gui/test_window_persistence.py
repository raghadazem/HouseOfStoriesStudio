"""Window persistence: geometry (size/position/maximized) survives a save/restore round trip."""

from __future__ import annotations

from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.windows.main_window import MainWindow


def test_no_saved_geometry_uses_default_size(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)

    assert window.size().width() == 1440
    assert window.size().height() == 900


def test_geometry_round_trips_through_settings(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    # Kept within the offscreen test platform's 800x800 virtual screen —
    # restoreGeometry() clamps a window to fit its available screen, so a
    # larger size here would be constrained by the test environment, not
    # by the code under test.
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)
    window.resize(700, 500)
    window.move(20, 30)
    qtbot.wait(20)

    gui_settings.save_window_geometry(window.saveGeometry())

    restored_geometry = gui_settings.load_window_geometry()
    assert restored_geometry is not None

    second_window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(second_window)

    assert second_window.size().width() == 700
    assert second_window.size().height() == 500


def test_close_event_persists_geometry(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    theme = ThemeManager(qapp, initial_theme="light")
    window = MainWindow(gui_context, theme, gui_settings)
    qtbot.addWidget(window)
    window.resize(1111, 777)

    assert gui_settings.load_window_geometry() is None
    window.close()

    assert gui_settings.load_window_geometry() is not None
