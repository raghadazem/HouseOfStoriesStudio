"""Tests for VoiceGenerationReadinessService: actionable, per-line generation blockers."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.models import Character, Episode
from app.core.models.voice_profile import SPEAKER_KEY_NARRATOR
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import NotFoundError
from app.core.services.scene_service import SceneService
from app.core.services.voice_generation_readiness_service import VoiceGenerationReadinessService
from app.core.services.voice_profile_service import VoiceProfileService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    return episode


def _melissa(session: Session) -> Character:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    return character


def _line_for(session: Session, ss: SceneService, dialogue_ar: str):
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar)
    return ss.sync_dialogue_lines(session, scene.id)[0]


def _ready_profile(session: Session, vps: VoiceProfileService, approvals: ApprovalService, **kwargs):
    profile = vps.create_voice_profile(
        session, display_name="V", provider_name="mock_provider", provider_voice_id="v1", **kwargs
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    return profile


def _orchestrator() -> AIOrchestrator:
    return AIOrchestrator()


def test_evaluate_raises_not_found_for_unknown_line(session: Session) -> None:
    service = VoiceGenerationReadinessService()
    with pytest.raises(NotFoundError):
        service.evaluate(
            session, uuid.uuid4(), provider_name="mock_provider", orchestrator=_orchestrator()
        )


def test_evaluate_is_ready_for_fully_prepared_line(session: Session) -> None:
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    melissa = _melissa(session)
    line = _line_for(session, ss, "ميليسا: مرحباً")
    _ready_profile(session, vps, approvals, character_id=melissa.id)
    service = VoiceGenerationReadinessService(voice_profiles=vps, approvals=approvals, scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert report.is_ready, report.blocking_messages


def test_evaluate_blocks_unresolved_speaker_naming_it(session: Session) -> None:
    ss = SceneService()
    line = _line_for(session, ss, "شخصية مجهولة: مرحباً")
    service = VoiceGenerationReadinessService(scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("شخصية مجهولة" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_missing_active_voice_profile(session: Session) -> None:
    ss = SceneService()
    _melissa(session)  # Character exists, but has no VoiceProfile at all
    line = _line_for(session, ss, "ميليسا: مرحباً")
    service = VoiceGenerationReadinessService(scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("No active voice profile" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_unapproved_active_voice_profile(session: Session) -> None:
    ss = SceneService()
    vps = VoiceProfileService()
    melissa = _melissa(session)
    line = _line_for(session, ss, "ميليسا: مرحباً")
    profile = vps.create_voice_profile(
        session, character_id=melissa.id, display_name="V",
        provider_name="mock_provider", provider_voice_id="v1",
    )
    vps.set_active_voice_profile(session, profile.id)  # never approved
    service = VoiceGenerationReadinessService(voice_profiles=vps, scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("not yet approved" in msg for msg in report.blocking_messages)


def test_evaluate_narrator_line_resolves_via_speaker_key(session: Session) -> None:
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    line = _line_for(session, ss, "Narrator: كان يا ما كان")
    _ready_profile(session, vps, approvals, speaker_key=SPEAKER_KEY_NARRATOR)
    service = VoiceGenerationReadinessService(voice_profiles=vps, approvals=approvals, scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert report.is_ready, report.blocking_messages


def test_evaluate_blocks_when_provider_not_configured(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    melissa = _melissa(session)
    line = _line_for(session, ss, "ميليسا: مرحباً")
    _ready_profile(session, vps, approvals, character_id=melissa.id)
    service = VoiceGenerationReadinessService(voice_profiles=vps, approvals=approvals, scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="elevenlabs", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("not configured" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_when_a_job_is_already_in_flight(session: Session) -> None:
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    melissa = _melissa(session)
    line = _line_for(session, ss, "ميليسا: مرحباً")
    _ready_profile(session, vps, approvals, character_id=melissa.id)
    jobs = GenerationJobService()
    jobs.create_job(
        session, workflow_name="voice_line", provider_name="mock_provider", provider_model=None,
        batch_id=uuid.uuid4(), prompt_text="x", dialogue_line_id=line.id,
    )
    service = VoiceGenerationReadinessService(
        generation_jobs=jobs, voice_profiles=vps, approvals=approvals, scenes=ss
    )

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("already pending/running" in msg for msg in report.blocking_messages)


def test_evaluate_song_scene_line_is_not_applicable(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا وبيلسان: معاً معاً")
    ss.update_scene(session, scene.id, is_song_scene=True)
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    service = VoiceGenerationReadinessService(scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert report.is_song_scene
    assert not report.is_ready
    assert report.blocking_messages == []
    assert report.not_applicable_reason is not None


def test_evaluate_song_scene_unresolved_speaker_is_not_a_voice_blocker(session: Session) -> None:
    """A song scene's lines skip the ordinary speaker/profile checks
    entirely -- an unresolved speaker like 'الجميع' must never surface
    as a Voice readiness failure."""
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="الجميع: معاً نستطيع")
    ss.update_scene(session, scene.id, is_song_scene=True)
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    service = VoiceGenerationReadinessService(scenes=ss)

    report = service.evaluate(
        session, line.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert report.is_song_scene
    assert not any("does not match any known character" in msg for msg in report.blocking_messages)
    assert report.blocking_messages == []


def test_evaluate_scene_returns_one_report_per_current_line(session: Session) -> None:
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    melissa = _melissa(session)
    _ready_profile(session, vps, approvals, character_id=melissa.id)
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B")
    service = VoiceGenerationReadinessService(voice_profiles=vps, approvals=approvals, scenes=ss)

    reports = service.evaluate_scene(
        session, scene.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert len(reports) == 2
    assert reports[0].is_ready  # Melissa resolved + ready
    assert not reports[1].is_ready  # Bilsan unresolved (no Character row created)
