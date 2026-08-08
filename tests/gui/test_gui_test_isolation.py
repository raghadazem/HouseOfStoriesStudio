"""Regression tests for GUI test isolation itself.

``ThemeManager`` is the only thing that ever calls
``QApplication.setStyleSheet(...)`` (``docs/21_DESIGN_SYSTEM.md`` §3),
and the ``QApplication`` is a single process-wide instance every GUI
test shares (pytest-qt can't create a second one per process). Before
``conftest.py``'s ``_reset_qapplication_style`` autouse fixture, a
stylesheet applied by one test (via the ``theme`` fixture, or a test
constructing its own ``ThemeManager`` directly, as several files in this
suite do) silently stayed active for every test that ran afterward —
changing measured widget sizes (button/font padding from the QSS) in
tests that never touched theming themselves. This is what made
``PageHeader.resize(300, 100)`` measure ~437px instead of 300px only
when run as part of the full suite, never standalone. See
``docs/28_ASSET_IMPORT_AND_GUI_TEST_ISOLATION_STATUS.md``.

Test order within this file is deliberate and load-bearing: several
tests below only prove anything because of what the *previous* test in
the file did to shared ``QApplication`` state.
"""

from __future__ import annotations

from app.gui.theme.manager import ThemeManager
from app.gui.widgets.page_header import PageHeader

_WRAP_BELOW_WIDTH_PROBE = 300  # matches tests/gui/test_ui_polish_v3_widgets.py


def test_a_apply_a_dark_theme_to_the_shared_qapplication(qapp) -> None:
    """Deliberately contaminates global state, the way an ordinary theme
    test would — the next test proves it doesn't leak."""
    theme = ThemeManager(qapp, initial_theme="dark")
    assert qapp.styleSheet() != ""
    assert theme.is_dark()


def test_b_qapplication_style_is_reset_after_the_previous_test(qapp) -> None:
    """Directly proves the autouse fixture's teardown ran: if it hadn't,
    this would see test_a's dark stylesheet still applied."""
    assert qapp.styleSheet() == ""


def test_c_page_header_wraps_correctly_standalone(qtbot) -> None:
    """Baseline: a fresh PageHeader, no ThemeManager touched in this
    test at all, run first (alphabetically/by definition order) among
    the wrap-behavior checks here."""
    header = PageHeader("Episodes", primary_label="+ New Episode")
    qtbot.addWidget(header)
    header.show()

    header.resize(800, 60)
    qtbot.waitUntil(lambda: header._wrapped is False, timeout=1000)

    header.resize(_WRAP_BELOW_WIDTH_PROBE, 100)
    qtbot.waitUntil(lambda: header._wrapped is True, timeout=1000)


def test_d_apply_several_theme_changes_including_a_toggle(qapp, qtbot) -> None:
    """Simulates a realistic run of test_theme.py's tests happening
    just before the PageHeader check below."""
    theme = ThemeManager(qapp, initial_theme="light")
    theme.apply("dark")
    theme.toggle()
    theme.apply("light")
    assert qapp.styleSheet() != ""  # contaminated again, on purpose


def test_e_page_header_wraps_identically_after_theme_churn(qtbot) -> None:
    """Same widget, same thresholds, same assertions as test_c — proving
    PageHeader's actual behavior is unaffected by the theme tests that
    ran in between, not just that the stylesheet string is empty."""
    header = PageHeader("Episodes", primary_label="+ New Episode")
    qtbot.addWidget(header)
    header.show()

    header.resize(800, 60)
    qtbot.waitUntil(lambda: header._wrapped is False, timeout=1000)

    header.resize(_WRAP_BELOW_WIDTH_PROBE, 100)
    qtbot.waitUntil(lambda: header._wrapped is True, timeout=1000)

    assert header.width() == _WRAP_BELOW_WIDTH_PROBE  # the actual regression: this used to be ~437
