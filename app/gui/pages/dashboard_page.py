"""DashboardPage — the one functional screen in Milestone 4A (UI/UX-polished).

Reads real counts through ``ApplicationContext``'s services (never
instantiating one itself), shows friendly empty states when the
database has no data yet (or hasn't been migrated at all), and wires
up whichever quick actions already have a real service behind them.

Visual hierarchy (top to bottom): Production Progress → Dashboard
Summary → Quick Actions → Recent Activity. Branding lives in the top
bar, above this page, not duplicated here — see
``docs/23_UI_UX_POLISH_STATUS.md`` for the full design rationale.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.ai.exceptions import ProviderNotConfiguredError
from app.core.db.enums import PipelineStage, ProductionTaskStatus, PromptCategory, PromptType
from app.core.models import Asset, Episode, ProductionTask
from app.core.services.exceptions import ConflictError, ServiceError
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    ActionCard,
    ActivityTimeline,
    EmptyState,
    LoadingOverlay,
    ProgressStepper,
    SectionHeader,
    SummaryCard,
    parse_log_line,
    show_error,
    show_info,
    show_not_implemented,
)

_DASHBOARD_TEMPLATE_NAME = "dashboard_quick_thumbnail"
_ACTIVITY_MAX_LINES = 12

# A GUI-only display grouping of the existing Episode.pipeline_stage
# enum (app/core/db/enums.py) into the 7 founder-specified stages for
# the Production Progress stepper. Changing this list changes nothing
# about how pipeline_stage is stored or validated — see
# docs/23_UI_UX_POLISH_STATUS.md for why this stays presentation-only.
_PROGRESS_STEPS = ["Script", "Storyboard", "Images", "Voice", "Video", "SEO", "Upload"]

_STAGE_TO_STEP_INDEX: dict[PipelineStage, int] = {
    PipelineStage.IDEA: 0,
    PipelineStage.LESSON: 0,
    PipelineStage.OUTLINE: 0,
    PipelineStage.SCRIPT: 0,
    PipelineStage.STORYBOARD: 1,
    PipelineStage.IMAGE_PROMPTS: 2,
    PipelineStage.VIDEO_PROMPTS: 2,
    PipelineStage.THUMBNAIL: 2,
    PipelineStage.VOICE: 3,
    PipelineStage.SONG: 3,
    PipelineStage.EDITING: 4,
    PipelineStage.SEO: 5,
    PipelineStage.READY_TO_PUBLISH: 6,
    PipelineStage.PUBLISHED: 6,
}


class DashboardPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardPage")
        self._ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_lg, METRICS.spacing_xl, METRICS.spacing_xl
        )
        layout.setSpacing(METRICS.spacing_lg)

        layout.addWidget(self._build_progress_panel())
        layout.addLayout(self._build_summary_section())
        layout.addLayout(self._build_quick_actions_section())
        layout.addWidget(self._build_activity_panel())

        self._overlay = LoadingOverlay(self, theme)

        self.refresh()

    # --- 1. Production Progress ------------------------------------------------

    def _build_progress_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("class", "card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_lg
        )
        panel_layout.setSpacing(METRICS.spacing_md)

        self._progress_header = SectionHeader("Production Progress", "No active episode yet")
        panel_layout.addWidget(self._progress_header)

        self._progress_stepper = ProgressStepper(_PROGRESS_STEPS, None)
        panel_layout.addWidget(self._progress_stepper)

        self._progress_empty = EmptyState(
            "No active episode yet — seed demo data or create one to see its progress here.",
            icon="🎬",
        )
        self._progress_empty.setVisible(False)
        panel_layout.addWidget(self._progress_empty)

        return panel

    # --- 2. Dashboard Summary ----------------------------------------------------

    def _build_summary_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(METRICS.spacing_md)
        section.addWidget(SectionHeader("Overview", "Your production studio at a glance"))

        grid = QGridLayout()
        grid.setSpacing(METRICS.spacing_md)
        self._episodes_card = SummaryCard("🎬", "Episodes")
        self._characters_card = SummaryCard("👧", "Characters")
        self._assets_card = SummaryCard("🖼", "Assets")
        self._review_card = SummaryCard("✅", "Pending Review")
        self._tasks_card = SummaryCard("📋", "Production Tasks")
        self._provider_card = SummaryCard("🤖", "AI Provider")
        cards = [
            self._episodes_card, self._characters_card, self._assets_card,
            self._review_card, self._tasks_card, self._provider_card,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 3, index % 3)
            grid.setColumnStretch(index % 3, 1)
        section.addLayout(grid)
        return section

    # --- 3. Quick Actions ---------------------------------------------------------

    def _build_quick_actions_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(METRICS.spacing_md)
        section.addWidget(SectionHeader("Quick Actions", "Jump straight into production"))

        row = QHBoxLayout()
        row.setSpacing(METRICS.spacing_md)

        actions = [
            ("➕", "Create Episode", "Start a new episode", self._on_create_episode),
            ("📂", "Open Episode 001", "Review the demo episode", self._on_open_episode_001),
            ("📥", "Import Asset", "Bring in a file", self._on_import_asset),
            ("✨", "Run Mock AI", "Generate a test thumbnail", self._on_run_mock_ai),
            ("✅", "Review Queue", "See what's pending", self._on_open_review_queue),
        ]
        for icon, title, description, handler in actions:
            card = ActionCard(icon, title, description)
            card.clicked.connect(handler)
            row.addWidget(card, stretch=1)
        section.addLayout(row)
        return section

    def _on_create_episode(self) -> None:
        show_not_implemented(self, "Create Episode")

    def _on_open_episode_001(self) -> None:
        try:
            with self._ctx.open_session() as session:
                episode = session.query(Episode).filter_by(number=1).one_or_none()
                if episode is None:
                    show_info(
                        self, "Episode 001",
                        "No Episode #1 exists yet.\n\n"
                        "Run the CLI's `seed-demo` command to create the demo episode.",
                    )
                    return
                progress = self._ctx.episode_service.calculate_episode_progress(session, episode.id)
                show_info(
                    self, episode.title_en,
                    f"{episode.title_ar}\n\n"
                    f"Stage: {episode.pipeline_stage.value}\n"
                    f"Lesson: {episode.lesson}\n"
                    f"Task progress: {progress.completed_tasks}/{progress.total_tasks} "
                    f"({progress.percent}%)",
                )
        except OperationalError:
            self._show_db_not_ready()

    def _on_import_asset(self) -> None:
        show_not_implemented(self, "Import Asset")

    def _on_run_mock_ai(self) -> None:
        # A write path (may create a PromptTemplate row), unlike the other
        # handlers here — session_scope() so that write is committed even
        # if a caught ConflictError/ProviderNotConfiguredError makes this
        # return early, before AssetImportService's own internal commit
        # would otherwise have covered it.
        try:
            with self._ctx.session_scope() as session:
                episode = session.query(Episode).filter_by(number=1).one_or_none()
                if episode is None:
                    show_info(
                        self, "Run Mock AI",
                        "No Episode #1 exists yet.\n\n"
                        "Run the CLI's `seed-demo` command first, then try again.",
                    )
                    return
                existing_templates = self._ctx.prompt_template_service.list_prompt_templates(
                    session, category=PromptCategory.THUMBNAIL,
                )
                template = next(
                    (t for t in existing_templates if t.name == _DASHBOARD_TEMPLATE_NAME), None
                )
                if template is None:
                    template = self._ctx.prompt_template_service.create_prompt_template(
                        session,
                        name=_DASHBOARD_TEMPLATE_NAME,
                        category=PromptCategory.THUMBNAIL,
                        prompt_type=PromptType.IMAGE,
                        text_en="A bright, eye-catching thumbnail for this episode.",
                        is_reusable=True,
                    )
                self._overlay.start("Running mock AI generation…")
                QApplication.processEvents()
                try:
                    result = self._ctx.ai_orchestrator.run_workflow(
                        session,
                        "thumbnail",
                        provider_name="mock_provider",
                        prompt_template_id=template.id,
                        episode_id=episode.id,
                    )
                except ConflictError:
                    show_info(
                        self, "Run Mock AI",
                        "MockProvider is deterministic, so generating the same "
                        "thumbnail again produces the exact same file — it's "
                        "already in the review queue from a previous run.",
                    )
                    return
                except ProviderNotConfiguredError as err:
                    show_error(self, "Run Mock AI", str(err))
                    return
                finally:
                    self._overlay.stop()
                show_info(
                    self, "Run Mock AI",
                    f"Generated a new draft asset:\n\n{result.asset.relative_path}\n\n"
                    "It's now waiting in the Review Queue.",
                )
                self.refresh()
        except OperationalError:
            self._overlay.stop()
            self._show_db_not_ready()
        except ServiceError as err:
            self._overlay.stop()
            show_error(self, "Run Mock AI", str(err))

    def _on_open_review_queue(self) -> None:
        self.navigate_requested.emit("review_queue")

    # --- 4. Recent Activity --------------------------------------------------------

    def _build_activity_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("class", "card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_lg
        )
        panel_layout.setSpacing(METRICS.spacing_md)

        panel_layout.addWidget(SectionHeader("Recent Activity", "What's happened lately"))

        self._activity_timeline = ActivityTimeline()
        panel_layout.addWidget(self._activity_timeline)

        self._activity_empty = EmptyState("No activity yet.", icon="🕘")
        panel_layout.addWidget(self._activity_empty)

        return panel

    # --- data loading --------------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                episode_count = len(self._ctx.episode_service.list_episodes(session))
                character_count = len(self._ctx.character_service.list_characters(session))
                asset_count = session.query(Asset).count()
                pending_review = self._ctx.approval_service.list_pending_review_assets(session)
                open_tasks = (
                    session.query(ProductionTask)
                    .filter(ProductionTask.status != ProductionTaskStatus.DONE)
                    .count()
                )
                total_tasks = session.query(ProductionTask).count()
                active_episode = session.query(Episode).filter_by(number=1).one_or_none()
                active_episode_summary = (
                    (active_episode.title_en, active_episode.pipeline_stage)
                    if active_episode is not None
                    else None
                )
        except OperationalError:
            self._show_db_not_ready()
            return

        self._episodes_card.set_value(str(episode_count))
        self._episodes_card.set_subtitle(
            "No episodes yet" if episode_count == 0 else "Total episodes"
        )

        self._characters_card.set_value(str(character_count))
        self._characters_card.set_subtitle(
            "No characters yet" if character_count == 0 else "Active characters"
        )

        self._assets_card.set_value(str(asset_count))
        self._assets_card.set_subtitle("No assets yet" if asset_count == 0 else "Managed files")

        self._review_card.set_value(str(len(pending_review)))
        if pending_review:
            self._review_card.set_badge("Needs attention", "warning")
        else:
            self._review_card.set_badge("All clear", "success")

        self._tasks_card.set_value(str(open_tasks))
        self._tasks_card.set_subtitle(
            f"{open_tasks} open of {total_tasks} total" if total_tasks else "No tasks yet"
        )
        if total_tasks:
            self._tasks_card.set_progress((total_tasks - open_tasks) / total_tasks)

        providers = self._ctx.ai_orchestrator.list_available_providers("image")
        if providers:
            self._provider_card.set_value(providers[0])
            self._provider_card.set_badge("Configured", "success")
        else:
            self._provider_card.set_value("None")
            self._provider_card.set_badge("Not configured", "danger")

        self._refresh_progress_panel(active_episode_summary)
        self._load_recent_activity()

    def _refresh_progress_panel(self, active_episode_summary: tuple[str, PipelineStage] | None) -> None:
        if active_episode_summary is None:
            self._progress_header.set_subtitle("No active episode yet")
            self._progress_stepper.setVisible(False)
            self._progress_empty.setVisible(True)
            return

        title, stage = active_episode_summary
        self._progress_header.set_subtitle(f"{title} · {stage.value.replace('_', ' ').title()}")
        self._progress_stepper.setVisible(True)
        self._progress_empty.setVisible(False)
        self._progress_stepper.set_progress(_PROGRESS_STEPS, _STAGE_TO_STEP_INDEX.get(stage, 0))

    def _load_recent_activity(self) -> None:
        log_path = self._ctx.config.log_dir / "app.log"
        lines: list[str] = []
        if log_path.is_file():
            try:
                with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                    lines = handle.readlines()[-_ACTIVITY_MAX_LINES:]
            except OSError:
                lines = []

        entries = [entry for entry in (parse_log_line(line) for line in reversed(lines)) if entry is not None]

        if not entries:
            self._activity_timeline.setVisible(False)
            self._activity_empty.setVisible(True)
            return

        self._activity_empty.setVisible(False)
        self._activity_timeline.setVisible(True)
        self._activity_timeline.set_entries(entries)

    def _show_db_not_ready(self) -> None:
        show_error(
            self, "Database not initialized",
            "The database has no tables yet.\n\n"
            "Run `hos-cli init-db` (or `python -m app.cli.main init-db`) "
            "from the project root, then restart the app.",
        )
