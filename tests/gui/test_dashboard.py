"""Dashboard loading: real counts from services, empty states, and quick actions."""

from __future__ import annotations

import pytest

from app.core.db.enums import ApprovalStatus, AssetType, PipelineStage
from app.core.models import Asset, Character, Episode
from app.gui.context import ApplicationContext
from app.gui.pages.dashboard_page import DashboardPage
from app.gui.theme.manager import ThemeManager


@pytest.fixture()
def dashboard(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> DashboardPage:
    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    return page


def test_dashboard_shows_empty_state_on_fresh_database(dashboard: DashboardPage) -> None:
    # Start == target == 0 for every card on a fresh database, so
    # set_value_animated resolves instantly (no animation to wait out).
    assert dashboard._episodes_card._value_label.text() == "0"
    assert dashboard._episodes_card._caption_label.text() == "No episodes yet"
    assert dashboard._characters_card._value_label.text() == "0"
    assert dashboard._assets_card._value_label.text() == "0"
    assert dashboard._review_card._value_label.text() == "0"
    assert dashboard._activity_empty.isVisible()
    assert not dashboard._activity_timeline.isVisible()
    assert dashboard._progress_empty.isVisible()


def test_dashboard_shows_real_counts_after_seeding(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        episode = Episode(
            slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
        )
        character = Character(slug="melissa", name_ar="م", name_en="Melissa")
        asset = Asset(
            asset_type=AssetType.IMAGE,
            original_filename="f.png",
            relative_path="episodes/ep001/images/f.png",
            checksum="a" * 64,
            approval_status=ApprovalStatus.DRAFT,
        )
        session.add_all([episode, character, asset])

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)

    # Values now count up from 0, so wait out the animation instead of
    # asserting the label text synchronously.
    qtbot.waitUntil(lambda: page._episodes_card._value_label.text() == "1", timeout=1500)
    qtbot.waitUntil(lambda: page._characters_card._value_label.text() == "1", timeout=1500)
    qtbot.waitUntil(lambda: page._assets_card._value_label.text() == "1", timeout=1500)
    qtbot.waitUntil(lambda: page._review_card._value_label.text() == "1", timeout=1500)


def test_dashboard_ai_card_shows_mock_provider(dashboard: DashboardPage) -> None:
    assert dashboard._ai_card._subtitle_label.text() == "via mock_provider"
    assert dashboard._ai_card._badge is not None
    assert dashboard._ai_card._badge.text() == "Configured"


def test_open_episode_001_shows_not_found_dialog_when_none_exists(
    dashboard: DashboardPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.gui.pages.dashboard_page.show_info",
        lambda _parent, title, message: calls.append((title, message)),
    )

    dashboard._on_open_episode_001()

    assert len(calls) == 1
    assert "No Episode #1" in calls[0][1]


def test_open_episode_001_shows_real_episode_details(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(
                slug="ep001_test", number=1, title_ar="ع", title_en="My Episode", lesson="Sharing"
            )
        )

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.gui.pages.dashboard_page.show_info",
        lambda _parent, title, message: calls.append((title, message)),
    )

    page._on_open_episode_001()

    assert calls[0][0] == "My Episode"
    assert "Sharing" in calls[0][1]


def test_create_episode_and_import_asset_show_not_implemented(
    dashboard: DashboardPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.gui.pages.dashboard_page.show_not_implemented",
        lambda _parent, feature: calls.append(feature),
    )

    dashboard._on_create_episode()
    dashboard._on_import_asset()

    assert calls == ["Create Episode", "Import Asset"]


def test_run_mock_ai_creates_a_draft_asset(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
        )

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)

    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.gui.pages.dashboard_page.show_info",
        lambda _parent, title, message: info_calls.append((title, message)),
    )

    page._on_run_mock_ai()

    assert len(info_calls) == 1
    assert "Generated a new draft asset" in info_calls[0][1]
    with gui_context.open_session() as session:
        assert session.query(Asset).count() == 1


def test_run_mock_ai_twice_shows_deterministic_conflict_message(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
        )

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)

    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.gui.pages.dashboard_page.show_info",
        lambda _parent, title, message: info_calls.append((title, message)),
    )

    page._on_run_mock_ai()
    page._on_run_mock_ai()

    assert len(info_calls) == 2
    assert "deterministic" in info_calls[1][1]
    with gui_context.open_session() as session:
        assert session.query(Asset).count() == 1  # second run did not create a duplicate


def test_open_review_queue_emits_navigate_signal(dashboard: DashboardPage, qtbot) -> None:
    with qtbot.waitSignal(dashboard.navigate_requested, timeout=1000) as blocker:
        dashboard._on_open_review_queue()
    assert blocker.args == ["review_queue"]


def test_recent_activity_shows_log_lines_once_something_was_logged(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    gui_context.logger.info("a real activity line for the dashboard to display")

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()
    page.refresh()

    assert page._activity_timeline.isVisible()
    assert not page._activity_empty.isVisible()
    assert len(page._activity_timeline.entries) >= 1
    assert "a real activity line" in page._activity_timeline.entries[0].title


def test_production_progress_panel_reflects_episode_pipeline_stage(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(
                slug="ep001_test", number=1, title_ar="ع", title_en="My Episode",
                lesson="Sharing", pipeline_stage=PipelineStage.STORYBOARD,
            )
        )

    page = DashboardPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    assert not page._progress_empty.isVisible()
    assert page._progress_stepper.isVisible()
    assert "My Episode" in page._progress_header._subtitle_label.text()
    assert "Storyboard" in page._progress_header._subtitle_label.text()
    # PipelineStage.STORYBOARD maps to step index 1 ("Storyboard") — that
    # step's dot should be "current", the step before it "done".
    script_dot = page._progress_stepper._layout.itemAt(0).widget().layout().itemAt(0).widget()
    storyboard_dot = page._progress_stepper._layout.itemAt(2).widget().layout().itemAt(0).widget()
    assert script_dot.property("class") == "stepDot-done"
    assert storyboard_dot.property("class") == "stepDot-current"
