"""Tests for EpisodesPage: empty state, real data, search/filter, and create flow."""

from __future__ import annotations

from app.core.db.enums import PipelineStage
from app.core.models import Episode
from app.gui.context import ApplicationContext
from app.gui.pages.episodes_page import EpisodesPage, _CreateEpisodeDialog
from app.gui.theme.manager import ThemeManager


def test_shows_empty_state_on_fresh_database(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    assert page._empty_state.isVisible()
    assert not page._error_state.isVisible()
    assert page._rows == []


def test_shows_real_episodes_after_seeding(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test Episode", lesson="Sharing")
        )

    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)

    assert len(page._rows) == 1
    _episode, row = page._rows[0]
    assert "Test Episode" in row._title_label.text()


def test_search_filters_rows_live(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(Episode(slug="ep001_a", number=1, title_ar="ا", title_en="Alpha", lesson="Sharing"))
        session.add(Episode(slug="ep002_b", number=2, title_ar="ب", title_en="Beta", lesson="Patience"))

    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    page._search._field.setText("alpha")
    visible = [ep.title_en for ep, row in page._rows if row.isVisible()]
    assert visible == ["Alpha"]


def test_stage_filter_narrows_rows(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(
                slug="ep001_a", number=1, title_ar="ا", title_en="Alpha", lesson="Sharing",
                pipeline_stage=PipelineStage.STORYBOARD,
            )
        )
        session.add(Episode(slug="ep002_b", number=2, title_ar="ب", title_en="Beta", lesson="Patience"))

    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    index = page._stage_filter.findData(PipelineStage.STORYBOARD)
    page._stage_filter.setCurrentIndex(index)
    visible = [ep.title_en for ep, row in page._rows if row.isVisible()]
    assert visible == ["Alpha"]


def test_create_episode_dialog_validates_required_fields() -> None:
    dialog = _CreateEpisodeDialog(existing_numbers=set())
    assert dialog.validate() == "Title (English) is required."
    dialog.title_en_field.setText("New Episode")
    assert dialog.validate() == "Title (Arabic) is required."
    dialog.title_ar_field.setText("حلقة")
    assert dialog.validate() == "Lesson is required."
    dialog.lesson_field.setText("Sharing")
    assert dialog.validate() is None


def test_create_episode_dialog_rejects_duplicate_number() -> None:
    dialog = _CreateEpisodeDialog(existing_numbers={1})
    dialog.title_en_field.setText("New Episode")
    dialog.title_ar_field.setText("حلقة")
    dialog.lesson_field.setText("Sharing")
    dialog.number_field.setValue(1)
    assert dialog.validate() == "Episode number 1 is already in use."


def test_create_episode_dialog_builds_expected_slug() -> None:
    dialog = _CreateEpisodeDialog(existing_numbers=set())
    dialog.title_en_field.setText("The Lost Turtle")
    dialog.number_field.setValue(5)
    fields = dialog.result_fields()
    assert fields["slug"] == "ep005_the_lost_turtle"
    assert fields["number"] == 5


def test_on_create_episode_adds_a_real_row(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)
    assert page._rows == []

    def fake_exec(self):
        self.title_en_field.setText("Created Episode")
        self.title_ar_field.setText("حلقة منشأة")
        self.lesson_field.setText("Kindness")
        return _CreateEpisodeDialog.DialogCode.Accepted

    monkeypatch.setattr(_CreateEpisodeDialog, "exec", fake_exec)
    page._on_create_episode()

    assert len(page._rows) == 1
    assert page._rows[0][0].title_en == "Created Episode"


def test_clicking_a_row_emits_episode_opened(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(
            Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test Episode", lesson="Sharing")
        )

    page = EpisodesPage(gui_context, theme)
    qtbot.addWidget(page)

    episode, row = page._rows[0]
    with qtbot.waitSignal(page.episode_opened, timeout=1000) as blocker:
        row.clicked.emit()
    assert blocker.args == [episode.id]
