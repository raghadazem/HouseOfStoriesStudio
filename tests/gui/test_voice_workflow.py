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


def test_panel_shows_song_scene_line_with_song_badge_and_no_generate_button(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    """A song-scene line must never read as Blocked/Ready, must show a
    Song badge instead, must not offer an ordinary Generate button, and
    must not count toward the scene's ready total -- even though its
    speaker ('الجميع') would otherwise be unresolved."""
    episode_id = _episode(gui_context)
    scene_id = _scene(gui_context, episode_id, "الجميع: معاً نستطيع")
    with gui_context.session_scope() as session:
        gui_context.scene_service.update_scene(session, scene_id, is_song_scene=True)

    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Song" in text for text in labels)
    assert not any("Blocked" in text for text in labels)
    assert not any(text.strip() == "Ready" for text in labels)
    assert any("0/0 ready" in text for text in labels)
    buttons = {btn.text(): btn for btn in panel.findChildren(QPushButton)}
    assert "Generate" not in buttons


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


# --- bird / turtle mother (non-character speaker_key) GUI visibility ---------


def test_profiles_summary_includes_bird_and_turtle_mother_with_approved_active_state(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    """The Voice Profiles summary must show every NON_CHARACTER_SPEAKERS
    entry, not just Characters + Narrator -- Bird and Turtle Mother must
    appear with their own approved/active status, exactly like any other
    speaker, without being hardcoded as unrelated GUI-only rows."""
    from app.core.models.voice_profile import SPEAKER_KEY_BIRD, SPEAKER_KEY_TURTLE_MOTHER

    episode_id = _episode(gui_context)
    with gui_context.session_scope() as session:
        vps = VoiceProfileService()
        for speaker_key in (SPEAKER_KEY_BIRD, SPEAKER_KEY_TURTLE_MOTHER):
            profile = vps.create_voice_profile(
                session, speaker_key=speaker_key, display_name=speaker_key,
                provider_name="mock_provider", provider_voice_id=f"voice-{speaker_key}",
            )
            vps.set_active_voice_profile(session, profile.id)
            ApprovalService().approve_entity(session, "voice_profile", profile.id, decided_by="founder")

    panel = vw.VoiceWorkspacePanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    rows_text = [label.text() for label in panel._profiles_summary.findChildren(QLabel)]
    assert any(text == "Bird" for text in rows_text)
    assert any(text == "Turtle Mother" for text in rows_text)
    bird_status = next(text for text in rows_text if text.startswith("bird ("))
    assert "(approved)" in bird_status
    turtle_mother_status = next(text for text in rows_text if text.startswith("turtle_mother ("))
    assert "(approved)" in turtle_mother_status


# --- MP3 playback (Milestone 9 Creator-tier compatibility fix) ---------------


def test_audio_candidate_tile_plays_mp3_asset(
    qtbot, gui_context: ApplicationContext, tmp_path
) -> None:
    """The existing audio review player must keep working for the new
    default MP3 output, with no visual redesign: AudioCandidateTile /
    QMediaPlayer resolve and accept a real .mp3 Asset's file exactly
    like it already does for .wav -- format-agnostic by construction
    (it only ever calls QUrl.fromLocalFile on the asset's own path)."""
    from PySide6.QtCore import QUrl

    from app.core.ai.generation_job_service import GenerationJobService
    from app.core.db.enums import AssetType
    from app.core.services.asset_import_service import ImportRequest
    from app.gui.widgets import AudioCandidateTile

    mp3_header = bytes([0xFF, 0xFB, 0x90, 0xC0])
    frame_size = 417  # floor(144 * 128000 / 44100)
    mp3_bytes = (mp3_header + bytes(frame_size - len(mp3_header))) * 5
    source_path = tmp_path / "melissa_line.mp3"
    source_path.write_bytes(mp3_bytes)

    episode_id = _episode(gui_context)
    with gui_context.session_scope() as session:
        jobs = GenerationJobService()
        job = jobs.create_job(
            session, workflow_name="voice_line", provider_name="elevenlabs",
            provider_model="eleven_multilingual_v2", batch_id=uuid.uuid4(),
            prompt_text="مرحباً", episode_id=episode_id,
        )
        job = jobs.mark_running(session, job.id)
        asset = gui_context.asset_import_service.import_asset(
            session,
            ImportRequest(
                source_path=source_path, asset_type=AssetType.VOICE,
                episode_id=episode_id, duration_seconds=5 * (1152 / 44100),
                source_tool="elevenlabs",
            ),
        )
        job = jobs.mark_succeeded(session, job.id, result_asset_id=asset.id)
        job_id, asset_id = job.id, asset.id

    with gui_context.open_session() as session:
        from app.core.models import Asset, GenerationJob

        job = session.get(GenerationJob, job_id)
        asset = session.get(Asset, asset_id)
        assert asset.relative_path.endswith(".mp3")

        tile = AudioCandidateTile(
            gui_context, job, asset,
            on_approve=lambda _id: None, on_reject=lambda _id: None,
            on_retry=lambda _id: None, on_cancel=lambda _id: None,
        )
        qtbot.addWidget(tile)

        play_button = tile.findChildren(QPushButton)[0]
        assert play_button.isEnabled()
        play_button.click()

        expected_url = QUrl.fromLocalFile(
            str(gui_context.storage_service.resolve_managed_path(asset.relative_path))
        )
        assert tile._player.source() == expected_url
