"""Tests for app.core.ffmpeg_ops -- the thin subprocess wrapper over
ffmpeg/ffprobe. Every ``subprocess.run`` call is mocked: these tests
verify command construction and error handling, not that a real
ffmpeg binary is installed (that is proven separately, by hand, per
the Milestone 10 Phase 2 preflight)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.core import ffmpeg_ops


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)


def _probe_json(*, codec="mp3", sample_rate="44100", channels=1, layout="mono", duration="3.5", bit_rate="128000"):
    return json.dumps(
        {
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": codec,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "channel_layout": layout,
                }
            ],
            "format": {"duration": duration, "bit_rate": bit_rate},
        }
    )


# --- probe_audio -----------------------------------------------------------


def test_probe_audio_parses_ffprobe_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        assert "-show_streams" in cmd
        return _completed(stdout=_probe_json())

    monkeypatch.setattr(subprocess, "run", fake_run)

    probe = ffmpeg_ops.probe_audio(Path("clip.mp3"))

    assert probe.codec_name == "mp3"
    assert probe.sample_rate == 44100
    assert probe.channels == 1
    assert probe.channel_layout == "mono"
    assert probe.duration_seconds == pytest.approx(3.5)
    assert probe.bit_rate == 128000


def test_probe_audio_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ffmpeg_ops.FfmpegError, match="not found"):
        ffmpeg_ops.probe_audio(Path("clip.mp3"))


def test_probe_audio_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return _completed(returncode=1, stderr="invalid data found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ffmpeg_ops.FfmpegError, match="invalid data found"):
        ffmpeg_ops.probe_audio(Path("clip.mp3"))


def test_probe_audio_raises_when_no_audio_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return _completed(stdout=json.dumps({"streams": [], "format": {}}))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ffmpeg_ops.FfmpegError, match="No audio stream"):
        ffmpeg_ops.probe_audio(Path("clip.mp3"))


def test_probe_audio_handles_non_ascii_arabic_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file with Arabic ID3 tags (title/artist/lyrics) must probe
    cleanly -- this is exactly the shape of ffprobe's real JSON output
    for the approved Episode 001 song file, which triggered a
    UnicodeDecodeError under Windows' cp1255 default subprocess
    decoding before the explicit encoding="utf-8" fix."""
    data = {
        "streams": [
            {
                "codec_type": "audio", "codec_name": "mp3", "sample_rate": "48000",
                "channels": 2, "channel_layout": "stereo",
            }
        ],
        "format": {
            "duration": "98.679979",
            "bit_rate": "192367",
            "tags": {
                "title": "مَعًا نَسْتَطِيعْ",
                "artist": "ragadazeem",
                "comment": "made with suno",
                "lyrics-eng": "[Verse 1 — ميليسا وَبَيْلَسان]\nمَعًا مَعًا، خُطْوَةً خُطْوَة",
            },
        },
    }

    def fake_run(cmd, **kwargs):
        return _completed(stdout=json.dumps(data, ensure_ascii=False))

    monkeypatch.setattr(subprocess, "run", fake_run)

    probe = ffmpeg_ops.probe_audio(Path("مَعًا نَسْتَطِيعْ.mp3"))

    assert probe.codec_name == "mp3"
    assert probe.duration_seconds == pytest.approx(98.679979)
    assert probe.sample_rate == 48000
    assert probe.channels == 2


def test_run_passes_explicit_utf8_encoding_to_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard for the exact cp1255 crash: subprocess.run must
    always be called with an explicit encoding, never left to the OS
    locale's default codepage."""
    captured_kwargs: dict = {}

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return _completed(stdout=_probe_json())

    monkeypatch.setattr(subprocess, "run", fake_run)

    ffmpeg_ops.probe_audio(Path("clip.mp3"))

    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"
    assert captured_kwargs["text"] is True


# --- run_ffmpeg --------------------------------------------------------------


def test_run_ffmpeg_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return _completed(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ffmpeg_ops.FfmpegError, match="boom"):
        ffmpeg_ops.run_ffmpeg(["-i", "x.mp3", "out.mp3"])


# --- concat_audio_with_gaps --------------------------------------------------


def test_concat_rejects_empty_input_paths() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ffmpeg_ops.concat_audio_with_gaps([], [], Path("out.mp3"))


def test_concat_rejects_wrong_gap_count() -> None:
    with pytest.raises(ValueError, match="exactly 1 entries"):
        ffmpeg_ops.concat_audio_with_gaps(
            [Path("a.mp3"), Path("b.mp3")], [0.1, 0.2], Path("out.mp3")
        )


def test_concat_builds_one_gap_per_boundary_no_leading_or_trailing_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 clips, 2 gaps: exactly 5 ffmpeg inputs (3 real + 2 generated
    silence), silence strictly between clips, single deterministic
    filter_complex, MP3/44100/128k output spec."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    ffmpeg_ops.concat_audio_with_gaps(
        [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")],
        [0.45, 1.25],
        Path("out.mp3"),
        sample_rate=44100,
        channels=1,
        bitrate="128k",
    )

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert cmd.count("-i") == 5  # 3 real clips + 2 generated silence segments
    assert "a.mp3" in cmd and "b.mp3" in cmd and "c.mp3" in cmd
    assert cmd.count("anullsrc=r=44100:cl=mono") == 2
    assert "0.450000" in cmd
    assert "1.250000" in cmd

    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert filter_complex.endswith("concat=n=5:v=0:a=1[out]")
    # Leading/trailing segments in the concat chain are the real clips
    # (labels a0 and a4), never a generated-silence label.
    assert filter_complex.split(";")[-1].startswith("[a0][a1][a2][a3][a4]")

    assert cmd[-1] == "out.mp3"
    assert "-map" in cmd and cmd[cmd.index("-map") + 1] == "[out]"
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "libmp3lame"
    assert "-b:a" in cmd and cmd[cmd.index("-b:a") + 1] == "128k"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "44100"
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"


def test_concat_single_clip_needs_no_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    ffmpeg_ops.concat_audio_with_gaps([Path("only.mp3")], [], Path("out.mp3"))

    cmd = captured["cmd"]
    assert cmd.count("-i") == 1
    assert "anullsrc" not in " ".join(cmd)
