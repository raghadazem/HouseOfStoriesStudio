"""Tests for VoiceProductionCandidateService: "does this line already
have a valid, CURRENT, reusable candidate?" (Milestone 9 production-
safety checkpoint, 2026-08-15).

Every candidate is constructed directly (GenerationJobService +
AssetImportService), not via a real provider call, so every matching
dimension (voice_id/model_id/output_format/normalized_text_sent/file
existence/job status) can be independently controlled and independently
proven to gate reuse. No real ElevenLabs call anywhere in this file.
"""

from __future__ import annotations

import uuid
import wave

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.providers.mock_provider import MockProvider
from app.core.db.enums import ApprovalDecision, AssetType, GenerationJobStatus
from app.core.models import Character, DialogueLine, Episode
from app.core.models.asset import ROLE_FINAL_LINE_VOICE
from app.core.services.approval_service import ApprovalService
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import NotFoundError
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService
from app.core.services.voice_production_candidate_service import VoiceProductionCandidateService
from app.core.services.voice_profile_service import VoiceProfileService


class _FakeVoiceProvider(MockProvider):
    """A real .model/.output_format, unlike MockProvider, so every
    matching dimension is independently testable."""

    name = "fake_candidate_provider"

    @property
    def model(self) -> str:
        return "fake-model-v1"

    @property
    def output_format(self) -> str:
        return "fake_format"


def _orchestrator() -> AIOrchestrator:
    return AIOrchestrator(provider_registry={"fake_candidate_provider": _FakeVoiceProvider})


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    return episode


def _ready_line(session: Session, dialogue_ar: str = "ميليسا: مرحباً"):
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug=f"melissa-{uuid.uuid4().hex[:8]}", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar)
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="fake_candidate_provider", provider_voice_id="voice-current",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    return episode, line


def _write_wav(path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(uuid.uuid4().bytes * 50)  # unique bytes -> unique checksum


def _job_with_asset(
    session: Session,
    app_config: AppConfig,
    tmp_path,
    line: DialogueLine,
    *,
    voice_id: str | None,
    normalized_text_sent: str | None,
    output_format: object = "fake_format",
    model_id: str | None = None,
    # Mirrors what run_voice_line_batch actually snapshots for an
    # ordinary (non-overridden) line: GenerationJob.provider_model is
    # always the provider's own configured default -- only a line
    # performance override ever puts an explicit "model_id" key into
    # parameters. Tests that want a mismatched model pass model_id=
    # explicitly (a real params key always wins over this fallback).
    provider_model: str | None = "fake-model-v1",
    status: GenerationJobStatus = GenerationJobStatus.SUCCEEDED,
    delete_file: bool = False,
    with_asset: bool = True,
):
    jobs = GenerationJobService()
    parameters: dict[str, object] = {}
    if voice_id is not None:
        parameters["voice_id"] = voice_id
    if output_format is not None:
        parameters["output_format"] = output_format
    if normalized_text_sent is not None:
        parameters["normalized_text_sent"] = normalized_text_sent
    if model_id is not None:
        parameters["model_id"] = model_id

    asset = None
    result_asset_id = None
    if with_asset:
        asset_import = AssetImportService(app_config, StorageService(app_config))
        wav_path = tmp_path / f"voice_{uuid.uuid4().hex}.wav"
        _write_wav(wav_path)
        asset = asset_import.import_asset(
            session,
            ImportRequest(
                source_path=wav_path, asset_type=AssetType.VOICE,
                episode_id=line.scene.episode_id, dialogue_line_id=line.id, source_tool="test",
            ),
        )
        if delete_file:
            (app_config.production_dir / asset.relative_path).unlink()
        result_asset_id = asset.id

    job = jobs.create_job(
        session, workflow_name="voice_line", provider_name="fake_candidate_provider",
        provider_model=provider_model, batch_id=uuid.uuid4(),
        prompt_text=normalized_text_sent or "x", parameters=parameters,
        dialogue_line_id=line.id, episode_id=line.scene.episode_id,
    )
    job = jobs.mark_running(session, job.id)
    if status == GenerationJobStatus.SUCCEEDED:
        job = jobs.mark_succeeded(session, job.id, result_asset_id=result_asset_id)
    elif status == GenerationJobStatus.FAILED:
        job = jobs.mark_failed(session, job.id, error_category="Test", error_message="simulated failure")
    return job, asset


# --- basic lookups -----------------------------------------------------------


def test_evaluate_line_raises_not_found_for_unknown_line(session: Session, app_config: AppConfig) -> None:
    service = VoiceProductionCandidateService(config=app_config)
    with pytest.raises(NotFoundError):
        service.evaluate_line(
            session, uuid.uuid4(), provider_name="fake_candidate_provider", orchestrator=_orchestrator()
        )


def test_evaluate_line_no_candidate_at_all(session: Session, app_config: AppConfig) -> None:
    _episode, line = _ready_line(session)
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False
    assert report.current_candidate_asset_id is None
    assert report.expected_voice_id == "voice-current"
    assert report.expected_model_id == "fake-model-v1"
    assert report.expected_output_format == "fake_format"
    assert report.expected_normalized_text_sent == "مرحباً"


# --- the 11+ required matching-rule cases -------------------------------------


def test_1_current_candidate_causes_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is True
    assert report.current_candidate_asset_id is not None


def test_2_superseded_voice_profile_candidate_does_not_cause_skip(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """A job generated under an old, no-longer-active VoiceProfile
    (e.g. before the Melissa/Bilsan casting swap) must not be mistaken
    for current, even though it once succeeded."""
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-OLD-superseded", normalized_text_sent="مرحباً",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_3_wrong_voice_id_does_not_cause_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="totally-different-voice", normalized_text_sent="مرحباً",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_4_wrong_model_id_does_not_cause_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً", model_id="wrong-model",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_5_wrong_output_format_does_not_cause_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً", output_format="wrong_format",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_6_different_normalized_text_sent_does_not_cause_skip(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """E.g. before a pronunciation override existed, or before the
    Tortor Scene 7 laugh-cue substitution."""
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="نص مختلف تماماً",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_7_missing_asset_file_does_not_cause_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    """A SUCCEEDED job whose Asset row exists but whose file has been
    removed from disk must never be treated as reusable."""
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً", delete_file=True,
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_8_failed_job_does_not_cause_skip(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
        status=GenerationJobStatus.FAILED, with_asset=False,
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is False


def test_9_draft_current_candidate_is_reusable(session: Session, app_config: AppConfig, tmp_path) -> None:
    """DRAFT is the default/normal state -- must count as reusable for
    the purpose of avoiding a duplicate paid call; final-take promotion
    is a completely separate, later human decision."""
    from app.core.db.enums import ApprovalStatus

    _episode, line = _ready_line(session)
    _job, asset = _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
    )
    assert asset.approval_status == ApprovalStatus.DRAFT
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is True


def test_10_approved_candidate_is_reusable(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job, asset = _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
    )
    ApprovalService().decide_asset_review(
        session, asset.id, ApprovalDecision.APPROVED, decided_by="founder"
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is True


def test_11_final_line_voice_candidate_is_reusable(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job, asset = _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
    )
    ApprovalService().decide_asset_review(
        session, asset.id, ApprovalDecision.APPROVED, decided_by="founder"
    )
    SceneService().set_line_final_take(session, line.id, asset.id)
    assert asset.role == ROLE_FINAL_LINE_VOICE
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is True


# --- idempotent-resume semantics ----------------------------------------------


def test_16_partial_batch_success_second_pass_only_selects_missing(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """Simulates: a batch of 2 lines, one succeeds (current candidate),
    one fails (no candidate) -- re-running selection must only flag the
    failed/missing one."""
    episode = _episode(session)
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug=f"melissa-{uuid.uuid4().hex[:8]}", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: نجح\nميليسا: فشل")
    lines = ss.sync_dialogue_lines(session, scene.id)
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="fake_candidate_provider", provider_voice_id="voice-current",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")

    succeeded_line, failed_line = lines[0], lines[1]
    _job_with_asset(
        session, app_config, tmp_path, succeeded_line,
        voice_id="voice-current", normalized_text_sent="نجح",
    )
    _job_with_asset(
        session, app_config, tmp_path, failed_line,
        voice_id="voice-current", normalized_text_sent="فشل",
        status=GenerationJobStatus.FAILED, with_asset=False,
    )
    service = VoiceProductionCandidateService(config=app_config)

    succeeded_report = service.evaluate_line(
        session, succeeded_line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )
    failed_report = service.evaluate_line(
        session, failed_line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert succeeded_report.has_current_candidate is True  # would be skipped
    assert failed_report.has_current_candidate is False  # would be regenerated


def test_17_all_lines_current_zero_missing(session: Session, app_config: AppConfig, tmp_path) -> None:
    _episode, line = _ready_line(session)
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="مرحباً",
    )
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.has_current_candidate is True


# --- performance override participates in matching ----------------------------


def test_line_performance_override_line_only_matches_the_override_shape(
    session: Session, app_config: AppConfig, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line with a registered performance override (like Tortor's
    Scene 7 laugh cue) must expect the override's model_id/text, not
    the ordinary provider default/normalize_arabic_line output -- a
    plain-multilingual-v2 candidate for that line must NOT count as
    current, and a candidate that matches the override shape must."""
    from app.core.ai import line_performance_overrides as overrides_module

    # _ready_line always seats a "Melissa" character (name_ar=ميليسا) --
    # the speaker's real identity is irrelevant to this test, which
    # only exercises the override registry's effect on matching.
    _episode, line = _ready_line(session, dialogue_ar="ميليسا: هاها! نص")
    override = overrides_module.LinePerformanceOverride(
        model_id="eleven_v3", provider_bound_text="[laughs] نص", reason="test",
    )
    monkeypatch.setitem(overrides_module.LINE_PERFORMANCE_OVERRIDES, line.id, override)
    service = VoiceProductionCandidateService(config=app_config)

    # An old candidate generated before the override existed (plain text, no model_id).
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="هاها! نص",
    )
    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )
    assert report.has_current_candidate is False
    assert report.expected_model_id == "eleven_v3"
    assert report.expected_normalized_text_sent == "[laughs] نص"

    # A candidate matching the override shape.
    _job_with_asset(
        session, app_config, tmp_path, line,
        voice_id="voice-current", normalized_text_sent="[laughs] نص", model_id="eleven_v3",
    )
    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )
    assert report.has_current_candidate is True


def test_pronunciation_override_participates_in_expected_text(
    session: Session, app_config: AppConfig
) -> None:
    """بيلسان still works normally: a line's expected text picks up the
    live PronunciationOverride table, same as production generation."""
    from app.core.services.pronunciation_override_service import PronunciationOverrideService

    _episode, line = _ready_line(session, dialogue_ar="ميليسا: يا بيلسان")
    PronunciationOverrideService().create_override(session, term="بيلسان", replacement="بَيْلَسان")
    service = VoiceProductionCandidateService(config=app_config)

    report = service.evaluate_line(
        session, line.id, provider_name="fake_candidate_provider", orchestrator=_orchestrator()
    )

    assert report.expected_normalized_text_sent == "يا بَيْلَسان"
