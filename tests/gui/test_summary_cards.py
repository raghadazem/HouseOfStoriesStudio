"""SummaryCard: the reusable widget in isolation, independent of the Dashboard."""

from __future__ import annotations

from app.gui.widgets.summary_card import SummaryCard


def test_summary_card_shows_initial_values(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes", "5", "Total episodes")
    qtbot.addWidget(card)
    card.show()  # isVisible() only reflects reality once the widget chain is shown

    assert card._title_label.text() == "Episodes"
    assert card._value_label.text() == "5"
    assert card._subtitle_label.text() == "Total episodes"
    assert card._subtitle_label.isVisible()


def test_summary_card_default_value_is_em_dash(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    assert card._value_label.text() == "—"


def test_summary_card_subtitle_hidden_when_not_given(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    assert not card._subtitle_label.isVisible()


def test_set_value_updates_the_label(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    card.set_value("42")
    assert card._value_label.text() == "42"


def test_set_subtitle_shows_it(qtbot) -> None:
    card = SummaryCard("🎬", "Episodes")
    qtbot.addWidget(card)
    card.show()
    card.set_subtitle("Updated")
    assert card._subtitle_label.text() == "Updated"
    assert card._subtitle_label.isVisible()


def test_set_badge_adds_and_updates_a_status_badge(qtbot) -> None:
    card = SummaryCard("✅", "Pending Review")
    qtbot.addWidget(card)

    card.set_badge("Needs attention", "warning")
    assert card._badge is not None
    assert card._badge.text() == "Needs attention"
    assert card._badge.property("class") == "badge-warning"

    card.set_badge("All clear", "success")
    assert card._badge.text() == "All clear"
    assert card._badge.property("class") == "badge-success"
