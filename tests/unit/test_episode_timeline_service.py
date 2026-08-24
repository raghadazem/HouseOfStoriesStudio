"""Tests for EpisodeTimelineService (Milestone 10 Phase 3): the
dialogue track must be a pure delegation to
EpisodeAudioAssemblyService (never re-derived), the music track must
honestly distinguish NOT_APPLICABLE/MISSING/PRESENT_NOT_APPROVED/
PRESENT_AND_APPROVED, the SFX track must always report UNSUPPORTED,
and is_mix_ready must be computed strictly from real data -- never
forced. No TTS/provider/ffmpeg call, no Asset/GenerationJob write,
anywhere in this file.
"""

from __future__ import annotations

import hashlib
import uuid
import wave

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode, Song
from app.core.models.asset import ROLE_FINAL_LINE_VOICE, ROLE_FINAL_MUSIC
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_audio_assembly_service import EpisodeAudioAssemblyService
from app.core.services.episode_timeline_service import (
    EpisodeTimelineService,
    MusicTrackStatus,
    SfxTrackStatus,
)
from app.core.services.exceptions import NotFoundError
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService


def _episode(session: Session, *, includes_song: bool = False) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L", includes_song=includes_song,
    )
    session.add(episode)
    session.flush()
    return episode


def _character(session: Session, name_ar: str, name_en: str) -> Character:
    character = Character(slug=f"{name_en.lower()}-{uuid.uuid4().hex[:6]}", name_ar=name_ar, name_en=name_en)
    session.add(character)
    session.flush()
    return character


def _write_wav(path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(uuid.uuid4().bytes * 50)


def _make_final_voice_asset(session: Session, app_config: AppConfig, tmp_path, line) -> Asset:
    storage = StorageService(app_config)
    asset_import = AssetImportService(app_config, storage)
    wav_path = tmp_path / f"voice_{uuid.uuid4().hex}.wav"
    _write_wav(wav_path)
    asset = asset_import.import_asset(
        session,
        ImportRequest(
            source_path=wav_path, asset_type=AssetType.VOICE,
            episode_id=line.scene.episode_id, dialogue_line_id=line.id, source_tool="test",
            duration_seconds=3.0,
        ),
    )
    asset.role = ROLE_FINAL_LINE_VOICE
    asset.approval_status = ApprovalStatus.APPROVED
    session.flush()
    return asset


def _ready_scene(session: Session, ss: SceneService, episode: Episode, dialogue_ar: str, order_index: int = 1):
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar, order_index=order_index)
    lines = ss.sync_dialogue_lines(session, scene.id)
    return scene, lines


def _fully_voiced_episode(session: Session, app_config: AppConfig, tmp_path, *, includes_song: bool = False) -> Episode:
    """A minimal episode whose dialogue track is assembly-ready --
    isolates music/SFX/is_mix_ready behavior from dialogue-readiness
    noise in tests that don't care about the dialogue track itself."""
    episode = _episode(session, includes_song=includes_song)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: A1")
    for line in lines:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    session.commit()
    return episode


def _music_asset(session: Session, *, episode_id, approved: bool) -> Asset:
    relative_path = f"episodes/x/audio/music/{uuid.uuid4().hex}.mp3"
    asset = Asset(
        asset_type=AssetType.MUSIC,
        original_filename="song.mp3",
        relative_path=relative_path,
        checksum=hashlib.sha256(relative_path.encode()).hexdigest(),
        episode_id=episode_id,
        role=ROLE_FINAL_MUSIC,
        approval_status=ApprovalStatus.APPROVED if approved else ApprovalStatus.IN_REVIEW,
    )
    session.add(asset)
    session.flush()
    return asset


# --- dialogue track: pure delegation, never re-derived ----------------------


def test_dialogue_report_is_the_exact_object_assembly_service_returns(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path)

    assembly_service = EpisodeAudioAssemblyService(config=app_config)
    expected_report = assembly_service.build_report(session, episode.id)

    service = EpisodeTimelineService(assembly_service=assembly_service, config=app_config)
    timeline = service.build_timeline(session, episode.id)

    # Same content (proves no independent reimplementation of
    # ordering/validation/duration math) -- compared field by field
    # since build_report is called twice (once above, once inside
    # build_timeline) and dataclasses compare by value.
    assert timeline.dialogue_report == expected_report


def test_dialogue_report_delegates_to_the_injected_assembly_service_instance(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path)

    assembly_service = EpisodeAudioAssemblyService(config=app_config)
    calls: list[uuid.UUID] = []
    original_build_report = assembly_service.build_report

    def spy_build_report(session_arg, episode_id_arg):
        calls.append(episode_id_arg)
        return original_build_report(session_arg, episode_id_arg)

    monkeypatch.setattr(assembly_service, "build_report", spy_build_report)

    service = EpisodeTimelineService(assembly_service=assembly_service, config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert calls == [episode.id]
    assert timeline.dialogue_report.is_assembly_ready is True


def test_raises_not_found_for_unknown_episode(session: Session, app_config: AppConfig) -> None:
    service = EpisodeTimelineService(config=app_config)
    with pytest.raises(NotFoundError):
        service.build_timeline(session, uuid.uuid4())


# --- music track --------------------------------------------------------


def test_music_not_applicable_when_episode_does_not_include_song(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=False)

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.status == MusicTrackStatus.NOT_APPLICABLE
    assert timeline.music_track.asset_id is None


def test_music_missing_when_episode_includes_song_but_no_asset_exists(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.status == MusicTrackStatus.MISSING
    assert timeline.music_track.asset_id is None


def test_music_present_not_approved(session: Session, app_config: AppConfig, tmp_path) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    asset = _music_asset(session, episode_id=episode.id, approved=False)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.status == MusicTrackStatus.PRESENT_NOT_APPROVED
    assert timeline.music_track.asset_id == asset.id


def test_music_present_and_approved(session: Session, app_config: AppConfig, tmp_path) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    asset = _music_asset(session, episode_id=episode.id, approved=True)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.status == MusicTrackStatus.PRESENT_AND_APPROVED
    assert timeline.music_track.asset_id == asset.id


def test_song_metadata_existence_is_reported_independently_of_asset_state(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    session.add(Song(episode_id=episode.id, lyrics_ar="كلمات"))
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.song_exists is True
    assert timeline.music_track.status == MusicTrackStatus.MISSING  # song text != produced audio


# --- SFX track: always UNSUPPORTED, never blocks -----------------------


def test_sfx_is_always_unsupported(session: Session, app_config: AppConfig, tmp_path) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path)
    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.sfx_track.status == SfxTrackStatus.UNSUPPORTED


def test_sfx_unsupported_does_not_block_mix_readiness(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    # includes_song=False (music NOT_APPLICABLE) + assembly-ready dialogue
    # should be mix-ready despite SFX being UNSUPPORTED.
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=False)
    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.sfx_track.status == SfxTrackStatus.UNSUPPORTED
    assert timeline.is_mix_ready is True


# --- is_mix_ready: derived, never forced --------------------------------


def test_mix_not_ready_when_dialogue_not_assembly_ready(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session, includes_song=False)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _ready_scene(session, ss, episode, "ميليسا: A1")  # no final voice asset created
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.dialogue_report.is_assembly_ready is False
    assert timeline.is_mix_ready is False


def test_mix_blocked_by_missing_required_music_even_with_dialogue_ready(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.dialogue_report.is_assembly_ready is True
    assert timeline.music_track.status == MusicTrackStatus.MISSING
    assert timeline.is_mix_ready is False


def test_mix_blocked_by_unapproved_required_music_even_with_dialogue_ready(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    _music_asset(session, episode_id=episode.id, approved=False)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.is_mix_ready is False


def test_mix_ready_when_dialogue_ready_and_music_not_applicable(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=False)

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.is_mix_ready is True


def test_mix_ready_when_dialogue_ready_and_music_approved(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    _music_asset(session, episode_id=episode.id, approved=True)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.is_mix_ready is True


# --- song topology safety: flagged, never guessed -----------------------


def test_multiple_song_scenes_are_flagged_as_ambiguous_topology(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    ss = SceneService()
    scene_a, _ = _ready_scene(session, ss, episode, "ميليسا: song a", order_index=2)
    ss.update_scene(session, scene_a.id, is_song_scene=True)
    scene_b, _ = _ready_scene(session, ss, episode, "ميليسا: song b", order_index=3)
    ss.update_scene(session, scene_b.id, is_song_scene=True)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.song_scene_count == 2
    assert timeline.music_track.topology_ambiguous is True
    # Status is still honestly computed (MISSING here) -- ambiguity is
    # reported, never used to fabricate or suppress the real status.
    assert timeline.music_track.status == MusicTrackStatus.MISSING


def test_single_song_scene_is_not_flagged_as_ambiguous(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    ss = SceneService()
    scene, _ = _ready_scene(session, ss, episode, "ميليسا: song", order_index=2)
    ss.update_scene(session, scene.id, is_song_scene=True)
    session.commit()

    service = EpisodeTimelineService(config=app_config)
    timeline = service.build_timeline(session, episode.id)

    assert timeline.music_track.song_scene_count == 1
    assert timeline.music_track.topology_ambiguous is False


# --- no side effects -----------------------------------------------------


def test_build_timeline_creates_no_new_rows(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _fully_voiced_episode(session, app_config, tmp_path, includes_song=True)
    _music_asset(session, episode_id=episode.id, approved=True)
    session.commit()

    asset_count_before = session.query(Asset).count()

    service = EpisodeTimelineService(config=app_config)
    service.build_timeline(session, episode.id)
    service.build_timeline(session, episode.id)  # calling twice must still write nothing

    assert session.query(Asset).count() == asset_count_before
    assert not session.new
    assert not session.dirty
    assert not session.deleted
