"""Tests for the Milestone 4B shared widgets: ErrorState, PageHeader, EntityRow,
EntityCard, FormDialog, ResponsiveGrid, and the age_label relative-time helper.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtWidgets import QLabel, QPushButton

from app.gui.widgets.entity_card import EntityCard
from app.gui.widgets.entity_row import EntityRow
from app.gui.widgets.error_state import ErrorState
from app.gui.widgets.form_dialog import FormDialog
from app.gui.widgets.page_header import PageHeader
from app.gui.widgets.relative_time import age_label
from app.gui.widgets.responsive_grid import ResponsiveGrid

# --- ErrorState -------------------------------------------------------------------


def test_error_state_shows_message_and_retry_button(qtbot) -> None:
    state = ErrorState("Something broke")
    qtbot.addWidget(state)
    assert state._message_label.text() == "Something broke"
    assert state._retry_button is not None


def test_error_state_retry_emits_signal(qtbot) -> None:
    state = ErrorState("Something broke")
    qtbot.addWidget(state)
    with qtbot.waitSignal(state.retry_requested, timeout=1000):
        state._retry_button.click()


def test_error_state_without_retry_hides_button(qtbot) -> None:
    state = ErrorState("Something broke", retry_label=None)
    qtbot.addWidget(state)
    assert state._retry_button is None


# --- PageHeader ---------------------------------------------------------------------


def test_page_header_shows_title_and_subtitle(qtbot) -> None:
    header = PageHeader("Episodes", "All production episodes")
    qtbot.addWidget(header)
    assert header._title_label.text() == "Episodes"
    assert header._subtitle_label.text() == "All production episodes"


def test_page_header_without_primary_label_has_no_button(qtbot) -> None:
    header = PageHeader("Settings")
    qtbot.addWidget(header)
    assert header.primary_button is None


def test_page_header_primary_action_emits_signal(qtbot) -> None:
    header = PageHeader("Episodes", primary_label="+ New Episode")
    qtbot.addWidget(header)
    with qtbot.waitSignal(header.primary_action_triggered, timeout=1000):
        header.primary_button.click()


# --- EntityRow (accessible QPushButton-based row) ------------------------------------


def test_entity_row_is_a_pushbutton_for_accessibility(qtbot) -> None:
    row = EntityRow("🎬", "Episode 1", "Idea")
    qtbot.addWidget(row)
    assert isinstance(row, QPushButton)
    assert row.focusPolicy() != 0  # keyboard-focusable, unlike a plain QFrame


def test_entity_row_click_emits_clicked(qtbot) -> None:
    row = EntityRow("🎬", "Episode 1")
    qtbot.addWidget(row)
    with qtbot.waitSignal(row.clicked, timeout=1000):
        row.click()


def test_entity_row_set_title_and_subtitle(qtbot) -> None:
    row = EntityRow("🎬", "Episode 1", "Idea")
    qtbot.addWidget(row)
    row.show()  # isVisible() only reflects reality once the widget chain is shown
    row.set_title("Episode 2")
    row.set_subtitle("Storyboard")
    assert row._title_label.text() == "Episode 2"
    assert row._subtitle_label.text() == "Storyboard"
    assert row._subtitle_label.isVisible()


def test_entity_row_add_trailing_widget(qtbot) -> None:
    row = EntityRow("🎬", "Episode 1")
    qtbot.addWidget(row)
    label = QLabel("Idea")
    row.add_trailing_widget(label)
    assert row._trailing_layout.count() == 1


# --- EntityCard -----------------------------------------------------------------------


def test_entity_card_is_a_pushbutton_for_accessibility(qtbot) -> None:
    card = EntityCard("🧒", "Melissa", "Hero")
    qtbot.addWidget(card)
    assert isinstance(card, QPushButton)


def test_entity_card_click_emits_clicked(qtbot) -> None:
    card = EntityCard("🧒", "Melissa")
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.clicked, timeout=1000):
        card.click()


def test_entity_card_set_thumbnail_switches_to_image_class(qtbot) -> None:
    from PySide6.QtGui import QPixmap

    card = EntityCard("🖼", "photo.png")
    qtbot.addWidget(card)
    pixmap = QPixmap(50, 50)
    pixmap.fill()
    card.set_thumbnail(pixmap)
    assert card._thumb_label.property("class") == "entityCardThumb-image"
    assert not card._thumb_label.pixmap().isNull()


# --- FormDialog -----------------------------------------------------------------------


def test_form_dialog_save_calls_validate_and_blocks_on_error(qtbot) -> None:
    dialog = FormDialog("Test Form")
    qtbot.addWidget(dialog)
    dialog.show()  # isVisible() only reflects reality once the widget chain is shown
    dialog.validate = lambda: "Something is wrong"
    dialog._on_save_clicked()
    assert dialog.result() == 0  # not accepted
    assert dialog._error_label.isVisible()
    assert dialog._error_label.text() == "Something is wrong"


def test_form_dialog_save_accepts_when_valid(qtbot) -> None:
    dialog = FormDialog("Test Form")
    qtbot.addWidget(dialog)
    dialog.validate = lambda: None
    dialog._on_save_clicked()
    assert dialog.result() == FormDialog.DialogCode.Accepted


def test_form_dialog_without_save_shows_close_only(qtbot) -> None:
    dialog = FormDialog("Details", show_save=False)
    qtbot.addWidget(dialog)
    assert dialog._save_button is None


def test_form_dialog_add_row_appends_to_content_layout(qtbot) -> None:
    dialog = FormDialog("Test Form")
    qtbot.addWidget(dialog)
    dialog.add_row("Name", QLabel("value"))
    assert dialog.content_layout.count() == 1


# --- ResponsiveGrid ---------------------------------------------------------------------


def test_responsive_grid_lays_out_more_columns_when_wider(qtbot) -> None:
    grid = ResponsiveGrid(card_min_width=100, spacing=10)
    qtbot.addWidget(grid)
    grid.show()
    cards = [QPushButton(str(i)) for i in range(6)]
    grid.set_cards(cards)

    grid.resize(150, 400)
    qtbot.wait(20)
    assert grid._columns == 1

    grid.resize(650, 400)
    qtbot.wait(20)
    assert grid._columns == 6


def test_responsive_grid_set_cards_clears_previous_layout(qtbot) -> None:
    grid = ResponsiveGrid(card_min_width=100)
    qtbot.addWidget(grid)
    grid.resize(500, 400)
    grid.set_cards([QPushButton("a"), QPushButton("b")])
    assert grid._grid.count() == 2

    grid.set_cards([QPushButton("c")])
    assert grid._grid.count() == 1


# --- age_label ------------------------------------------------------------------------


def test_age_label_buckets_aware_utc_timestamps() -> None:
    now = datetime.now(UTC)
    assert age_label(now) == "just now"
    assert age_label(now - timedelta(minutes=5)) == "5m ago"
    assert age_label(now - timedelta(hours=3)) == "3h ago"
    assert age_label(now - timedelta(days=2)) == "2d ago"


def test_age_label_treats_naive_timestamps_as_utc() -> None:
    """SQLite round-trips DateTime(timezone=True) as naive datetimes that
    still represent UTC — age_label must not crash or misinterpret them."""
    naive_now = datetime.now(UTC).replace(tzinfo=None)
    assert age_label(naive_now) == "just now"
