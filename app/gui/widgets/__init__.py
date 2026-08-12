"""Reusable widgets shared across every GUI screen.

Every widget here reads colors from the active theme (never a literal
hex code) — see ``docs/21_DESIGN_SYSTEM.md``.
"""

from __future__ import annotations

from app.gui.widgets.action_card import ActionCard
from app.gui.widgets.activity_timeline import ActivityEntry, ActivityTimeline, parse_log_line
from app.gui.widgets.app_logo import AppLogo
from app.gui.widgets.candidate_review import (
    AudioCandidateTile,
    CandidateReviewDialogBase,
    CandidateTile,
)
from app.gui.widgets.dialogs import (
    confirm,
    show_error,
    show_info,
    show_not_implemented,
    show_warning,
)
from app.gui.widgets.elevated_card import ElevatedCard
from app.gui.widgets.empty_state import EmptyState
from app.gui.widgets.entity_card import EntityCard
from app.gui.widgets.entity_row import EntityRow
from app.gui.widgets.error_state import ErrorState
from app.gui.widgets.form_dialog import FormDialog
from app.gui.widgets.loading import LoadingOverlay, LoadingSpinner
from app.gui.widgets.nav_icon import render_nav_icon
from app.gui.widgets.page_header import PageHeader
from app.gui.widgets.placeholder_page import PlaceholderPage
from app.gui.widgets.progress_stepper import ProgressStepper
from app.gui.widgets.relative_time import age_label
from app.gui.widgets.responsive_grid import ResponsiveGrid
from app.gui.widgets.scene_card import SceneCard
from app.gui.widgets.search_box import SearchBox
from app.gui.widgets.section_header import SectionHeader
from app.gui.widgets.status_badge import StatusBadge
from app.gui.widgets.summary_card import SummaryCard
from app.gui.widgets.toast import Toast, ToastHost
from app.gui.widgets.toolbar_row import ToolbarRow

__all__ = [
    "ActionCard",
    "ActivityEntry",
    "ActivityTimeline",
    "AppLogo",
    "AudioCandidateTile",
    "CandidateReviewDialogBase",
    "CandidateTile",
    "ElevatedCard",
    "EmptyState",
    "EntityCard",
    "EntityRow",
    "ErrorState",
    "FormDialog",
    "LoadingOverlay",
    "LoadingSpinner",
    "PageHeader",
    "PlaceholderPage",
    "ProgressStepper",
    "ResponsiveGrid",
    "SceneCard",
    "SearchBox",
    "SectionHeader",
    "StatusBadge",
    "SummaryCard",
    "Toast",
    "ToastHost",
    "ToolbarRow",
    "age_label",
    "confirm",
    "parse_log_line",
    "render_nav_icon",
    "show_error",
    "show_info",
    "show_not_implemented",
    "show_warning",
]
