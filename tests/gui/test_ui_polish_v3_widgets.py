"""Tests for the GUI polish pass (v3): EmptyState's action button, FormDialog's
header/icon/subtitle, ToolbarRow and PageHeader's narrow-width wrapping, and the
new Toast/ToastHost notification widgets.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.error_state import ErrorState
from app.gui.widgets.form_dialog import FormDialog
from app.gui.widgets.page_header import PageHeader
from app.gui.widgets.toast import Toast, ToastHost
from app.gui.widgets.toolbar_row import ToolbarRow

# --- EmptyState v2 -----------------------------------------------------------------


def test_empty_state_without_action_label_has_no_button(qtbot) -> None:
    state = EmptyState("Nothing here yet.")
    qtbot.addWidget(state)
    assert state._action_button is None


def test_empty_state_action_button_emits_signal(qtbot) -> None:
    state = EmptyState("No episodes yet.", action_label="+ New Episode")
    qtbot.addWidget(state)
    assert state._action_button is not None
    with qtbot.waitSignal(state.action_triggered, timeout=1000):
        state._action_button.click()


def test_empty_state_set_message_can_hide_action(qtbot) -> None:
    state = EmptyState("No episodes yet.", action_label="+ New Episode")
    qtbot.addWidget(state)
    state.show()  # isVisible() only reflects reality once the widget chain is shown
    state.set_message("No episodes match your search.", show_action=False)
    assert state._message_label.text() == "No episodes match your search."
    assert not state._action_button.isVisible()

    state.set_message("No episodes yet.")
    assert state._action_button.isVisible()


# --- ErrorState shares the same icon-badge treatment --------------------------------


def test_error_state_icon_uses_shared_empty_state_badge_class(qtbot) -> None:
    state = ErrorState("Something broke")
    qtbot.addWidget(state)
    badges = [
        label for label in state.findChildren(QLabel) if label.property("class") == "emptyStateIcon"
    ]
    assert len(badges) == 1
    assert badges[0].text() == "⚠️"


# --- FormDialog header polish --------------------------------------------------------


def test_form_dialog_with_icon_and_subtitle(qtbot) -> None:
    dialog = FormDialog("New Episode", icon="🎬", subtitle="Add it to the roster")
    qtbot.addWidget(dialog)
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "New Episode" in labels
    assert "Add it to the roster" in labels


def test_form_dialog_without_icon_has_no_extra_chip(qtbot) -> None:
    dialog = FormDialog("Details", show_save=False)
    qtbot.addWidget(dialog)
    chips = [
        label for label in dialog.findChildren(QLabel) if label.property("class") == "iconChip"
    ]
    assert chips == []


def test_form_dialog_show_starts_fully_opaque_eventually(qtbot) -> None:
    """The open animation starts at 0 opacity — after it settles the dialog
    content should be fully visible, not stuck invisible."""
    dialog = FormDialog("Test Form")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(250)  # longer than the ~160ms open animation
    assert dialog._opacity_effect.opacity() == 1.0


# --- ToolbarRow wraps at narrow widths ------------------------------------------------


def test_toolbar_row_wraps_below_threshold(qtbot) -> None:
    toolbar = ToolbarRow()
    qtbot.addWidget(toolbar)
    search = QPushButton("search")
    filter_box = QPushButton("filter")
    toolbar.add_widget(search, stretch=1)
    toolbar.add_widget(filter_box)
    toolbar.show()

    toolbar.resize(900, 40)
    qtbot.wait(20)
    assert toolbar._wrapped is False

    toolbar.resize(400, 80)
    qtbot.wait(20)
    assert toolbar._wrapped is True


# --- PageHeader wraps its primary button at very narrow widths -----------------------


def test_page_header_wraps_button_below_threshold(qtbot) -> None:
    header = PageHeader("Episodes", primary_label="+ New Episode")
    qtbot.addWidget(header)
    header.show()

    header.resize(800, 60)
    qtbot.wait(20)
    assert header._wrapped is False

    header.resize(300, 100)
    qtbot.wait(20)
    assert header._wrapped is True


def test_page_header_never_wraps_without_a_primary_button(qtbot) -> None:
    header = PageHeader("Settings")
    qtbot.addWidget(header)
    header.show()
    header.resize(200, 60)
    qtbot.wait(20)
    assert header._wrapped is False


# --- Toast / ToastHost -----------------------------------------------------------------


def test_toast_invalid_variant_falls_back_to_info(qtbot) -> None:
    toast = Toast("Something happened", variant="not-a-real-variant")  # type: ignore[arg-type]
    qtbot.addWidget(toast)
    assert toast.property("class") == "toast-info"


def test_toast_host_show_toast_adds_and_dismiss_removes(qtbot) -> None:
    anchor = QPushButton()
    qtbot.addWidget(anchor)
    anchor.resize(1000, 700)
    anchor.show()
    host = ToastHost(anchor)
    qtbot.addWidget(host)

    host.show_toast("Episode created.", "success")
    assert len(host._toasts) == 1
    toast = host._toasts[0]
    assert toast.property("class") == "toast-success"

    with qtbot.waitSignal(toast.dismissed, timeout=1000):
        toast.dismiss()
    assert host._toasts == []


def test_toast_host_repositions_to_anchor_top_right(qtbot) -> None:
    anchor = QPushButton()
    qtbot.addWidget(anchor)
    anchor.resize(1000, 700)
    anchor.show()
    host = ToastHost(anchor, top_offset=64)
    qtbot.addWidget(host)
    host.show_toast("Hello", "info")

    assert host.x() == anchor.width() - host.width() - 24  # METRICS.spacing_lg
    assert host.y() == 64 + 24
