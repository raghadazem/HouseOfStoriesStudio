"""Tests for the UI/UX-polish widgets: AppLogo, ElevatedCard, ProgressStepper,
ActionCard, and the activity-timeline log parser.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt

from app.gui.theme.manager import ThemeManager
from app.gui.widgets.action_card import ActionCard
from app.gui.widgets.activity_timeline import (
    ActivityTimeline,
    format_relative_time,
    parse_log_line,
)
from app.gui.widgets.app_logo import AppLogo
from app.gui.widgets.elevated_card import ElevatedCard
from app.gui.widgets.progress_stepper import ProgressStepper
from app.gui.widgets.summary_card import SummaryCard

# --- AppLogo --------------------------------------------------------------------


def test_app_logo_constructs_at_requested_size(qtbot, theme: ThemeManager) -> None:
    logo = AppLogo(theme, size=40)
    qtbot.addWidget(logo)
    assert logo.size().width() == 40
    assert logo.size().height() == 40


def test_app_logo_paints_without_error_in_both_themes(qtbot, qapp) -> None:
    for theme_name in ("light", "dark"):
        theme = ThemeManager(qapp, initial_theme=theme_name)
        logo = AppLogo(theme)
        qtbot.addWidget(logo)
        logo.show()
        logo.grab()  # forces a real paintEvent(); must not raise


# --- ElevatedCard -----------------------------------------------------------------


def test_elevated_card_has_card_class_and_shadow(qtbot) -> None:
    card = ElevatedCard()
    qtbot.addWidget(card)
    assert card.property("class") == "card"
    assert card.graphicsEffect() is not None


def test_elevated_card_hover_animates_shadow_toward_elevated(qtbot) -> None:
    card = ElevatedCard()
    qtbot.addWidget(card)
    card._animate_to(24, 6.0)
    assert card._blur_anim.endValue() == 24
    assert card._offset_anim.endValue() == 6.0

    card._animate_to(0, 0.0)
    assert card._blur_anim.endValue() == 0
    assert card._offset_anim.endValue() == 0.0


# --- SummaryCard.set_progress (new in the polish pass) -----------------------------


def test_summary_card_progress_bar_hidden_by_default(qtbot) -> None:
    card = SummaryCard("📋", "Production Tasks")
    qtbot.addWidget(card)
    assert not card._progress_bar.isVisible()


def test_summary_card_set_progress_shows_and_sets_value(qtbot) -> None:
    card = SummaryCard("📋", "Production Tasks")
    qtbot.addWidget(card)
    card.show()

    card.set_progress(0.4)

    assert card._progress_bar.isVisible()
    assert card._progress_bar.value() == 40


def test_summary_card_set_progress_clamps_out_of_range_values(qtbot) -> None:
    card = SummaryCard("📋", "Production Tasks")
    qtbot.addWidget(card)
    card.set_progress(-0.5)
    assert card._progress_bar.value() == 0
    card.set_progress(1.5)
    assert card._progress_bar.value() == 100


# --- ProgressStepper ----------------------------------------------------------------


def test_progress_stepper_builds_one_widget_per_step(qtbot) -> None:
    steps = ["Script", "Storyboard", "Images", "Voice", "Video", "SEO", "Upload"]
    stepper = ProgressStepper(steps, current_index=2)
    qtbot.addWidget(stepper)

    # 7 step widgets + 6 connectors between them = 13 layout items
    assert stepper._layout.count() == 13


def test_progress_stepper_marks_done_current_and_upcoming_correctly(qtbot) -> None:
    steps = ["A", "B", "C"]
    stepper = ProgressStepper(steps, current_index=1)
    qtbot.addWidget(stepper)

    # item 0 = step "A" (done), item 1 = connector, item 2 = step "B" (current), ...
    step_a = stepper._layout.itemAt(0).widget()
    step_b = stepper._layout.itemAt(2).widget()
    step_c = stepper._layout.itemAt(4).widget()

    def dot_class(step_widget) -> str:
        # the dot QLabel is the first child in the step's own QVBoxLayout
        return step_widget.layout().itemAt(0).widget().property("class")

    assert dot_class(step_a) == "stepDot-done"
    assert dot_class(step_b) == "stepDot-current"
    assert dot_class(step_c) == "stepDot-upcoming"


def test_progress_stepper_none_index_marks_everything_upcoming(qtbot) -> None:
    stepper = ProgressStepper(["A", "B"], current_index=None)
    qtbot.addWidget(stepper)
    step_a = stepper._layout.itemAt(0).widget()
    assert step_a.layout().itemAt(0).widget().property("class") == "stepDot-upcoming"


def test_progress_stepper_set_progress_rebuilds_without_leaking_old_widgets(qtbot) -> None:
    stepper = ProgressStepper(["A", "B", "C"], current_index=0)
    qtbot.addWidget(stepper)
    assert stepper._layout.count() == 5  # 3 steps + 2 connectors

    stepper.set_progress(["A", "B", "C"], current_index=2)

    # Rebuilding must not accumulate widgets from the previous render.
    assert stepper._layout.count() == 5


# --- ActionCard -----------------------------------------------------------------------


def test_action_card_emits_clicked_on_mouse_press(qtbot) -> None:
    card = ActionCard("✨", "Run Mock AI", "Generate a test thumbnail")
    qtbot.addWidget(card)

    with qtbot.waitSignal(card.clicked, timeout=1000):
        qtbot.mousePress(card, Qt.MouseButton.LeftButton)


# --- Activity log parsing --------------------------------------------------------------


def test_parse_log_line_handles_a_plain_info_line() -> None:
    entry = parse_log_line("2026-08-03 12:00:00 | INFO     | house_of_stories.gui | hello world")
    assert entry is not None
    assert entry.icon == "ℹ️"
    assert entry.title == "hello world"
    assert entry.timestamp == datetime(2026, 8, 3, 12, 0, 0)  # noqa: DTZ001 - naive, see activity_timeline.py


def test_parse_log_line_handles_seed_lines() -> None:
    entry = parse_log_line("2026-08-03 12:00:00 | INFO     | house_of_stories.seed | Seed data ready")
    assert entry is not None
    assert entry.icon == "🌱"


def test_parse_log_line_handles_warning_and_error_levels() -> None:
    warning = parse_log_line("2026-08-03 12:00:00 | WARNING  | house_of_stories.x | careful")
    error = parse_log_line("2026-08-03 12:00:00 | ERROR    | house_of_stories.x | broken")
    assert warning is not None and warning.icon == "⚠️"
    assert error is not None and error.icon == "❌"


def test_parse_log_line_describes_successful_generation_attempt() -> None:
    line = (
        '2026-08-03 12:00:00 | INFO     | house_of_stories.ai_generation | '
        'generation_attempt {"workflow_name": "thumbnail", "provider_name": "mock_provider", '
        '"outcome": "success"}'
    )
    entry = parse_log_line(line)
    assert entry is not None
    assert entry.icon == "✨"
    assert entry.title == "Generated thumbnail via mock_provider"


def test_parse_log_line_describes_failed_generation_attempt() -> None:
    line = (
        '2026-08-03 12:00:00 | WARNING  | house_of_stories.ai_generation | '
        'generation_attempt {"workflow_name": "thumbnail", "provider_name": "mock_provider", '
        '"outcome": "failure", "error_category": "ConflictError"}'
    )
    entry = parse_log_line(line)
    assert entry is not None
    assert entry.icon == "⚠️"
    assert "ConflictError" in entry.title


def test_parse_log_line_returns_none_for_malformed_lines() -> None:
    assert parse_log_line("not a real log line") is None
    assert parse_log_line("") is None


def test_format_relative_time_buckets() -> None:
    now = datetime.now()  # noqa: DTZ005 - naive, matches format_relative_time's own naive `now()`
    assert format_relative_time(None) == ""
    assert format_relative_time(now) == "just now"
    assert format_relative_time(now - timedelta(minutes=5)) == "5m ago"
    assert format_relative_time(now - timedelta(hours=3)) == "3h ago"
    assert format_relative_time(now - timedelta(days=2)) == "2d ago"


def test_activity_timeline_set_entries_updates_entries_property(qtbot) -> None:
    timeline = ActivityTimeline()
    qtbot.addWidget(timeline)
    entries = [parse_log_line("2026-08-03 12:00:00 | INFO     | x | hello")]

    timeline.set_entries(entries)

    assert timeline.entries == entries
    assert timeline._layout.count() == 1


def test_activity_timeline_set_entries_twice_does_not_accumulate_rows(qtbot) -> None:
    timeline = ActivityTimeline()
    qtbot.addWidget(timeline)
    first = [parse_log_line("2026-08-03 12:00:00 | INFO     | x | one")]
    second = [
        parse_log_line("2026-08-03 12:00:00 | INFO     | x | one"),
        parse_log_line("2026-08-03 12:01:00 | INFO     | x | two"),
    ]

    timeline.set_entries(first)
    timeline.set_entries(second)

    assert timeline._layout.count() == 2
