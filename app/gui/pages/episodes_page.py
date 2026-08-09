"""EpisodesPage — browse, search, and create episodes.

Milestone 4B's first production screen. Follows the same
architecture rule every other page already does: this module never
imports ``app.core.db`` or instantiates a service directly — everything
goes through the ``ApplicationContext`` passed in at construction, same
as ``DashboardPage``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.db.enums import PipelineStage
from app.core.models import Episode
from app.core.naming import slugify
from app.core.services.exceptions import ConflictError, ValidationError
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    EntityRow,
    ErrorState,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    SearchBox,
    StatusBadge,
    ToolbarRow,
    show_error,
)

_STAGE_ALL = "__all__"
_GATED_STAGES = (PipelineStage.READY_TO_PUBLISH, PipelineStage.PUBLISHED)


def stage_label(stage: PipelineStage) -> str:
    return stage.value.replace("_", " ").title()


def stage_badge_variant(stage: PipelineStage) -> str:
    if stage == PipelineStage.PUBLISHED:
        return "success"
    if stage == PipelineStage.READY_TO_PUBLISH:
        return "info"
    return "neutral"


class _CreateEpisodeDialog(FormDialog):
    """slug/number/title_ar/title_en/lesson/season/includes_song — the fields
    ``EpisodeService.create_episode`` actually requires plus the handful of
    simple optional ones; not every column on the model, to stay a form a
    person can fill in thirty seconds rather than a full metadata editor."""

    def __init__(self, existing_numbers: set[int], parent: QWidget | None = None) -> None:
        super().__init__(
            "New Episode", icon="🎬", subtitle="Add it to the production pipeline",
            save_label="Create", parent=parent,
        )
        self._existing_numbers = existing_numbers

        self.number_field = QSpinBox()
        self.number_field.setRange(1, 9999)
        self.number_field.setValue(max(existing_numbers, default=0) + 1)
        self.add_row("Episode number", self.number_field)

        self.title_en_field = QLineEdit()
        self.title_en_field.setPlaceholderText("Melissa and Bilsan and the Lost Little Turtle")
        self.add_row("Title (English)", self.title_en_field)

        self.title_ar_field = QLineEdit()
        self.title_ar_field.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.title_ar_field.setPlaceholderText("ميليسا وبيلسان والسلحفاة الصغيرة التائهة")
        self.add_row("Title (Arabic)", self.title_ar_field)

        self.lesson_field = QLineEdit()
        self.lesson_field.setPlaceholderText("Sharing, patience, honesty, ...")
        self.add_row("Lesson", self.lesson_field)

        self.season_field = QSpinBox()
        self.season_field.setRange(1, 99)
        self.season_field.setValue(1)
        self.add_row("Season", self.season_field)

        self.includes_song_field = QCheckBox("This episode includes an original song")
        self.add_row("Options", self.includes_song_field)

    def validate(self) -> str | None:
        if not self.title_en_field.text().strip():
            return "Title (English) is required."
        if not self.title_ar_field.text().strip():
            return "Title (Arabic) is required."
        if not self.lesson_field.text().strip():
            return "Lesson is required."
        if self.number_field.value() in self._existing_numbers:
            return f"Episode number {self.number_field.value()} is already in use."
        return None

    def result_fields(self) -> dict[str, object]:
        title_en = self.title_en_field.text().strip()
        number = self.number_field.value()
        return {
            "slug": f"ep{number:03d}_{slugify(title_en, fallback_prefix='episode')}",
            "number": number,
            "title_ar": self.title_ar_field.text().strip(),
            "title_en": title_en,
            "lesson": self.lesson_field.text().strip(),
            "season": self.season_field.value(),
            "includes_song": self.includes_song_field.isChecked(),
        }


class EpisodesPage(QWidget):
    episode_opened = Signal(uuid.UUID)

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("episodesPage")
        self._ctx = ctx
        self._theme = theme
        self._on_feedback = on_feedback
        self._episodes: list[Episode] = []
        self._rows: list[tuple[Episode, EntityRow]] = []

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

        self._header = PageHeader(
            "Episodes", "All production episodes", primary_label="+ New Episode"
        )
        self._header.primary_action_triggered.connect(self._on_create_episode)
        layout.addWidget(self._header)

        toolbar = ToolbarRow()
        self._search = SearchBox("Search episodes…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.add_widget(self._search, stretch=1)

        self._stage_filter = QComboBox()
        self._stage_filter.addItem("All stages", _STAGE_ALL)
        for stage in PipelineStage:
            self._stage_filter.addItem(stage_label(stage), stage)
        self._stage_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.add_widget(self._stage_filter)
        layout.addWidget(toolbar)

        self._count_label = QLabel("")
        self._count_label.setProperty("class", "resultCount")
        layout.addWidget(self._count_label)

        self._list_container = QVBoxLayout()
        self._list_container.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._list_container)

        self._empty_state = EmptyState(
            "No episodes yet — create the first one to get production moving.",
            icon="🎬",
            action_label="+ New Episode",
        )
        self._empty_state.action_triggered.connect(self._on_create_episode)
        layout.addWidget(self._empty_state)

        self._error_state = ErrorState("The database has no tables yet.")
        self._error_state.retry_requested.connect(self.refresh)
        layout.addWidget(self._error_state)

        layout.addStretch(1)

        self._overlay = LoadingOverlay(self, theme)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_create_episode)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)

        self.refresh()

    # --- data loading -----------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                self._episodes = self._ctx.episode_service.list_episodes(session)
                progress_by_id = {
                    episode.id: self._ctx.episode_service.calculate_episode_progress(
                        session, episode.id
                    )
                    for episode in self._episodes
                }
        except OperationalError:
            self._show_error_state()
            return

        self._error_state.setVisible(False)
        self._rebuild_rows(progress_by_id)
        self._apply_filters()

    def _rebuild_rows(self, progress_by_id: dict) -> None:
        while self._list_container.count():
            item = self._list_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []

        for episode in self._episodes:
            progress = progress_by_id.get(episode.id)
            subtitle = episode.lesson
            if progress is not None and progress.total_tasks:
                subtitle += f"  ·  {progress.completed_tasks}/{progress.total_tasks} tasks"
            row = EntityRow("🎬", f"#{episode.number}  {episode.title_en}", subtitle)
            row.add_trailing_widget(
                StatusBadge(stage_label(episode.pipeline_stage), stage_badge_variant(episode.pipeline_stage))
            )
            row.clicked.connect(lambda _checked=False, ep=episode: self.episode_opened.emit(ep.id))
            self._list_container.addWidget(row)
            self._rows.append((episode, row))

    def _show_error_state(self) -> None:
        self._empty_state.setVisible(False)
        self._error_state.setVisible(True)
        while self._list_container.count():
            item = self._list_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # --- search / filter ---------------------------------------------------

    def _apply_filters(self, *_args: object) -> None:
        query = self._search.text().strip().lower()
        stage = self._stage_filter.currentData()

        visible_count = 0
        for episode, row in self._rows:
            matches_query = not query or query in episode.title_en.lower() or query in episode.title_ar
            matches_stage = stage == _STAGE_ALL or episode.pipeline_stage == stage
            visible = matches_query and matches_stage
            row.setVisible(visible)
            visible_count += int(visible)

        self._empty_state.setVisible(visible_count == 0 and not self._error_state.isVisible())
        if visible_count == 0 and self._episodes:
            self._empty_state.set_message("No episodes match your search.", show_action=False)
        else:
            self._empty_state.set_message(
                "No episodes yet — create the first one to get production moving."
            )
        self._count_label.setVisible(bool(self._episodes))
        self._count_label.setText(f"{visible_count} of {len(self._episodes)} episodes")

    # --- create --------------------------------------------------------------

    def _on_create_episode(self) -> None:
        existing_numbers = {episode.number for episode in self._episodes}
        dialog = _CreateEpisodeDialog(existing_numbers, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return

        fields = dialog.result_fields()
        self._overlay.start("Creating episode…")
        try:
            with self._ctx.session_scope() as session:
                self._ctx.episode_service.create_episode_from_template(session, **fields)
        except (ConflictError, ValidationError) as err:
            show_error(self, "Create Episode", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()

        self.refresh()
        if self._on_feedback:
            self._on_feedback(f"Episode #{fields['number']} created.", "success")
