"""Tests for EpisodeAudioAssemblyService (Milestone 10 Phase 1):
deterministic ordering, per-line validation, song exclusion, and the
predicted-preview-duration formula. No real ElevenLabs call anywhere in
this file -- most tests never even touch a provider/orchestrator, since
this service has none.
"""

from __future__ import annotations

import inspect
import uuid
import wave

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.generation_job_service import GenerationJobService
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode
from app.core.models.asset import ROLE_FINAL_LINE_VOICE
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_audio_assembly_service import (
    DEFAULT_SAME_SCENE_GAP_SECONDS,
    DEFAULT_SCENE_BOUNDARY_GAP_SECONDS,
    EpisodeAudioAssemblyService,
)
from app.core.services.exceptions import NotFoundError
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
        wav_file.writeframes(uuid.uuid4().bytes * 50)  # unique bytes -> unique checksum


def _make_final_asset(
    session: Session,
    app_config: AppConfig,
    tmp_path,
    line,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    duration_seconds: float | None = 3.0,
    write_file: bool = True,
    role: str | None = ROLE_FINAL_LINE_VOICE,
    provider_name: str | None = None,
    model_id: str | None = None,
    provider_model: str | None = None,
) -> Asset:
    """Directly constructs an Asset in whatever state a test needs --
    including states the real approval workflow would never itself
    produce (e.g. two finals for one line, an unapproved final) --
    deliberately, since those are exactly the defensive cases this
    service's validation must catch."""
    storage = StorageService(app_config)
    asset_import = AssetImportService(app_config, storage)
    wav_path = tmp_path / f"voice_{uuid.uuid4().hex}.wav"
    if write_file:
        _write_wav(wav_path)
    else:
        wav_path.write_bytes(b"not-a-real-file-and-will-be-deleted")

    asset = asset_import.import_asset(
        session,
        ImportRequest(
            source_path=wav_path, asset_type=AssetType.VOICE,
            episode_id=line.scene.episode_id, dialogue_line_id=line.id, source_tool="test",
            duration_seconds=duration_seconds,
        ),
    )
    if not write_file:
        (app_config.production_dir / asset.relative_path).unlink()

    asset.role = role
    asset.approval_status = approval_status

    if provider_name is not None or model_id is not None:
        jobs = GenerationJobService()
        job = jobs.create_job(
            session, workflow_name="voice_line", provider_name=provider_name or "elevenlabs",
            provider_model=provider_model, batch_id=uuid.uuid4(), prompt_text="x",
            parameters={"model_id": model_id} if model_id else {},
            dialogue_line_id=line.id, episode_id=line.scene.episode_id,
        )
        jobs.mark_running(session, job.id)
        jobs.mark_succeeded(session, job.id, result_asset_id=asset.id)
        asset.generation_job_id = job.id

    session.flush()
    return asset


def _ready_scene(session: Session, ss: SceneService, episode: Episode, dialogue_ar: str, order_index: int = 0, is_song_scene: bool = False):
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar, order_index=order_index)
    if is_song_scene:
        ss.update_scene(session, scene.id, is_song_scene=True)
    lines = ss.sync_dialogue_lines(session, scene.id)
    return scene, lines


# --- ordering -------------------------------------------------------------


def test_ordering_is_by_scene_and_line_order_index_not_incidental(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _character(session, "بيلسان", "Bilsan")

    # Deliberately insert what becomes scene 2 FIRST (at order_index=1),
    # then insert what becomes scene 1 at order_index=1, shifting the
    # first one down to 2 -- proving ordering never depends on
    # insertion/incidental DB order, only on order_index.
    _scene2, lines2 = _ready_scene(session, ss, episode, "ميليسا: B1\nبيلسان: B2", order_index=1)
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: A1\nبيلسان: A2", order_index=1)
    for line in [*lines1, *lines2]:
        _make_final_asset(session, app_config, tmp_path, line)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert [s.authored_text for s in report.sources] == ["A1", "A2", "B1", "B2"]
    assert [s.scene_order_index for s in report.sources] == [1, 1, 2, 2]
    assert [s.dialogue_line_order_index for s in report.sources] == [0, 1, 0, 1]


def test_evaluate_raises_not_found_for_unknown_episode(session: Session, app_config: AppConfig) -> None:
    service = EpisodeAudioAssemblyService(config=app_config)
    with pytest.raises(NotFoundError):
        service.build_report(session, uuid.uuid4())


# --- song exclusion ---------------------------------------------------------


def test_song_scene_lines_are_excluded_and_counted_separately(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")

    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: مرحباً", order_index=1)
    _song_scene, song_lines = _ready_scene(
        session, ss, episode, "ميليسا: نشيد\nميليسا: نشيد 2", order_index=2, is_song_scene=True
    )
    for line in lines1:
        _make_final_asset(session, app_config, tmp_path, line)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.spoken_line_count == 1
    assert report.song_line_count_excluded == 2
    assert all(s.dialogue_line_id not in {line.id for line in song_lines} for s in report.sources)


# --- validation --------------------------------------------------------------


def test_missing_final_asset_marks_source_invalid_and_not_ready(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, _lines = _ready_scene(session, ss, episode, "ميليسا: بلا صوت", order_index=1)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.spoken_line_count == 1
    assert report.valid_source_count == 0
    assert report.is_assembly_ready is False
    assert not report.sources[0].is_valid
    assert "no final_line_voice asset exists" in report.sources[0].validation_errors[0]


def test_duplicate_final_assets_marks_source_invalid(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: مكرر", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0])
    _make_final_asset(session, app_config, tmp_path, lines[0])
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.is_assembly_ready is False
    assert not report.sources[0].is_valid
    assert "2 final_line_voice assets exist" in report.sources[0].validation_errors[0]


def test_unapproved_final_role_asset_marks_source_invalid(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: غير معتمد", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0], approval_status=ApprovalStatus.DRAFT)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.is_assembly_ready is False
    assert any("not approved" in e for e in report.sources[0].validation_errors)


def test_missing_physical_file_marks_source_invalid(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: ملف مفقود", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0], write_file=False)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.is_assembly_ready is False
    assert any("does not exist on disk" in e for e in report.sources[0].validation_errors)


@pytest.mark.parametrize("bad_duration", [None, 0, -1.0])
def test_missing_or_invalid_duration_marks_source_invalid(
    session: Session, app_config: AppConfig, tmp_path, bad_duration
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: مدة غير صالحة", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0], duration_seconds=bad_duration)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.is_assembly_ready is False
    assert any("invalid duration_seconds" in e for e in report.sources[0].validation_errors)


def test_valid_source_exposes_full_provenance(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: صحيح", order_index=1)
    asset = _make_final_asset(
        session, app_config, tmp_path, lines[0], duration_seconds=4.2,
        provider_name="elevenlabs", model_id="eleven_multilingual_v2",
    )
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    source = report.sources[0]
    assert source.is_valid
    assert source.asset_id == asset.id
    assert source.duration_seconds == 4.2
    assert source.relative_path == asset.relative_path
    assert source.absolute_path == app_config.production_dir / asset.relative_path
    assert source.provider_name == "elevenlabs"
    assert source.model_id == "eleven_multilingual_v2"


def test_tortor_scene7_style_v3_provenance_is_surfaced_correctly(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """Not the real Tortor line -- a synthetic line shaped like it
    (eleven_v3 model_id in provenance) -- proving the read model
    surfaces whichever model/provider actually produced the approved
    take, without this service knowing anything about
    LinePerformanceOverride/eleven_v3 as concepts."""
    episode = _episode(session)
    ss = SceneService()
    _character(session, "طُرطُر", "Tortor")
    _scene, lines = _ready_scene(session, ss, episode, "طُرطُر: هاها", order_index=1)
    asset = _make_final_asset(
        session, app_config, tmp_path, lines[0],
        provider_name="elevenlabs", model_id="eleven_v3",
    )
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.sources[0].is_valid
    assert report.sources[0].asset_id == asset.id
    assert report.sources[0].model_id == "eleven_v3"


def test_historical_rejected_asset_is_ignored_current_final_still_used(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """A superseded/rejected DRAFT asset for the same line (never given
    the final role) must never be picked up -- only the one Asset
    actually holding role=final_line_voice matters."""
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: نهائي", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0], role=None, approval_status=ApprovalStatus.DRAFT)
    final_asset = _make_final_asset(session, app_config, tmp_path, lines[0])
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.sources[0].is_valid
    assert report.sources[0].asset_id == final_asset.id


# --- duration / boundary math -------------------------------------------------


def test_total_source_duration_sums_only_valid_sources(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: أ\nميليسا: ب", order_index=1)
    _make_final_asset(session, app_config, tmp_path, lines[0], duration_seconds=2.0)
    # lines[1] left without any final asset -- invalid, must not count toward the sum.
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.total_source_duration_seconds == 2.0
    assert report.is_assembly_ready is False


def test_same_scene_boundary_gap_between_two_lines_in_one_scene(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene, lines = _ready_scene(session, ss, episode, "ميليسا: أ\nميليسا: ب", order_index=1)
    for line in lines:
        _make_final_asset(session, app_config, tmp_path, line, duration_seconds=1.0)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.same_scene_boundary_count == 1
    assert report.scene_boundary_count == 0
    assert report.predicted_silence_seconds == pytest.approx(DEFAULT_SAME_SCENE_GAP_SECONDS)
    assert report.predicted_preview_duration_seconds == pytest.approx(2.0 + DEFAULT_SAME_SCENE_GAP_SECONDS)


def test_scene_boundary_gap_between_two_scenes(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: أ", order_index=1)
    _scene2, lines2 = _ready_scene(session, ss, episode, "ميليسا: ب", order_index=2)
    for line in [*lines1, *lines2]:
        _make_final_asset(session, app_config, tmp_path, line, duration_seconds=1.0)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.same_scene_boundary_count == 0
    assert report.scene_boundary_count == 1
    assert report.predicted_silence_seconds == pytest.approx(DEFAULT_SCENE_BOUNDARY_GAP_SECONDS)


def test_no_double_gap_at_a_scene_boundary_with_multiple_lines_each_side(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """3 lines in scene 1, 2 lines in scene 2: exactly 2 same-scene gaps
    (within scene 1) + 1 same-scene gap (within scene 2) + exactly ONE
    scene-boundary gap at the join -- never a same-scene AND a
    scene-boundary gap stacked at the same point."""
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: أ\nميليسا: ب\nميليسا: ج", order_index=1)
    _scene2, lines2 = _ready_scene(session, ss, episode, "ميليسا: د\nميليسا: هـ", order_index=2)
    for line in [*lines1, *lines2]:
        _make_final_asset(session, app_config, tmp_path, line, duration_seconds=1.0)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert report.same_scene_boundary_count == 3  # 2 within scene1 + 1 within scene2
    assert report.scene_boundary_count == 1
    assert len(report.sources) == 5
    expected_silence = 3 * DEFAULT_SAME_SCENE_GAP_SECONDS + 1 * DEFAULT_SCENE_BOUNDARY_GAP_SECONDS
    assert report.predicted_silence_seconds == pytest.approx(expected_silence)
    assert report.predicted_preview_duration_seconds == pytest.approx(5.0 + expected_silence)


def test_scene_boundary_gap_across_an_excluded_song_scene(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """A song scene between two spoken scenes contributes zero sources
    of its own, but the two spoken lines on either side of it still get
    exactly one scene-boundary gap between them -- not zero, not two."""
    episode = _episode(session)
    ss = SceneService()
    _character(session, "ميليسا", "Melissa")
    _scene1, lines1 = _ready_scene(session, ss, episode, "ميليسا: أ", order_index=1)
    _ready_scene(session, ss, episode, "ميليسا: نشيد", order_index=2, is_song_scene=True)
    _scene3, lines3 = _ready_scene(session, ss, episode, "ميليسا: ب", order_index=3)
    for line in [*lines1, *lines3]:
        _make_final_asset(session, app_config, tmp_path, line, duration_seconds=1.0)
    session.commit()

    report = EpisodeAudioAssemblyService(config=app_config).build_report(session, episode.id)

    assert len(report.sources) == 2
    assert report.same_scene_boundary_count == 0
    assert report.scene_boundary_count == 1


# --- no-provider boundary -----------------------------------------------------


def test_module_never_imports_a_generation_capable_symbol() -> None:
    """Regression guard: this service must never gain a path to real
    generation. Parses the module's own AST and inspects only its
    actual import statements (never prose/docstrings/comments, which
    legitimately discuss these names when explaining the boundary)."""
    import ast

    import app.core.services.episode_audio_assembly_service as module

    tree = ast.parse(inspect.getsource(module))
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")
            imported_names.extend(alias.name for alias in node.names)

    forbidden = [
        "AIProvider",
        "AIOrchestrator",
        "elevenlabs",
        "ElevenLabs",
        "run_voice_line_batch",
        "VoiceLineWorkflow",
        "generation_runner",
        "app.core.ai",
    ]
    for imported in imported_names:
        for term in forbidden:
            assert term not in imported, (
                f"forbidden generation-capable import {imported!r} (matches {term!r}) "
                "found in module's actual import statements"
            )
