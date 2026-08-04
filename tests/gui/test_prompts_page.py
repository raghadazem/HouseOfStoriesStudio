"""Tests for PromptsPage: empty state, real data, search/filter, and create flow."""

from __future__ import annotations

from app.core.db.enums import PromptCategory, PromptType
from app.core.models import PromptTemplate
from app.gui.context import ApplicationContext
from app.gui.pages.prompts_page import PromptsPage, _CreatePromptDialog
from app.gui.theme.manager import ThemeManager


def test_shows_empty_state_on_fresh_database(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    assert page._empty_state.isVisible()
    assert page._rows == []


def test_shows_real_prompts_after_seeding(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            PromptTemplate(
                name="hero_thumbnail", category=PromptCategory.THUMBNAIL,
                prompt_type=PromptType.IMAGE, text_en="A bright thumbnail.",
            )
        )

    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)

    assert len(page._rows) == 1
    _template, row = page._rows[0]
    assert "hero_thumbnail" in row._title_label.text()


def test_search_filters_rows_live(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            PromptTemplate(
                name="alpha_prompt", category=PromptCategory.STORY,
                prompt_type=PromptType.TEXT, text_en="Alpha text",
            )
        )
        session.add(
            PromptTemplate(
                name="beta_prompt", category=PromptCategory.STORY,
                prompt_type=PromptType.TEXT, text_en="Beta text",
            )
        )

    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    page._search._field.setText("alpha")
    visible = [t.name for t, row in page._rows if row.isVisible()]
    assert visible == ["alpha_prompt"]


def test_category_filter_narrows_rows(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            PromptTemplate(
                name="thumb_prompt", category=PromptCategory.THUMBNAIL,
                prompt_type=PromptType.IMAGE, text_en="Thumb",
            )
        )
        session.add(
            PromptTemplate(
                name="story_prompt", category=PromptCategory.STORY,
                prompt_type=PromptType.TEXT, text_en="Story",
            )
        )

    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    index = page._category_filter.findData(PromptCategory.THUMBNAIL)
    page._category_filter.setCurrentIndex(index)
    visible = [t.name for t, row in page._rows if row.isVisible()]
    assert visible == ["thumb_prompt"]


def test_create_prompt_dialog_validates_required_fields() -> None:
    dialog = _CreatePromptDialog()
    assert dialog.validate() == "Name is required."
    dialog.name_field.setText("test_prompt")
    assert dialog.validate() == "Prompt text is required."
    dialog.text_field.setPlainText("Some prompt text")
    assert dialog.validate() is None


def test_create_prompt_dialog_result_fields_use_real_enum_members() -> None:
    """Regression test: QComboBox.currentData() round-trips a
    str-subclassed Python enum as a plain str, not the enum member —
    PromptTemplateService.create_prompt_template needs real
    PromptCategory/PromptType instances. Without the fix, this silently
    passed a bare string through, which the underlying Enum column
    could reject at flush/commit time."""
    dialog = _CreatePromptDialog()
    dialog.name_field.setText("test_prompt")
    dialog.text_field.setPlainText("Some prompt text")
    fields = dialog.result_fields()
    assert isinstance(fields["category"], PromptCategory)
    assert isinstance(fields["prompt_type"], PromptType)


def test_on_create_prompt_adds_a_real_row_and_persists(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)
    assert page._rows == []

    def fake_exec(self):
        self.name_field.setText("new_prompt")
        self.text_field.setPlainText("A generated prompt.")
        return _CreatePromptDialog.DialogCode.Accepted

    monkeypatch.setattr(_CreatePromptDialog, "exec", fake_exec)
    page._on_create_prompt()

    assert len(page._rows) == 1
    assert page._rows[0][0].name == "new_prompt"
    with gui_context.open_session() as session:
        assert session.query(PromptTemplate).filter_by(name="new_prompt").count() == 1


def test_open_detail_builds_dialog(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            PromptTemplate(
                name="hero_thumbnail", category=PromptCategory.THUMBNAIL,
                prompt_type=PromptType.IMAGE, text_en="A bright thumbnail.",
            )
        )

    page = PromptsPage(gui_context, theme)
    qtbot.addWidget(page)

    opened = []
    from app.gui.pages import prompts_page as module

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            opened.append(args)

        def exec(self):
            return 0

    monkeypatch.setattr(module, "_PromptDetailDialog", _FakeDialog)
    template, _row = page._rows[0]
    page._open_detail(template)
    assert len(opened) == 1
