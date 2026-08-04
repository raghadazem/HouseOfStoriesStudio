"""Sidebar navigation: clicking an item switches the central page and status text."""

from __future__ import annotations

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Episode
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


def test_review_queue_badge_shows_real_count_on_first_launch(
    qtbot, gui_context: ApplicationContext, gui_settings: AppSettings, qapp
) -> None:
    """Regression test: DashboardPage.refresh() runs once inside its own
    __init__ (so it works as a standalone widget), which is *before*
    MainWindow._wire_signals() connects review_count_updated — that first
    emission used to have no listener, leaving the sidebar badge blank
    until the user navigated away and back. MainWindow now refreshes the
    dashboard once more right after wiring, so the badge is correct from
    the very first frame."""
    with gui_context.session_scope() as session:
        episode = Episode(
            slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
        )
        session.add(episode)
        for i in range(3):
            session.add(Asset(
                asset_type=AssetType.IMAGE,
                original_filename=f"f{i}.png",
                relative_path=f"episodes/ep001/images/f{i}.png",
                checksum=str(i) * 64,
                approval_status=ApprovalStatus.DRAFT,
            ))

    window = _window(qtbot, gui_context, gui_settings, qapp)
    window.show()  # isVisible() only reflects reality once the widget chain is shown

    badge = window.sidebar._badges["review_queue"]
    assert badge.isVisible()
    assert badge.text() == "3"
