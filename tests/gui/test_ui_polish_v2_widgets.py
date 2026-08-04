"""Tests for the v2 UI/UX-polish pass: SummaryCard's hero/caption/animated-value
API, ProgressStepper's per-step icons and pulse effect, the sidebar's custom
nav-icon renderer, grouping/badge, and the TopBar diagnostics popover.

See docs/24_UI_UX_POLISH_V2_STATUS.md for the design rationale.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from app.gui.theme.manager import ThemeManager
from app.gui.widgets.nav_icon import GLYPHS, render_nav_icon
from app.gui.widgets.progress_stepper import ProgressStepper
from app.gui.widgets.summary_card import SummaryCard
from app.gui.windows.sidebar import NAV_ITEMS, Sidebar
from app.gui.windows.top_bar import TopBar

# --- SummaryCard: hero variant ----------------------------------------------------


def test_summary_card_hero_uses_bigger_chip_and_hero_classes(qtbot) -> None:
    card = SummaryCard("🤖", "AI Studio", hero=True)
    qtbot.addWidget(card)

    assert card.property("class") == "card-hero"
    assert card._value_label.property("class") == "cardValue-hero"
    assert card._icon_chip.property("class") == "iconChip-hero"
    assert card._icon_chip.size().width() == 48


def test_summary_card_non_hero_uses_regular_classes(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)

    assert card.property("class") == "card"
    assert card._value_label.property("class") == "cardValue"
    assert card._icon_chip.size().width() == 40


# --- SummaryCard.set_caption --------------------------------------------------------


def test_summary_card_caption_hidden_until_set(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    assert not card._caption_label.isVisible()


def test_summary_card_set_caption_shows_real_text(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    card.show()

    card.set_caption("3 in production")

    assert card._caption_label.text() == "3 in production"
    assert card._caption_label.isVisible()

    card.set_caption("")
    assert not card._caption_label.isVisible()


# --- SummaryCard.set_value_animated -------------------------------------------------


def test_set_value_animated_resolves_instantly_when_start_equals_target(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    card.set_value_animated(0)  # "—" is treated as 0 -> 0 == 0, no animation needed
    assert card._value_label.text() == "0"


def test_set_value_animated_eventually_reaches_target(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)

    card.set_value_animated(7)

    qtbot.waitUntil(lambda: card._value_label.text() == "7", timeout=1500)


def test_set_value_animated_replaces_a_running_animation(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)

    card.set_value_animated(100)
    first_anim = card._value_anim
    card.set_value_animated(3)  # should stop the first animation, not stack

    assert card._value_anim is not first_anim
    qtbot.waitUntil(lambda: card._value_label.text() == "3", timeout=1500)


# --- ProgressStepper: per-step icons -------------------------------------------------


def test_progress_stepper_shows_icon_for_current_and_upcoming_steps(qtbot) -> None:
    steps = ["Script", "Storyboard", "Images"]
    icons = ["📝", "🧩", "🖼️"]
    stepper = ProgressStepper(steps, current_index=1, icons=icons)
    qtbot.addWidget(stepper)

    step_a = stepper._layout.itemAt(0).widget()  # done -> checkmark, not its icon
    step_b = stepper._layout.itemAt(2).widget()  # current -> its own icon
    step_c = stepper._layout.itemAt(4).widget()  # upcoming -> its own icon

    def dot_text(step_widget) -> str:
        return step_widget.layout().itemAt(0).widget().text()

    assert dot_text(step_a) == "✓"
    assert dot_text(step_b) == "🧩"
    assert dot_text(step_c) == "🖼️"


def test_progress_stepper_falls_back_to_numbers_without_icons(qtbot) -> None:
    stepper = ProgressStepper(["A", "B"], current_index=None)
    qtbot.addWidget(stepper)
    step_a = stepper._layout.itemAt(0).widget()
    assert step_a.layout().itemAt(0).widget().text() == "1"


# --- ProgressStepper: current-stage pulse --------------------------------------------


def test_only_the_current_dot_gets_a_pulse_effect(qtbot, theme: ThemeManager) -> None:
    stepper = ProgressStepper(["A", "B", "C"], current_index=1, theme=theme)
    qtbot.addWidget(stepper)

    def dot(index: int):
        item = stepper._layout.itemAt(index * 2)
        return item.widget().layout().itemAt(0).widget()

    assert dot(0).graphicsEffect() is None
    assert isinstance(dot(1).graphicsEffect(), QGraphicsDropShadowEffect)
    assert dot(2).graphicsEffect() is None
    assert len(stepper._pulse_animations) == 1


def test_progress_stepper_rebuild_stops_old_pulse_animations(qtbot, theme: ThemeManager) -> None:
    stepper = ProgressStepper(["A", "B"], current_index=0, theme=theme)
    qtbot.addWidget(stepper)
    first_animations = list(stepper._pulse_animations)
    assert len(first_animations) == 1

    stepper.set_progress(["A", "B"], current_index=1)

    assert len(stepper._pulse_animations) == 1
    assert stepper._pulse_animations[0] is not first_animations[0]
    for anim in first_animations:
        assert anim.state().name == "Stopped"


# --- render_nav_icon ------------------------------------------------------------------


def test_render_nav_icon_returns_a_non_null_icon_for_every_glyph() -> None:
    for glyph in GLYPHS:
        icon = render_nav_icon(glyph, "#6C5CE7", size=18)
        assert isinstance(icon, QIcon)
        assert not icon.isNull()


def test_render_nav_icon_rejects_unknown_glyphs() -> None:
    with pytest.raises(ValueError, match="Unknown nav icon glyph"):
        render_nav_icon("not_a_real_glyph", "#000000")


# --- Sidebar: grouping + badge ---------------------------------------------------------


def test_sidebar_groups_match_nav_items(qtbot, theme: ThemeManager) -> None:
    sidebar = Sidebar(theme)
    qtbot.addWidget(sidebar)
    assert {item.key for item in NAV_ITEMS} == set(sidebar._buttons.keys())


def test_sidebar_set_badge_shows_and_hides(qtbot, theme: ThemeManager) -> None:
    sidebar = Sidebar(theme)
    qtbot.addWidget(sidebar)
    sidebar.show()

    sidebar.set_badge("review_queue", 5)
    badge = sidebar._badges["review_queue"]
    assert badge.isVisible()
    assert badge.text() == "5"

    sidebar.set_badge("review_queue", 0)
    assert not badge.isVisible()


def test_sidebar_set_badge_caps_display_at_99_plus(qtbot, theme: ThemeManager) -> None:
    sidebar = Sidebar(theme)
    qtbot.addWidget(sidebar)
    sidebar.set_badge("review_queue", 250)
    assert sidebar._badges["review_queue"].text() == "99+"


def test_sidebar_select_moves_indicator_to_the_selected_button(qtbot, theme: ThemeManager) -> None:
    sidebar = Sidebar(theme)
    qtbot.addWidget(sidebar)
    sidebar.show()

    sidebar.select("characters")

    # The move is an animated QPropertyAnimation — its target (endValue)
    # reflects the new selection immediately; the widget's live geometry
    # only catches up once the event loop pumps the animation's timer.
    button = sidebar.button_for("characters")
    expected_y = button.mapTo(sidebar, button.rect().topLeft()).y()
    assert sidebar._indicator_anim.endValue().y() == expected_y

    qtbot.waitUntil(lambda: sidebar._indicator.geometry().y() == expected_y, timeout=1000)


# --- TopBar: diagnostics popover is a real top-level window, not a clipped child -------


def test_diagnostics_popover_is_a_top_level_window_not_clipped_by_topbar(
    qtbot, theme: ThemeManager
) -> None:
    """Regression test: the popover used to be a plain child of TopBar,
    which is only `topbar_height` tall — Qt clips child-widget painting to
    the parent's rect, so the popover rendered as a near-blank sliver
    instead of its 4 rows. It must be a real top-level window so its full
    height can render. See docs/24_UI_UX_POLISH_V2_STATUS.md §11."""
    top_bar = TopBar(version="0.1.0", theme=theme)
    qtbot.addWidget(top_bar)

    popover = top_bar._diagnostics
    assert popover.isWindow()
    assert popover.windowFlags() & Qt.WindowType.Tool


def test_toggle_diagnostics_shows_and_hides_the_popover(qtbot, theme: ThemeManager) -> None:
    top_bar = TopBar(version="0.1.0", theme=theme)
    qtbot.addWidget(top_bar)
    top_bar.show()

    assert not top_bar._diagnostics.isVisible()
    top_bar._toggle_diagnostics()
    assert top_bar._diagnostics.isVisible()
    top_bar._toggle_diagnostics()
    assert not top_bar._diagnostics.isVisible()


def test_set_current_episode_updates_the_chip(qtbot, theme: ThemeManager) -> None:
    top_bar = TopBar(version="0.1.0", theme=theme)
    qtbot.addWidget(top_bar)

    top_bar.set_current_episode("My Episode", "Storyboard")
    assert "My Episode" in top_bar._episode_chip.text()
    assert "Storyboard" in top_bar._episode_chip.text()

    top_bar.set_current_episode(None, None)
    assert top_bar._episode_chip.text() == "No active episode"
