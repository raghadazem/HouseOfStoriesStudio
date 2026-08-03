"""Reusable widgets shared across every GUI screen.

Every widget here reads colors from the active theme (never a literal
hex code) — see ``docs/21_DESIGN_SYSTEM.md``.
"""

from __future__ import annotations

from app.gui.widgets.dialogs import (
    confirm,
    show_error,
    show_info,
    show_not_implemented,
    show_warning,
)
from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.loading import LoadingOverlay, LoadingSpinner
from app.gui.widgets.placeholder_page import PlaceholderPage
from app.gui.widgets.search_box import SearchBox
from app.gui.widgets.section_header import SectionHeader
from app.gui.widgets.status_badge import StatusBadge
from app.gui.widgets.summary_card import SummaryCard

__all__ = [
    "EmptyState",
    "LoadingOverlay",
    "LoadingSpinner",
    "PlaceholderPage",
    "SearchBox",
    "SectionHeader",
    "StatusBadge",
    "SummaryCard",
    "confirm",
    "show_error",
    "show_info",
    "show_not_implemented",
    "show_warning",
]
