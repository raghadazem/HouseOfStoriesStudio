"""Tests for run_voice_line_batch: mirrors run_scene_image_batch's test shape.

Exercises the real VoiceLineWorkflow + MockProvider + real
AssetImportService/GenerationJobService together, per this module's own
established pattern (see test_generation_runner.py's module docstring).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.exceptions import ProviderNotConfiguredError, ProviderRequestError
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.generation_runner import VoiceLineBatchRequest, run_voice_line_batch
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult
from app.core.ai.providers.mock_provider import MockProvider
from app.core.ai.workflows.base import Workflow
from app.core.ai.workflows.voice_line_workflow import VoiceLineWorkflow
from app.core.db.enums import AssetType, GenerationJobStatus
from app.core.models import Asset, Character, Episode
from app.core.services.approval_service import ApprovalService
from app.core.services.asset_import_service import AssetImportService
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService
from app.core.services.voice_profile_service import VoiceProfileService


def _workflow_registry_for(app_config: AppConfig) -> dict[str, type[Workflow]]:
    asset_import = AssetImportService(app_config, StorageService(app_config))

    class _BoundVoiceLineWorkflow(VoiceLineWorkflow):
        def __init__(self) -> None:
            super().__init__(asset_import=asset_import)

    return {VoiceLineWorkflow.name: _BoundVoiceLineWorkflow}


def _orchestrator(app_config: AppConfig, provider_registry=None) -> AIOrchestrator:
    return AIOrchestrator(
        provider_registry=provider_registry, workflow_registry=_workflow_registry_for(app_config)
    )


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    return episode


def _ready_line(session: Session, dialogue_ar: str = "ميليسا: مرحباً يا أصدقاء"):
    """A DialogueLine whose speaker resolves to an approved, active VoiceProfile."""
    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar=dialogue_ar)
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="mock_provider", provider_voice_id="voice-melissa",
        default_parameters={"stability": 0.5},
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    return episode, line


# --- fail-fast pre-checks ---------------------------------------------------


def test_run_batch_rejects_out_of_range_candidate_count(session: Session, app_config: AppConfig) -> None:
    episode, line = _ready_line(session)
    request = VoiceLineBatchRequest(
        provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id, candidate_count=5
    )
    with pytest.raises(ValidationError):
        run_voice_line_batch(
            session, request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
        )


def test_run_batch_rejects_unknown_line(session: Session, app_config: AppConfig) -> None:
    request = VoiceLineBatchRequest(
        provider_name="mock_provider", dialogue_line_id=uuid.uuid4(), episode_id=uuid.uuid4()
    )
    with pytest.raises(NotFoundError):
        run_voice_line_batch(
            session, request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
        )


def test_run_batch_rejects_line_not_ready_before_creating_any_job(
    session: Session, app_config: AppConfig
) -> None:
    """No VoiceProfile at all -- must block, naming the character, zero job rows."""
    ss = SceneService()
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    jobs = GenerationJobService()

    with pytest.raises(ValidationError, match="ميليسا"):
        run_voice_line_batch(
            session,
            VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
            orchestrator=_orchestrator(app_config),
            generation_jobs=jobs,
        )

    assert jobs.list_jobs(session, dialogue_line_id=line.id) == []


def test_run_batch_rejects_unconfigured_provider_before_creating_any_job(
    session: Session, app_config: AppConfig
) -> None:
    class _UnconfiguredProvider(AIProvider):
        name = "unconfigured"
        supported_modalities = frozenset({"voice"})

        def is_configured(self) -> bool:
            return False

        def generate(self, request: GenerationRequest) -> GenerationResult:
            raise AssertionError("must never be called")

    episode, line = _ready_line(session)
    jobs = GenerationJobService()
    orchestrator = _orchestrator(app_config, provider_registry={"unconfigured": _UnconfiguredProvider})

    with pytest.raises((ProviderNotConfiguredError, ValidationError)):
        run_voice_line_batch(
            session,
            VoiceLineBatchRequest(provider_name="unconfigured", dialogue_line_id=line.id, episode_id=episode.id),
            orchestrator=orchestrator,
            generation_jobs=jobs,
        )

    assert jobs.list_jobs(session, dialogue_line_id=line.id) == []


def test_run_batch_rejects_song_scene_line_before_creating_any_job(
    session: Session, app_config: AppConfig
) -> None:
    """Core must refuse a song-scene line even if called directly --
    never relies solely on the GUI hiding/disabling Generate."""
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="الجميع: معاً نستطيع")
    ss.update_scene(session, scene.id, is_song_scene=True)
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    jobs = GenerationJobService()

    with pytest.raises(ValidationError, match="song scene"):
        run_voice_line_batch(
            session,
            VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
            orchestrator=_orchestrator(app_config),
            generation_jobs=jobs,
        )

    assert jobs.list_jobs(session, dialogue_line_id=line.id) == []


# --- success + provenance ---------------------------------------------------


def test_run_batch_creates_one_job_per_candidate_sharing_a_batch_id(
    session: Session, app_config: AppConfig
) -> None:
    episode, line = _ready_line(session)
    jobs = GenerationJobService()

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(
            provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id, candidate_count=2
        ),
        orchestrator=_orchestrator(app_config),
        generation_jobs=jobs,
    )

    assert len(result) == 2
    assert len({job.batch_id for job in result}) == 1
    assert all(job.status == GenerationJobStatus.SUCCEEDED for job in result)
    assert all(job.dialogue_line_id == line.id for job in result)
    assert len({job.result_asset_id for job in result}) == 2


def test_run_batch_snapshots_authored_and_normalized_text(
    session: Session, app_config: AppConfig
) -> None:
    episode, line = _ready_line(session, dialogue_ar="ميليسا: تورتور صديقي")
    from app.core.services.pronunciation_override_service import PronunciationOverrideService

    PronunciationOverrideService().create_override(session, term="تورتور", replacement="طُرطُر")

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    assert job.parameters["authored_text"] == "تورتور صديقي"
    assert job.parameters["normalized_text_sent"] == "طُرطُر صديقي"
    assert job.parameters["pronunciation_overrides_applied"] == ["تورتور"]
    assert job.prompt_text == "طُرطُر صديقي"  # exact text sent, snapshotted verbatim
    assert job.parameters["voice_id"] == "voice-melissa"
    assert job.parameters["stability"] == 0.5


def test_run_batch_sets_asset_dialogue_line_id_and_duration(
    session: Session, app_config: AppConfig
) -> None:
    episode, line = _ready_line(session)

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    asset = session.get(Asset, job.result_asset_id)
    assert asset.dialogue_line_id == line.id
    assert asset.asset_type == AssetType.VOICE
    assert asset.duration_seconds == 1.0
    assert asset.generation_job_id == job.id


def test_run_batch_threads_retry_of_job_id_onto_the_new_job(
    session: Session, app_config: AppConfig
) -> None:
    episode, line = _ready_line(session)
    original = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )[0]

    retried = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(
            provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id,
            retry_of_job_id=original.id,
        ),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )[0]

    assert retried.retry_of_job_id == original.id
    assert retried.batch_id == original.batch_id


# --- provider failure / cancellation -----------------------------------------


def test_run_batch_marks_job_failed_when_provider_raises(session: Session, app_config: AppConfig) -> None:
    class _FailingProvider(AIProvider):
        name = "failing"
        supported_modalities = frozenset({"voice"})

        def is_configured(self) -> bool:
            return True

        def generate(self, request: GenerationRequest) -> GenerationResult:
            raise ProviderRequestError("simulated provider failure")

    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="failing", provider_voice_id="voice-melissa",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    jobs = GenerationJobService()
    orchestrator = _orchestrator(app_config, provider_registry={"failing": _FailingProvider})

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(
            provider_name="failing", dialogue_line_id=line.id, episode_id=episode.id, candidate_count=2
        ),
        orchestrator=orchestrator,
        generation_jobs=jobs,
    )

    assert len(result) == 2
    assert all(job.status == GenerationJobStatus.FAILED for job in result)
    assert all(job.error_category == "ProviderRequestError" for job in result)


def test_run_batch_discards_result_when_cancelled_while_generating(
    session: Session, app_config: AppConfig
) -> None:
    jobs = GenerationJobService()
    running_job_ids: list[uuid.UUID] = []

    def _on_update(job):
        if job.status == GenerationJobStatus.RUNNING:
            running_job_ids.append(job.id)

    class _CancelMidFlightProvider(MockProvider):
        name = "cancel_mid_flight"

        def generate(self, request: GenerationRequest) -> GenerationResult:
            jobs.request_cancel(session, running_job_ids[-1])
            return super().generate(request)

    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    line = ss.sync_dialogue_lines(session, scene.id)[0]
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="cancel_mid_flight", provider_voice_id="voice-melissa",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    orchestrator = _orchestrator(
        app_config, provider_registry={"cancel_mid_flight": _CancelMidFlightProvider}
    )

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="cancel_mid_flight", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=orchestrator,
        generation_jobs=jobs,
        on_job_update=_on_update,
    )

    job = result[0]
    assert job.status == GenerationJobStatus.CANCELLED
    assert job.result_asset_id is not None
    assert jobs.list_jobs(session, status=GenerationJobStatus.SUCCEEDED) == []
