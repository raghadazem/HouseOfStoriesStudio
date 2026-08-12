"""Tests for SettingsPage: real theme toggle, workspace/database facts, providers."""

from __future__ import annotations

from app import __version__
from app.core.services.pronunciation_override_service import PronunciationOverrideService
from app.gui.context import ApplicationContext
from app.gui.pages.settings_page import SettingsPage
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager


def test_shows_current_theme(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)
    assert "Light" in page._theme_label.text()
    assert page._theme_button.text() == "Switch to Dark"


def test_toggle_theme_updates_theme_manager_and_persists_setting(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    page._on_toggle_theme()

    assert theme.theme_name == "dark"
    assert gui_settings.load_theme() == "dark"
    assert "Dark" in page._theme_label.text()
    assert page._theme_button.text() == "Switch to Light"


def test_theme_changed_elsewhere_updates_this_pages_labels(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    """The label must stay in sync even when the theme is toggled from
    somewhere else (e.g. the top bar's own toggle button)."""
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    theme.toggle()

    assert "Dark" in page._theme_label.text()


def test_shows_real_workspace_paths(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert str(gui_context.config.db_path) in page._info_text("Database file")


def test_shows_app_version_in_about_section(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert __version__ in page._info_text("Version")


def test_shows_mock_provider_as_configured(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert "mock_provider" in page._info_text("Image generation")


def test_gemini_section_shows_not_configured_without_api_key(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Status") == "Not configured"
    assert page._info_text("Model") == "gemini-3.1-flash-image"


def test_gemini_section_shows_configured_with_api_key_and_never_shows_the_key(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Status") == "Configured"
    all_text = " ".join(label.text() for label in page.findChildren(type(page._theme_label)))
    assert "super-secret-value" not in all_text


def test_gemini_section_reads_model_override_from_env(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.setenv("HOS_GEMINI_IMAGE_MODEL", "gemini-3-pro-image")
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Model") == "gemini-3-pro-image"


# --- ElevenLabs Voice (Milestone 9) -------------------------------------------


def test_elevenlabs_section_shows_not_configured_without_api_key(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Voice Status") == "Not configured"
    assert page._info_text("Voice Model") == "eleven_multilingual_v2"
    # The Gemini section's own keys must stay unaffected by adding this one.
    assert page._info_text("Model") == "gemini-3.1-flash-image"


def test_elevenlabs_section_shows_configured_and_never_shows_the_key(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "super-secret-elevenlabs-value")
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Voice Status") == "Configured"
    all_text = " ".join(label.text() for label in page.findChildren(type(page._theme_label)))
    assert "super-secret-elevenlabs-value" not in all_text


def test_elevenlabs_section_reads_model_override_from_env(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_VOICE_MODEL", "eleven_v3")
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._info_text("Voice Model") == "eleven_v3"


# --- Pronunciation Overrides (Milestone 9) ------------------------------------


def test_pronunciation_overrides_starts_empty(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    assert page._pronunciation_list_layout.count() == 1  # the "No overrides" label


def test_add_pronunciation_override_via_gui(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    page._pronunciation_term_field.setText("تورتور")
    page._pronunciation_replacement_field.setText("طُرطُر")
    page._on_add_pronunciation_override()

    with gui_context.open_session() as session:
        overrides = PronunciationOverrideService().list_overrides(session)
    assert [(o.term, o.replacement) for o in overrides] == [("تورتور", "طُرطُر")]
    # Fields clear after a successful add.
    assert page._pronunciation_term_field.text() == ""


def test_add_pronunciation_override_rejects_empty_fields(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings, monkeypatch
) -> None:
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)
    errors = []
    monkeypatch.setattr(
        "app.gui.pages.settings_page.show_error",
        lambda _parent, title, message: errors.append((title, message)),
    )

    page._on_add_pronunciation_override()

    assert len(errors) == 1
    with gui_context.open_session() as session:
        assert PronunciationOverrideService().list_overrides(session) == []


def test_remove_pronunciation_override_via_gui(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, gui_settings: AppSettings
) -> None:
    with gui_context.session_scope() as session:
        override = PronunciationOverrideService().create_override(
            session, term="تورتور", replacement="طُرطُر"
        )
        override_id = override.id
    page = SettingsPage(gui_context, theme, gui_settings)
    qtbot.addWidget(page)

    page._on_remove_pronunciation_override(override_id)

    with gui_context.open_session() as session:
        assert PronunciationOverrideService().list_overrides(session) == []
