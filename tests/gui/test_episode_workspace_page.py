"""Tests for EpisodeWorkspacePage: tabs, storyboard scene editing, SEO, Export gating."""

from __future__ import annotations

from app.core.db.episode_001_production import populate_episode_001_production_content
from app.core.models import Episode
from app.gui.context import ApplicationContext
from app.gui.pages.episode_workspace_page import EpisodeWorkspacePage
from app.gui.theme.manager import ThemeManager
from app.gui.widgets import SceneCard

_EXPECTED_TAB_LABELS = [
    "📝 Script",
    "🧩 Storyboard",
    "🖼 Images",
    "🎙️ Voice",
    "🎵 Music",
    "🎬 Video",
    "🔍 SEO",
    "🚀 Export",
]


def _episode(gui_context: ApplicationContext) -> Episode:
    with gui_context.session_scope() as session:
        episode = Episode(
            slug="ep001_test", number=1, title_ar="ع", title_en="Test Episode", lesson="Sharing"
        )
        session.add(episode)
        session.flush()
        episode_id = episode.id
    with gui_context.open_session() as session:
        return session.get(Episode, episode_id)


def _cards(page: EpisodeWorkspacePage) -> list[SceneCard]:
    layout = page._scene_list_layout
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def test_all_eight_tabs_present(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    assert page._tabs.count() == 8
    assert [page._tabs.tabText(i) for i in range(8)] == _EXPECTED_TAB_LABELS


def test_storyboard_shows_empty_state_with_no_scenes(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    page._tabs.setCurrentIndex(1)  # Storyboard — QTabWidget only shows the current tab

    assert page._scenes_empty_state.isVisible()
    assert _cards(page) == []


def test_add_scene_creates_a_card_and_hides_empty_state(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    page._on_add_scene()

    assert len(_cards(page)) == 1
    assert not page._scenes_empty_state.isVisible()


def test_duplicate_scene_adds_a_second_card(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    with gui_context.session_scope() as session:
        scene = gui_context.scene_service.add_scene(session, episode.id, title="Original")
        scene_id = scene.id

    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    page._on_duplicate_scene(scene_id)

    assert len(_cards(page)) == 2


def test_delete_scene_removes_its_card(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    with gui_context.session_scope() as session:
        scene = gui_context.scene_service.add_scene(session, episode.id)
        scene_id = scene.id

    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    page._tabs.setCurrentIndex(1)  # Storyboard — QTabWidget only shows the current tab
    assert len(_cards(page)) == 1

    page._on_delete_scene(scene_id)

    assert _cards(page) == []
    assert page._scenes_empty_state.isVisible()


def test_move_scene_down_then_up_reorders_cards(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    with gui_context.session_scope() as session:
        first = gui_context.scene_service.add_scene(session, episode.id, title="First")
        gui_context.scene_service.add_scene(session, episode.id, title="Second")
        first_id = first.id

    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)
    assert [c._title_label.text() for c in _cards(page)] == ["Scene 1: First", "Scene 2: Second"]

    page._on_move_scene(first_id, 1)  # move "First" down, past "Second"

    assert [c._title_label.text() for c in _cards(page)] == ["Scene 1: Second", "Scene 2: First"]

    page._on_move_scene(first_id, -1)  # move "First" (now scene 2) back up

    assert [c._title_label.text() for c in _cards(page)] == ["Scene 1: First", "Scene 2: Second"]


def test_expand_collapse_toggles_card_body_visibility(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    with gui_context.session_scope() as session:
        gui_context.scene_service.add_scene(session, episode.id)

    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    page._tabs.setCurrentIndex(1)  # Storyboard — QTabWidget only shows the current tab
    card = _cards(page)[0]
    assert not card.is_expanded

    card.toggle_expanded()
    assert card.is_expanded
    assert card._body.isVisible()

    card.toggle_expanded()
    assert not card.is_expanded
    assert not card._body.isVisible()


def test_compose_prompt_populates_the_cards_prompt_fields(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    with gui_context.session_scope() as session:
        scene = gui_context.scene_service.add_scene(
            session, episode.id, description="A turtle on a riverbank", camera_direction="Wide shot"
        )
        scene_id = scene.id

    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)
    card = _cards(page)[0]
    assert card._prompt_field.toPlainText() == ""

    page._on_compose_prompt(scene_id, card)

    assert "A turtle on a riverbank" in card._prompt_field.toPlainText()
    assert "Wide shot" in card._prompt_field.toPlainText()


def test_seo_save_round_trips_through_episode_service(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    page._seo_description_en.setPlainText("A fun episode about sharing.")
    page._seo_description_ar.setPlainText("حلقة ممتعة عن المشاركة")
    page._seo_hashtags.setText("#kids, #arabic")
    page._seo_credits.setPlainText("Written by the team")

    page._on_save_seo()

    with gui_context.open_session() as session:
        refreshed = session.get(Episode, episode.id)
        assert refreshed.description_en == "A fun episode about sharing."
        assert refreshed.hashtags == ["#kids", "#arabic"]
        assert refreshed.credits_text == "Written by the team"

    # And the tab reflects the saved state after the round-trip refresh.
    assert page._seo_description_en.toPlainText() == "A fun episode about sharing."


def test_export_tab_buttons_are_disabled_for_a_fresh_episode(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    assert not page._ready_button.isEnabled()
    assert not page._publish_button.isEnabled()


def test_set_episode_retargets_the_page_at_a_different_episode(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_one = _episode(gui_context)
    with gui_context.session_scope() as session:
        episode_two = Episode(
            slug="ep002_test", number=2, title_ar="ع2", title_en="Second Episode", lesson="Patience"
        )
        session.add(episode_two)
        session.flush()
        episode_two_id = episode_two.id

    page = EpisodeWorkspacePage(gui_context, theme, episode_one.id)
    qtbot.addWidget(page)
    assert "Test Episode" in page._header._title_label.text()

    page.set_episode(episode_two_id)

    assert "Second Episode" in page._header._title_label.text()


def test_save_script_on_a_brand_new_episode_persists_without_error(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    """Regression test: on a freshly created episode, the very first
    refresh()'s get_or_create_script used to run in a non-committing
    session, so the newly inserted Script row was rolled back the
    moment refresh() returned — the next Save then hit NotFoundError,
    which _on_save_script's own error handler turned into a blocking
    QMessageBox with no user present to dismiss it (a permanent hang
    under the offscreen test platform). refresh()/_refresh_song_fields
    now use session_scope so the get-or-create actually persists."""
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    page._script_summary.setPlainText("A short summary.")
    page._script_full.setPlainText("A turtle is lost near the lake.")
    page._on_save_script()

    with gui_context.open_session() as session:
        script = gui_context.script_service.get_or_create_script(session, episode.id)
        assert script.full_script == "A turtle is lost near the lake."


def test_music_tab_shows_song_fields_for_a_fresh_episode(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    assert page._song_lyrics.toPlainText() == ""
    assert page._song_duration.text() == ""


def test_save_song_round_trips_through_song_service(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode = _episode(gui_context)
    page = EpisodeWorkspacePage(gui_context, theme, episode.id)
    qtbot.addWidget(page)

    page._song_lyrics.setPlainText("كلمات جديدة")
    page._song_purpose.setPlainText("Teach teamwork.")
    page._song_duration.setText("50")
    page._song_notes.setPlainText("Upbeat.")
    page._song_suno_prompt.setPlainText("Children's pop.")
    page._on_save_song()

    with gui_context.open_session() as session:
        song = gui_context.song_service.get_or_create_song(session, episode.id)
        assert song.lyrics_ar == "كلمات جديدة"
        assert song.duration_seconds == 50
        assert song.suno_style_prompt == "Children's pop."


def test_workspace_loads_real_episode_001_production_content(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    """The Episode Workspace is the one and only way this content is
    meant to be viewed/edited (no parallel workflow) — this proves the
    real Milestone 6 production data actually renders through it."""
    with gui_context.session_scope() as session:
        episode = populate_episode_001_production_content(session)
        episode_id = episode.id

    page = EpisodeWorkspacePage(gui_context, theme, episode_id)
    qtbot.addWidget(page)

    assert "Melissa and Bilsan" in page._header._title_label.text()
    assert len(page._script_full.toPlainText()) > 500

    page._tabs.setCurrentIndex(1)
    cards = _cards(page)
    assert len(cards) == 15
    assert cards[0]._title_label.text() == "Scene 1: صوت غريب عند البحيرة"

    assert "معاً نستطيع" in page._song_lyrics.toPlainText()
    assert page._song_duration.text() == "60"

    assert page._seo_description_ar.toPlainText()
    assert page._seo_hashtags.text()
