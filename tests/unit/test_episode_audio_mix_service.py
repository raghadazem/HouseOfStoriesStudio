"""Tests for EpisodeAudioMixService (Milestone 10 Phase 5): the song
must be spliced exactly once at the song scene's position, using the
existing scene-boundary gap policy on both sides and never an extra
retained boundary gap; song-scene DialogueLines must never become
audio inputs; every validation gate must refuse cleanly rather than
produce a partial mix; and no source Asset may ever be modified.

Real ffmpeg/ffprobe calls are monkeypatched out at the
``app.core.ffmpeg_ops`` boundary -- these tests verify this service's
own splice/gap/validation logic, not that a real ffmpeg binary is
installed.
"""

from __future__ import annotations

import hashlib
import uuid
import wave
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core import ffmpeg_ops
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode
from app.core.models.asset import ROLE_FINAL_LINE_VOICE, ROLE_FINAL_MUSIC
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_audio_mix_service import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    EpisodeAudioMixService,
)
from app.core.services.exceptions import AudioRenderError
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService


def _episode(session: Session, *, includes_song: bool = True) -> Episode:
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


def _ready_scene(session: Session, ss: SceneService, episode: Episode, dialogue_ar: str, order_index: int):
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar, order_index=order_index)
    lines = ss.sync_dialogue_lines(session, scene.id)
    return scene, lines


def _song_scene(session: Session, ss: SceneService, episode: Episode, order_index: int):
    scene = ss.add_scene(session, episode.id, dialogue_ar="الجميع: كلمات الأغنية", order_index=order_index)
    ss.update_scene(session, scene.id, is_song_scene=True)
    lines = ss.sync_dialogue_lines(session, scene.id)
    return scene, lines


def _music_asset(
    session: Session, app_config: AppConfig, *, episode_id, approved: bool, write_file: bool = True
) -> Asset:
    storage = StorageService(app_config)
    relative_path = f"episodes/x/audio/music/{uuid.uuid4().hex}.mp3"
    if write_file:
        abspath = storage.resolve_managed_path(relative_path)
        abspath.parent.mkdir(parents=True, exist_ok=True)
        abspath.write_bytes(b"fake-song-bytes")
    asset = Asset(
        asset_type=AssetType.MUSIC,
        original_filename="song.mp3",
        relative_path=relative_path,
        checksum=hashlib.sha256(relative_path.encode()).hexdigest(),
        episode_id=episode_id,
        role=ROLE_FINAL_MUSIC,
        approval_status=ApprovalStatus.APPROVED if approved else ApprovalStatus.IN_REVIEW,
        duration_seconds=98.679979,
    )
    session.add(asset)
    session.flush()
    return asset


def _mixable_episode(session: Session, app_config: AppConfig, tmp_path):
    """Scene 1 (2 spoken lines) -> Scene 2 (song scene) -> Scene 3 (2
    spoken lines) -- a minimal mirror of Episode 001's Scene 8/9/10
    topology, with an approved final_music Asset already attached."""
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1\nميليسا: A2", order_index=1)
    for line in lines1:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    song_scene, song_lines = _song_scene(session, ss, episode, order_index=2)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: B1\nميليسا: B2", order_index=3)
    for line in lines3:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    music = _music_asset(session, app_config, episode_id=episode.id, approved=True)
    session.commit()
    return episode, lines1, song_scene, song_lines, lines3, music


def _stub_ffmpeg(monkeypatch: pytest.MonkeyPatch, *, song_duration: float = 98.679979):
    """Replaces ffmpeg_ops.probe_audio/concat_audio_with_gaps with fakes
    that never touch a real ffmpeg binary. concat_audio_with_gaps
    records exactly what it was called with and writes a placeholder
    output file so output_path.stat() still works. All tests in this
    file use ``tmp_path / "mix.mp3"`` as the output path, so probing by
    filename is an unambiguous, non-fragile way to distinguish "the
    rendered output" from a real dialogue/music input."""
    calls: dict = {}

    def fake_probe(path: Path, *, ffprobe_path: str = "ffprobe"):
        path_str = str(path).replace("\\", "/")
        if path.name == "mix.mp3":
            return ffmpeg_ops.AudioStreamProbe(
                codec_name="mp3", sample_rate=TARGET_SAMPLE_RATE, channels=TARGET_CHANNELS,
                channel_layout="stereo", duration_seconds=999.0, bit_rate=128000,
            )
        if "audio/music" in path_str:
            return ffmpeg_ops.AudioStreamProbe(
                codec_name="mp3", sample_rate=48000, channels=2, channel_layout="stereo",
                duration_seconds=song_duration, bit_rate=190000,
            )
        return ffmpeg_ops.AudioStreamProbe(
            codec_name="mp3", sample_rate=44100, channels=1, channel_layout="mono",
            duration_seconds=3.0, bit_rate=128000,
        )

    def fake_concat(input_paths, gap_seconds, output_path, **kwargs):
        calls["input_paths"] = list(input_paths)
        calls["gap_seconds"] = list(gap_seconds)
        calls["kwargs"] = kwargs
        output_path.write_bytes(b"fake-mixed-mp3-bytes")

    monkeypatch.setattr(ffmpeg_ops, "probe_audio", fake_probe)
    monkeypatch.setattr(ffmpeg_ops, "concat_audio_with_gaps", fake_concat)
    return calls


# --- happy path: splice position, ordering, gaps ----------------------------


def test_song_inserted_at_correct_scene_position_and_exactly_once(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    result = service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    input_paths = calls["input_paths"]
    assert len(input_paths) == 5  # 2 dialogue + song + 2 dialogue
    music_positions = [i for i, p in enumerate(input_paths) if "audio/music" in str(p).replace("\\", "/")]
    assert music_positions == [2]  # exactly once, immediately after scene1's 2 lines
    assert result.spoken_clip_count == 4


def test_song_scene_dialoguelines_never_become_audio_inputs(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    # No final_line_voice Asset exists for any song-scene line (by
    # construction, since _song_scene never creates one) -- so the only
    # way a song-scene line's audio could leak into the mix is if this
    # service invented a path for it. It never does: dialogue-typed
    # inputs equal exactly the 4 real spoken lines' asset paths.
    dialogue_inputs = [p for p in calls["input_paths"] if "audio/voice" in str(p).replace("\\", "/")]
    assert len(dialogue_inputs) == 4


def test_all_spoken_lines_preserved(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, lines1, _song_scene_row, _song_lines, lines3, _music = _mixable_episode(session, app_config, tmp_path)
    _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    result = service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    assert result.spoken_clip_count == len(lines1) + len(lines3) == 4


def test_pre_and_post_song_transition_gaps(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(
        config=app_config, same_scene_gap_seconds=0.45, scene_boundary_gap_seconds=1.25
    )
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    gap_seconds = calls["gap_seconds"]
    # order: [same-scene gap within scene1] [1.25 into song] [1.25 out of song] [same-scene gap within scene3]
    assert gap_seconds == pytest.approx([0.45, 1.25, 1.25, 0.45])


def test_no_extra_boundary_gap_between_before_and_after_scenes(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4 dialogue clips + 1 song = 5 segments => exactly 4 gaps, never
    5 (which would mean the old single Scene1->Scene3 boundary gap was
    retained in addition to the two song-transition gaps)."""
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    assert len(calls["gap_seconds"]) == len(calls["input_paths"]) - 1 == 4


def test_no_leading_or_trailing_silence(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    # ffmpeg_ops.concat_audio_with_gaps' own contract (tested separately
    # in test_ffmpeg_ops.py) guarantees no silence before input 0 or
    # after the last input; this asserts this service upholds the
    # gap_seconds length invariant that contract depends on.
    assert len(calls["gap_seconds"]) == len(calls["input_paths"]) - 1


# --- format handling: service requests the right target, not ffmpeg_ops internals ----


def test_requests_stereo_44100_output_regardless_of_source_formats(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mono 44.1kHz dialogue + stereo 48kHz song both go in; the
    service must ask ffmpeg_ops for stereo/44100 output -- the actual
    per-input aformat conversion is ffmpeg_ops' own, already-tested
    responsibility (test_ffmpeg_ops.py), not re-tested here."""
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music = _mixable_episode(session, app_config, tmp_path)
    calls = _stub_ffmpeg(monkeypatch)

    service = EpisodeAudioMixService(config=app_config)
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    assert calls["kwargs"]["sample_rate"] == TARGET_SAMPLE_RATE == 44100
    assert calls["kwargs"]["channels"] == TARGET_CHANNELS == 2


# --- validation gates: refuse cleanly, never a partial mix -----------------


def test_missing_final_music_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1", order_index=1)
    for line in lines1:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _song_scene(session, ss, episode, order_index=2)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: B1", order_index=3)
    for line in lines3:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="not mix-ready"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


def test_unapproved_final_music_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1", order_index=1)
    for line in lines1:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _song_scene(session, ss, episode, order_index=2)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: B1", order_index=3)
    for line in lines3:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _music_asset(session, app_config, episode_id=episode.id, approved=False)
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="not mix-ready"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


def test_missing_physical_music_file_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1", order_index=1)
    for line in lines1:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _song_scene(session, ss, episode, order_index=2)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: B1", order_index=3)
    for line in lines3:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    # approved in the DB, but the physical file is never written
    _music_asset(session, app_config, episode_id=episode.id, approved=True, write_file=False)
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="does not exist on disk"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


def test_dialogue_not_ready_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, _lines1 = _ready_scene(session, ss, episode, "ميليسا: A1", order_index=1)
    # deliberately no final voice asset for scene1's line
    _song_scene(session, ss, episode, order_index=2)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: B1", order_index=3)
    for line in lines3:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _music_asset(session, app_config, episode_id=episode.id, approved=True)
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="not mix-ready"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


def test_ambiguous_topology_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session, includes_song=True)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1", order_index=1)
    for line in lines1:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _song_scene(session, ss, episode, order_index=2)
    _song_scene(session, ss, episode, order_index=3)  # second song scene -> ambiguous
    _scene4, lines4 = _ready_scene(session, ss, episode, "ميليسا: B1", order_index=4)
    for line in lines4:
        _make_final_voice_asset(session, app_config, tmp_path, line)
    _music_asset(session, app_config, episode_id=episode.id, approved=True)
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="ambiguous song-scene topology"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


def test_multiple_approved_final_music_assets_refuses_render(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode, _lines1, _song_scene_row, _song_lines, _lines3, _music1 = _mixable_episode(session, app_config, tmp_path)
    _music_asset(session, app_config, episode_id=episode.id, approved=True)  # a second one
    session.commit()

    service = EpisodeAudioMixService(config=app_config)
    with pytest.raises(AudioRenderError, match="found 2"):
        service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")


# --- data safety --------------------------------------------------------


def test_source_assets_are_never_modified(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode, lines1, _song_scene_row, _song_lines, _lines3, music = _mixable_episode(session, app_config, tmp_path)
    _stub_ffmpeg(monkeypatch)

    voice_asset = (
        session.query(Asset).filter_by(role=ROLE_FINAL_LINE_VOICE, dialogue_line_id=lines1[0].id).one()
    )
    before = {
        "voice_checksum": voice_asset.checksum,
        "voice_relative_path": voice_asset.relative_path,
        "voice_approval": voice_asset.approval_status,
        "music_checksum": music.checksum,
        "music_relative_path": music.relative_path,
        "music_approval": music.approval_status,
        "music_role": music.role,
    }

    service = EpisodeAudioMixService(config=app_config)
    service.render_mix_preview(session, episode.id, tmp_path / "mix.mp3")

    assert voice_asset.checksum == before["voice_checksum"]
    assert voice_asset.relative_path == before["voice_relative_path"]
    assert voice_asset.approval_status == before["voice_approval"]
    assert music.checksum == before["music_checksum"]
    assert music.relative_path == before["music_relative_path"]
    assert music.approval_status == before["music_approval"]
    assert music.role == before["music_role"]
    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_module_never_imports_a_generation_capable_symbol() -> None:
    import inspect

    from app.core.services import episode_audio_mix_service

    source = inspect.getsource(episode_audio_mix_service)
    assert "app.core.ai" not in source
    assert "AIOrchestrator" not in source
    assert "AIProvider" not in source
