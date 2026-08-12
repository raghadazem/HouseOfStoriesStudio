"""Tests for the Voice workspace: readiness, generation, final-take selection.

Every real-generation path here uses ``mock_provider`` — no automated
test calls the real ElevenLabs API (same policy as Milestone 7/8).
"""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from app.core.models import Character, Episode
from app.core.services.approval_service import ApprovalService
from app.core.services.voice_profile_service import VoiceProfileService
from app.gui.context import ApplicationContext
from app.gui.pages import voice_workflow as vw
from app.gui.theme.manager import ThemeManager


def _episode(gui_context: ApplicationContext) -> uuid.UUID:
    with gui_context.session_scope() as session:
        episode = Episode(
            slug=f"ep-{uuid.uuid4().hex[:8]}", number=1, title_ar="ح", title_en="Ep", lesson="L"
        )
        session.add(episode)
        session.flush()
        return episode.id


def _ready_character_voice(
    gui_context: ApplicationContext, slug: str, name_ar: str, name_en: str
) -> uuid.UUID:
    """A Character with an active, approved VoiceProfile.

    ``name_ar`` must match the exact speaker prefix used in the test's
    ``dialogue_ar`` string — SceneService.resolve_speaker matches on
    this field, unlike Milestone 8's fixtures (which only ever needed
    character_id associations, never free-text speaker matching).
    """
    with gui_context.session_scope() as session:
        character = Character(slug=slug, name_ar=name_ar, name_en=name_en)
        session.add(character)
        session.flush()
        vps = VoiceProfileService()
        profile = vps.create_voice_profile(
            session, character_id=character.id, display_name=name_en,
            provider_name="mock_provider", provider_voice_id="voice-1",
        )
        vps.set_active_voice_profile(session, profile.id)
        ApprovalService().approve_entity(session, "voice_profile", profile.id, decided_by="founder")
        return character.id


def _scene(gui_context: ApplicationContext, episode_id: uuid.UUID, dialogue_ar: str) -> uuid.UUID:
    with gui_context.session_scope() as session:
        scene = gui_context.scene_service.add_scene(session, episode_id, dialogue_ar=dialogue_ar)
        return scene.id


@pytest.fixture(autouse=True)
def _no_real_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic regardless of the real machine's ambient environment —
    # see tests/gui/test_dashboard.py's dashboard fixture for the same
    # established pattern.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


# --- panel rendering ---------------------------------------------------------


def test_panel_shows_empty_state_with_no_scenes(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.show()

    panel.refresh(episode_id)

    assert panel._empty_state.isVisible()


def test_panel_shows_blocked_line_with_named_character(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    with gui_context.session_scope() as session:
        character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
        session.add(character)
        session.flush()
    _scene(gui_context, episode_id, "ميليسا: مرحباً")  # no VoiceProfile at all yet

    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Blocked" in text for text in labels)
    buttons = {btn.text(): btn for btn in panel.findChildren(QPushButton)}
    assert buttons["Generate"].isEnabled() is False


def test_panel_shows_ready_line_with_generate_enabled(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    _ready_character_voice(gui_context, "melissa", "ميليسا", "Melissa")
    _scene(gui_context, episode_id, "ميليسا: مرحباً")

    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Ready" in text for text in labels)
    buttons = {btn.text(): btn for btn in panel.findChildren(QPushButton)}
    assert buttons["Generate"].isEnabled() is True


# --- generate dialog ---------------------------------------------------------


def test_generate_dialog_lists_mock_provider_and_shows_authored_text(
    qtbot, gui_context: ApplicationContext
) -> None:
    episode_id = _episode(gui_context)
    _ready_character_voice(gui_context, "melissa", "ميليسا", "Melissa")
    scene_id = _scene(gui_context, episode_id, "ميليسا: مرحباً يا أصدقاء")
    with gui_context.session_scope() as session:
        line = gui_context.scene_service.sync_dialogue_lines(session, scene_id)[0]
        line_id = line.id

    dialog = vw._GenerateVoiceLineDialog(gui_context, line_id)
    qtbot.addWidget(dialog)

    provider_names = [dialog.provider_field.itemData(i) for i in range(dialog.provider_field.count())]
    assert "mock_provider" in provider_names

    request = dialog.build_request(episode_id)
    assert request.dialogue_line_id == line_id
    assert request.candidate_count == 1


# --- candidate review + set as final take -------------------------------------


def test_voice_candidate_review_runs_batch_and_set_as_final_take(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    melissa_id = _ready_character_voice(gui_context, "melissa", "ميليسا", "Melissa")
    scene_id = _scene(gui_context, episode_id, "ميليسا: مرحباً")
    with gui_context.session_scope() as session:
        line = gui_context.scene_service.sync_dialogue_lines(session, scene_id)[0]
        line_id = line.id

    request = vw.VoiceLineBatchRequest(
        provider_name="mock_provider", dialogue_line_id=line_id, episode_id=episode_id, candidate_count=1
    )
    dialog = vw._VoiceCandidateReviewDialog(gui_context, theme, line_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    # AudioCandidateTile (not the image CandidateTile) must back this grid.
    from app.gui.widgets import AudioCandidateTile

    assert dialog.findChildren(AudioCandidateTile)

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    job = jobs[0]
    assert job.dialogue_line_id == line_id
    assert job.parameters["voice_id"] == "voice-1"
    assert job.parameters["speaker_raw"] == "ميليسا"

    dialog._on_approve(job.result_asset_id)
    dialog._on_set_final_take(job.result_asset_id)

    with gui_context.open_session() as session:
        from app.core.models import Asset

        asset = session.get(Asset, job.result_asset_id)
        assert asset.role == "final_line_voice"
        assert asset.duration_seconds == 1.0
    assert dialog.changed is True
    assert melissa_id  # sanity: fixture actually created the character


def test_voice_candidate_review_cancel_pending_job_surfaces_error_without_hanging(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    """Proves _show_error's override routes through this module (not a
    blocking real QMessageBox) — the same regression class Milestone 8's
    shared-widget extraction caught once already."""
    episode_id = _episode(gui_context)
    _ready_character_voice(gui_context, "melissa", "ميليسا", "Melissa")
    scene_id = _scene(gui_context, episode_id, "ميليسا: مرحباً")
    with gui_context.session_scope() as session:
        line_id = gui_context.scene_service.sync_dialogue_lines(session, scene_id)[0].id

    request = vw.VoiceLineBatchRequest(
        provider_name="mock_provider", dialogue_line_id=line_id, episode_id=episode_id, candidate_count=1
    )
    dialog = vw._VoiceCandidateReviewDialog(gui_context, theme, line_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    job_id = jobs[0].id

    errors = []
    monkeypatch.setattr(
        vw, "show_error", lambda _parent, title, message: errors.append((title, message))
    )
    dialog._on_cancel(job_id)  # already succeeded -> can't cancel -> domain error
    assert len(errors) == 1


# --- voice profile manager -----------------------------------------------------


def test_voice_profile_manager_creates_and_activates_profile(
    qtbot, gui_context: ApplicationContext
) -> None:
    with gui_context.session_scope() as session:
        character = Character(slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
        session.add(character)
        session.flush()
        character_id = character.id

    manager = vw._VoiceProfileManagerDialog(
        gui_context, character_id=character_id, speaker_key=None, speaker_label="Bilsan"
    )
    qtbot.addWidget(manager)

    create_dialog = vw._VoiceProfileDialog(gui_context, character_id=character_id, speaker_key=None)
    qtbot.addWidget(create_dialog)
    create_dialog.display_name_field.setText("Bilsan — Playful")
    create_dialog.provider_field.setCurrentIndex(
        create_dialog.provider_field.findData("mock_provider")
    )
    create_dialog.provider_voice_id_field.setText("voice-bilsan")
    assert create_dialog.validate() is None

    with gui_context.session_scope() as session:
        create_dialog.create(session)

    profiles = VoiceProfileService().list_voice_profiles(
        gui_context.open_session(), character_id=character_id
    )
    assert len(profiles) == 1
    assert profiles[0].is_active is False

    with gui_context.session_scope() as session:
        VoiceProfileService().set_active_voice_profile(session, profiles[0].id)

    active = VoiceProfileService().get_active_voice_profile(
        gui_context.open_session(), character_id=character_id
    )
    assert active is not None
    assert active.display_name == "Bilsan — Playful"


# --- narrator (speaker_key) end-to-end ----------------------------------------


def test_narrator_line_is_ready_via_speaker_key_profile(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    from app.core.models.voice_profile import SPEAKER_KEY_NARRATOR

    episode_id = _episode(gui_context)
    with gui_context.session_scope() as session:
        vps = VoiceProfileService()
        profile = vps.create_voice_profile(
            session, speaker_key=SPEAKER_KEY_NARRATOR, display_name="Narrator",
            provider_name="mock_provider", provider_voice_id="voice-narrator",
        )
        vps.set_active_voice_profile(session, profile.id)
        ApprovalService().approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    _scene(gui_context, episode_id, "Narrator: كان يا ما كان")

    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Ready" in text for text in labels)
