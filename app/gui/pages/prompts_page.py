"""PromptsPage — browse, search, and create prompt templates.

Every field this page can set maps directly to
``PromptTemplateService.create_prompt_template`` — no draft/staging
concept invented on top of it. Character/episode/scene-scoped prompts
(vs. reusable/global ones) can already be created by the AI workflow
layer; this page's create form covers the common case (a reusable or
unscoped prompt) rather than re-exposing every possible association.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.db.enums import PromptCategory, PromptType
from app.core.models import PromptTemplate
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

_CATEGORY_ALL = "all"

_CATEGORY_ICON = {
    PromptCategory.STORY: "📝",
    PromptCategory.STORYBOARD: "🧩",
    PromptCategory.CHARACTER: "🧒",
    PromptCategory.BACKGROUND: "🏞",
    PromptCategory.IMAGE: "🖼",
    PromptCategory.VIDEO: "🎬",
    PromptCategory.VOICE: "🎙️",
    PromptCategory.SONG: "🎵",
    PromptCategory.THUMBNAIL: "🏷",
    PromptCategory.SEO: "🔍",
    PromptCategory.PUBLISHING: "📢",
}


def category_label(category: PromptCategory) -> str:
    return category.value.replace("_", " ").title()


def type_label(prompt_type: PromptType) -> str:
    return prompt_type.value.replace("_", " ").title()


class _CreatePromptDialog(FormDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "New Prompt Template", icon="✍️", subtitle="Reusable across episodes and characters",
            save_label="Create", parent=parent,
        )

        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("dashboard_quick_thumbnail")
        self.add_row("Name", self.name_field)

        self.category_field = QComboBox()
        for category in PromptCategory:
            self.category_field.addItem(category_label(category), category)
        self.add_row("Category", self.category_field)

        self.type_field = QComboBox()
        for prompt_type in PromptType:
            self.type_field.addItem(type_label(prompt_type), prompt_type)
        self.add_row("Prompt type", self.type_field)

        self.text_field = QTextEdit()
        self.text_field.setPlaceholderText("A bright, eye-catching thumbnail for {{ episode_title }}.")
        self.text_field.setMinimumHeight(120)
        self.add_row("Prompt text (English)", self.text_field)

        self.target_tool_field = QLineEdit()
        self.target_tool_field.setPlaceholderText("mock_provider, midjourney, ... (optional)")
        self.add_row("Target tool", self.target_tool_field)

        self.reusable_field = QCheckBox("Reusable across episodes/characters")
        self.add_row("Options", self.reusable_field)

    def validate(self) -> str | None:
        if not self.name_field.text().strip():
            return "Name is required."
        if not self.text_field.toPlainText().strip():
            return "Prompt text is required."
        return None

    def result_fields(self) -> dict[str, object]:
        return {
            "name": self.name_field.text().strip(),
            # QComboBox.currentData() round-trips a str-subclassed Python
            # enum as a plain str, not the enum member (see the matching
            # comment in assets_page.py) — re-wrap through the enum
            # constructor so PromptTemplateService gets real
            # PromptCategory/PromptType instances, not bare strings.
            "category": PromptCategory(self.category_field.currentData()),
            "prompt_type": PromptType(self.type_field.currentData()),
            "text_en": self.text_field.toPlainText().strip(),
            "is_reusable": self.reusable_field.isChecked(),
            "target_tool": self.target_tool_field.text().strip() or None,
        }


class _PromptDetailDialog(FormDialog):
    def __init__(self, template: PromptTemplate, parent: QWidget | None = None) -> None:
        super().__init__(f"{template.name} ({template.version})", show_save=False, min_width=520, parent=parent)

        meta_row = QHBoxLayout()
        meta_row.addWidget(StatusBadge(category_label(template.category), "info"))
        meta_row.addWidget(StatusBadge(type_label(template.prompt_type), "neutral"))
        if template.is_reusable:
            meta_row.addWidget(StatusBadge("Reusable", "success"))
        if template.target_tool:
            meta_row.addWidget(StatusBadge(template.target_tool, "neutral"))
        meta_row.addStretch(1)
        meta_wrap = QWidget()
        meta_wrap.setLayout(meta_row)
        self.add_row("Status", meta_wrap)

        text_field = QTextEdit(template.text_en)
        text_field.setReadOnly(True)
        text_field.setMinimumHeight(160)
        self.add_row("Prompt text (English)", text_field)


class PromptsPage(QWidget):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("promptsPage")
        self._ctx = ctx
        self._theme = theme
        self._on_feedback = on_feedback
        self._templates: list[PromptTemplate] = []
        self._rows: list[tuple[PromptTemplate, EntityRow]] = []

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
            "Prompt Manager", "Reusable and contextual prompt templates", primary_label="+ New Prompt"
        )
        self._header.primary_action_triggered.connect(self._on_create_prompt)
        layout.addWidget(self._header)

        toolbar = ToolbarRow()
        self._search = SearchBox("Search prompts…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.add_widget(self._search, stretch=1)

        self._category_filter = QComboBox()
        self._category_filter.addItem("All categories", _CATEGORY_ALL)
        for category in PromptCategory:
            self._category_filter.addItem(category_label(category), category)
        self._category_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.add_widget(self._category_filter)
        layout.addWidget(toolbar)

        self._count_label = QLabel("")
        self._count_label.setProperty("class", "resultCount")
        layout.addWidget(self._count_label)

        self._list_container = QVBoxLayout()
        self._list_container.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._list_container)

        self._empty_state = EmptyState(
            "No prompt templates yet — create the first one for your production pipeline.",
            icon="✍️",
            action_label="+ New Prompt",
        )
        self._empty_state.action_triggered.connect(self._on_create_prompt)
        layout.addWidget(self._empty_state)

        self._error_state = ErrorState("The database has no tables yet.")
        self._error_state.retry_requested.connect(self.refresh)
        layout.addWidget(self._error_state)

        layout.addStretch(1)

        self._overlay = LoadingOverlay(self, theme)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_create_prompt)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)

        self.refresh()

    # --- data loading -----------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                self._templates = self._ctx.prompt_template_service.list_prompt_templates(session)
        except OperationalError:
            self._show_error_state()
            return

        self._error_state.setVisible(False)
        self._rebuild_rows()
        self._apply_filters()

    def _rebuild_rows(self) -> None:
        while self._list_container.count():
            item = self._list_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []

        for template in self._templates:
            subtitle = f"{category_label(template.category)} · {type_label(template.prompt_type)}"
            row = EntityRow(_CATEGORY_ICON.get(template.category, "✍️"), f"{template.name}  ·  {template.version}", subtitle)
            if template.is_reusable:
                row.add_trailing_widget(StatusBadge("Reusable", "info"))
            row.clicked.connect(lambda _checked=False, t=template: self._open_detail(t))
            self._list_container.addWidget(row)
            self._rows.append((template, row))

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
        category = self._category_filter.currentData()

        visible_count = 0
        for template, row in self._rows:
            matches_query = (
                not query or query in template.name.lower() or query in template.text_en.lower()
            )
            matches_category = category == _CATEGORY_ALL or template.category == category
            visible = matches_query and matches_category
            row.setVisible(visible)
            visible_count += int(visible)

        self._empty_state.setVisible(visible_count == 0 and not self._error_state.isVisible())
        if self._templates:
            self._empty_state.set_message("No prompts match your search.", show_action=False)
        else:
            self._empty_state.set_message(
                "No prompt templates yet — create the first one for your production pipeline."
            )
        self._count_label.setVisible(bool(self._templates))
        self._count_label.setText(f"{visible_count} of {len(self._templates)} prompts")

    # --- detail / create ----------------------------------------------------

    def _open_detail(self, template: PromptTemplate) -> None:
        dialog = _PromptDetailDialog(template, parent=self)
        dialog.exec()

    def _on_create_prompt(self) -> None:
        dialog = _CreatePromptDialog(parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return

        fields = dialog.result_fields()
        self._overlay.start("Creating prompt template…")
        try:
            with self._ctx.session_scope() as session:
                self._ctx.prompt_template_service.create_prompt_template(session, **fields)
        except (ConflictError, ValidationError) as err:
            show_error(self, "New Prompt Template", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()

        self.refresh()
        if self._on_feedback:
            self._on_feedback(f"Prompt template '{fields['name']}' created.", "success")
