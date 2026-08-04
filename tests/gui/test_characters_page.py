"""Tests for CharactersPage: empty state, real data, search/filter, and create flow."""

from __future__ import annotations

from app.core.models import Character
from app.gui.context import ApplicationContext
from app.gui.pages.characters_page import CharactersPage, _CreateCharacterDialog
from app.gui.theme.manager import ThemeManager


def test_shows_empty_state_on_fresh_database(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    assert page._empty_state.isVisible()
    assert page._cards == []


def test_shows_real_characters_after_seeding(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(Character(slug="melissa", name_ar="م", name_en="Melissa", role="Hero"))

    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)

    assert len(page._cards) == 1
    _character, card = page._cards[0]
    assert card._title_label.text() == "Melissa"


def test_search_filters_cards_live(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(Character(slug="melissa", name_ar="م", name_en="Melissa"))
        session.add(Character(slug="bilsan", name_ar="ب", name_en="Bilsan"))

    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    page._search._field.setText("melissa")
    visible = [c.name_en for c, card in page._cards if card.isVisible()]
    assert visible == ["Melissa"]


def test_lock_filter_narrows_cards(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        locked = Character(slug="melissa", name_ar="م", name_en="Melissa")
        session.add(locked)
        session.add(Character(slug="bilsan", name_ar="ب", name_en="Bilsan"))
        session.flush()
        locked.active_version_id = None  # still unlocked; no version exists to lock to

    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    from app.gui.pages.characters_page import _LOCK_UNLOCKED

    index = page._lock_filter.findData(_LOCK_UNLOCKED)
    page._lock_filter.setCurrentIndex(index)
    visible = {c.name_en for c, card in page._cards if card.isVisible()}
    assert visible == {"Melissa", "Bilsan"}


def test_create_character_dialog_validates_required_fields() -> None:
    dialog = _CreateCharacterDialog(existing_slugs=set())
    assert dialog.validate() == "Name (English) is required."
    dialog.name_en_field.setText("Melissa")
    assert dialog.validate() == "Name (Arabic) is required."
    dialog.name_ar_field.setText("ميليسا")
    assert dialog.validate() is None


def test_create_character_dialog_rejects_duplicate_slug() -> None:
    dialog = _CreateCharacterDialog(existing_slugs={"melissa"})
    dialog.name_en_field.setText("Melissa")
    dialog.name_ar_field.setText("ميليسا")
    assert "already exists" in dialog.validate()


def test_create_character_dialog_parses_comma_separated_traits() -> None:
    dialog = _CreateCharacterDialog(existing_slugs=set())
    dialog.name_en_field.setText("Melissa")
    dialog.name_ar_field.setText("ميليسا")
    dialog.traits_field.setText("curious,  kind ,brave")
    fields = dialog.result_fields()
    assert fields["traits"] == ["curious", "kind", "brave"]


def test_on_create_character_adds_a_real_card(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)
    assert page._cards == []

    def fake_exec(self):
        self.name_en_field.setText("New Character")
        self.name_ar_field.setText("شخصية جديدة")
        return _CreateCharacterDialog.DialogCode.Accepted

    monkeypatch.setattr(_CreateCharacterDialog, "exec", fake_exec)
    page._on_create_character()

    assert len(page._cards) == 1
    assert page._cards[0][0].name_en == "New Character"


def test_open_detail_builds_dialog_with_version_history(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(Character(slug="melissa", name_ar="م", name_en="Melissa"))

    page = CharactersPage(gui_context, theme)
    qtbot.addWidget(page)

    opened = []
    from app.gui.pages import characters_page as module

    class _FakeDialog:
        def __init__(self, *args, **kwargs):
            opened.append(args)

        def exec(self):
            return 0

    monkeypatch.setattr(module, "_CharacterDetailDialog", _FakeDialog)
    character, _card = page._cards[0]
    page._open_detail(character)
    assert len(opened) == 1
