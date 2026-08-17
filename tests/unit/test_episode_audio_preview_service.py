"""Tests for EpisodeAudioPreviewService (Milestone 10 Phase 2).

Real ``ffmpeg``/``ffprobe`` calls are monkeypatched out at the
``app.core.ffmpeg_ops`` boundary -- these tests verify the service's
own logic (refusing to render when not assembly-ready, gap-policy
sequencing, result measurement), not that a real ffmpeg binary is
installed. That is proven separately, by hand, per the Milestone 10
Phase 2 preflight, and by one real manual render of Episode 001.
"""

from __future__ import annotations

import uuid
import wave
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core import ffmpeg_ops
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode
from app.core.models.asset import ROLE_FINAL_LINE_VOICE
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_audio_preview_service import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    EpisodeAudioPreviewService,
)
from app.core.services.exceptions import AudioRenderError
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
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


def _make_final_asset(
    session: Session,
    app_config: AppConfig,
    tmp_path,
    line,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    duration_seconds: float | None = 3.0,
    role: str | None = ROLE_FINAL_LINE_VOICE,
) -> Asset:
    storage = StorageService(app_config)
    asset_import = AssetImportService(app_config, storage)
    wav_path = tmp_path / f"voice_{uuid.uuid4().hex}.wav"
    _write_wav(wav_path)

    asset = asset_import.import_asset(
        session,
        ImportRequest(
            source_path=wav_path, asset_type=AssetType.VOICE,
            episode_id=line.scene.episode_id, dialogue_line_id=line.id, source_tool="test",
            duration_seconds=duration_seconds,
        ),
    )
    asset.role = role
    asset.approval_status = approval_status
    session.flush()
    return asset


def _ready_scene(session: Session, ss: SceneService, episode: Episode, dialogue_ar: str, order_index: int = 1):
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar, order_index=order_index)
    lines = ss.sync_dialogue_lines(session, scene.id)
    return scene, lines


def _stub_ffmpeg(monkeypatch: pytest.MonkeyPatch, *, probe_durations: dict[str, float], output_duration: float):
    """Replaces ffmpeg_ops.probe_audio/concat_audio_with_gaps with fakes
    that never touch a real ffmpeg binary. concat_audio_with_gaps
    records the exact input_paths/gap_seconds it was called with and
    writes a placeholder file so output_path.stat() still works."""
    calls: dict = {}

    def fake_probe(path: Path, *, ffprobe_path: str = "ffprobe"):
        key = str(path)
        duration = probe_durations.get(key, output_duration)
        return ffmpeg_ops.AudioStreamProbe(
            codec_name="mp3", sample_rate=TARGET_SAMPLE_RATE, channels=TARGET_CHANNELS,
            channel_layout="mono", duration_seconds=duration, bit_rate=128000,
        )

    def fake_concat(input_paths, gap_seconds, output_path, **kwargs):
        calls["input_paths"] = list(input_paths)
        calls["gap_seconds"] = list(gap_seconds)
        output_path.write_bytes(b"fake-mp3-bytes")
        probe_durations[str(output_path)] = output_duration

    monkeypatch.setattr(ffmpeg_ops, "probe_audio", fake_probe)
    monkeypatch.setattr(ffmpeg_ops, "concat_audio_with_gaps", fake_concat)
    return calls


# --- refuses to render when not assembly-ready ------------------------------


def test_raises_when_episode_has_no_final_asset(session: Session, app_config: AppConfig, tmp_path) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _ready_scene(session, ss, episode, "ميليسا: A1")
    session.commit()

    service = EpisodeAudioPreviewService(config=app_config)
    with pytest.raises(AudioRenderError, match="not assembly-ready"):
        service.render_preview(session, episode.id, tmp_path / "out.mp3")


def test_raises_when_a_final_asset_is_not_approved(session: Session, app_config: AppConfig, tmp_path) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: A1")
    _make_final_asset(session, app_config, tmp_path, lines[0], approval_status=ApprovalStatus.IN_REVIEW)
    session.commit()

    service = EpisodeAudioPreviewService(config=app_config)
    with pytest.raises(AudioRenderError, match="not assembly-ready"):
        service.render_preview(session, episode.id, tmp_path / "out.mp3")


# --- gap sequencing ----------------------------------------------------------


def test_gap_sequence_matches_scene_boundaries(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 lines in scene A (1 same-scene gap), then 2 lines in scene B
    (1 same-scene gap), with 1 scene-boundary gap between A and B --
    3 gaps total for 4 clips, in that exact order."""
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _character(session, "بيلسان", "Bilsan")
    _scene_a, lines_a = _ready_scene(session, ss, episode, "ميليسا: A1\nبيلسان: A2", order_index=1)
    _scene_b, lines_b = _ready_scene(session, ss, episode, "ميليسا: B1\nبيلسان: B2", order_index=2)
    for line in [*lines_a, *lines_b]:
        _make_final_asset(session, app_config, tmp_path, line)
    session.commit()

    calls = _stub_ffmpeg(monkeypatch, probe_durations={}, output_duration=99.0)

    service = EpisodeAudioPreviewService(
        config=app_config, same_scene_gap_seconds=0.45, scene_boundary_gap_seconds=1.25
    )
    output_path = tmp_path / "preview" / "out.mp3"
    result = service.render_preview(session, episode.id, output_path)

    assert calls["gap_seconds"] == pytest.approx([0.45, 1.25, 0.45])
    assert len(calls["input_paths"]) == 4
    assert result.clip_count == 4
    assert result.same_scene_gap_count == 2
    assert result.scene_boundary_gap_count == 1
    assert result.total_gap_seconds == pytest.approx(0.45 + 1.25 + 0.45)


def test_expected_and_measured_duration_and_delta(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: A1\nميليسا: A2", order_index=1)
    for line in lines:
        _make_final_asset(session, app_config, tmp_path, line)
    session.commit()

    probe_durations: dict[str, float] = {}
    _stub_ffmpeg(monkeypatch, probe_durations=probe_durations, output_duration=10.9)

    service = EpisodeAudioPreviewService(
        config=app_config, same_scene_gap_seconds=0.5, scene_boundary_gap_seconds=1.0
    )
    output_path = tmp_path / "out.mp3"

    # Force each clip's probed duration to a known value via the input
    # paths the service actually resolved (only known after the call
    # starts) -- simplest is to patch probe to a fixed per-call value.
    def fake_probe(path: Path, *, ffprobe_path: str = "ffprobe"):
        if str(path) == str(output_path):
            return ffmpeg_ops.AudioStreamProbe(
                codec_name="mp3", sample_rate=TARGET_SAMPLE_RATE, channels=TARGET_CHANNELS,
                channel_layout="mono", duration_seconds=10.9, bit_rate=128000,
            )
        return ffmpeg_ops.AudioStreamProbe(
            codec_name="mp3", sample_rate=TARGET_SAMPLE_RATE, channels=TARGET_CHANNELS,
            channel_layout="mono", duration_seconds=5.0, bit_rate=128000,
        )

    monkeypatch.setattr(ffmpeg_ops, "probe_audio", fake_probe)

    result = service.render_preview(session, episode.id, output_path)

    assert result.total_clip_duration_seconds == pytest.approx(10.0)  # 2 clips x 5.0s
    assert result.total_gap_seconds == pytest.approx(0.5)  # 1 same-scene gap
    assert result.expected_duration_seconds == pytest.approx(10.5)
    assert result.measured_duration_seconds == pytest.approx(10.9)
    assert result.duration_delta_seconds == pytest.approx(0.4)
    assert result.codec_name == "mp3"
    assert result.sample_rate == TARGET_SAMPLE_RATE
    assert result.channels == TARGET_CHANNELS
    assert result.file_size_bytes == len(b"fake-mp3-bytes")
    assert output_path.exists()
