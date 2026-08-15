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
from app.core.db.enums import ApprovalStatus, AssetType, GenerationJobStatus
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


def test_run_batch_snapshots_output_format_from_provider_default(
    session: Session, app_config: AppConfig
) -> None:
    """Milestone 9 compatibility fix: the provider's own effective
    output_format (whatever ELEVENLABS_OUTPUT_FORMAT/constructor/default
    resolved to) is snapshotted onto every GenerationJob, generically --
    run_voice_line_batch never hardcodes a format string itself."""

    class _FakeVoiceProvider(MockProvider):
        name = "fake_voice_mp3"

        @property
        def output_format(self) -> str:
            return "mp3_44100_128"

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
        provider_name="fake_voice_mp3", provider_voice_id="voice-melissa",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    orchestrator = _orchestrator(app_config, provider_registry={"fake_voice_mp3": _FakeVoiceProvider})

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="fake_voice_mp3", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=orchestrator,
        generation_jobs=GenerationJobService(),
    )

    assert result[0].parameters["output_format"] == "mp3_44100_128"


def test_run_batch_voice_profile_output_format_override_wins_over_provider_default(
    session: Session, app_config: AppConfig
) -> None:
    class _FakeVoiceProvider(MockProvider):
        name = "fake_voice_mp3_override"

        @property
        def output_format(self) -> str:
            return "mp3_44100_128"

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
        provider_name="fake_voice_mp3_override", provider_voice_id="voice-melissa",
        default_parameters={"output_format": "wav_44100"},
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    orchestrator = _orchestrator(
        app_config, provider_registry={"fake_voice_mp3_override": _FakeVoiceProvider}
    )

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(
            provider_name="fake_voice_mp3_override", dialogue_line_id=line.id, episode_id=episode.id
        ),
        orchestrator=orchestrator,
        generation_jobs=GenerationJobService(),
    )

    assert result[0].parameters["output_format"] == "wav_44100"


def test_run_batch_produces_valid_draft_mp3_asset_with_measured_duration(
    session: Session, app_config: AppConfig
) -> None:
    """Full pipeline, real ElevenLabsProvider class (fake HTTP client,
    real MPEG frame bytes) through run_voice_line_batch ->
    VoiceLineWorkflow -> AssetImportService: proves output_format
    provenance, the truthful .mp3 extension, and tinytag-measured
    duration all agree, and the resulting Asset stays DRAFT."""
    from app.core.ai.providers.elevenlabs_provider import ElevenLabsProvider

    mp3_header = bytes([0xFF, 0xFB, 0x90, 0xC0])
    frame_size = 417  # floor(144 * 128000 / 44100)
    mp3_frame = mp3_header + bytes(frame_size - len(mp3_header))
    mp3_bytes = mp3_frame * 10

    class _FakeTextToSpeech:
        def convert(self, voice_id, *, text, model_id, output_format, voice_settings):
            return iter([mp3_bytes])

    class _FakeClient:
        def __init__(self) -> None:
            self.text_to_speech = _FakeTextToSpeech()

    class _FakeElevenLabsProvider(ElevenLabsProvider):
        name = "elevenlabs"

        def __init__(self) -> None:
            super().__init__(api_key="fake-key", client_factory=lambda api_key: _FakeClient())

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
        provider_name="elevenlabs", provider_voice_id="voice-melissa",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")
    orchestrator = _orchestrator(app_config, provider_registry={"elevenlabs": _FakeElevenLabsProvider})

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="elevenlabs", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=orchestrator,
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    assert job.status == GenerationJobStatus.SUCCEEDED
    assert job.parameters["output_format"] == "mp3_44100_128"
    asset = session.get(Asset, job.result_asset_id)
    assert asset.relative_path.endswith(".mp3")
    assert asset.approval_status == ApprovalStatus.DRAFT
    assert asset.duration_seconds == pytest.approx(10 * (1152 / 44100))


# --- line performance overrides (Milestone 9 production-safety checkpoint) --


def test_run_batch_applies_a_registered_line_performance_override(
    session: Session, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generic exercise of the override mechanism itself (not the
    real Tortor line) -- proves run_voice_line_batch consults the
    registry, substitutes both the provider-bound text and the
    effective model_id, leaves authored_text/normalize_arabic_line's
    own output alone, and snapshots the true effective model onto the
    dedicated GenerationJob.provider_model column (not just
    parameters["model_id"])."""
    from app.core.ai import line_performance_overrides as overrides_module

    episode, line = _ready_line(session, dialogue_ar="ميليسا: نص عادي")
    override = overrides_module.LinePerformanceOverride(
        model_id="eleven_v3",
        provider_bound_text="[laughs] نص مختلف تماماً",
        reason="test override",
    )
    monkeypatch.setitem(overrides_module.LINE_PERFORMANCE_OVERRIDES, line.id, override)

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    assert job.parameters["authored_text"] == "نص عادي"  # authored_text never touched
    assert job.parameters["normalized_text_sent"] == "[laughs] نص مختلف تماماً"
    assert job.prompt_text == "[laughs] نص مختلف تماماً"
    assert job.parameters["model_id"] == "eleven_v3"
    assert job.provider_model == "eleven_v3"  # dedicated column, not just parameters
    assert job.parameters["voice_id"] == "voice-melissa"  # voice identity unaffected


def test_run_batch_ordinary_line_has_no_performance_override_applied(
    session: Session, app_config: AppConfig
) -> None:
    """A line with no registry entry -- including one that happens to
    contain هاها-like text -- must generate completely normally: no
    model_id override, no text substitution."""
    episode, line = _ready_line(session, dialogue_ar="ميليسا: هاها! يا لها من مزحة")

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(provider_name="mock_provider", dialogue_line_id=line.id, episode_id=episode.id),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    assert job.parameters["normalized_text_sent"] == "هاها! يا لها من مزحة"
    assert "model_id" not in job.parameters
    assert job.provider_model is None  # mock_provider has no .model attribute


def test_run_batch_real_tortor_scene7_line_id_resolves_to_v3_laugh_cue(
    session: Session, app_config: AppConfig
) -> None:
    """End-to-end proof using the REAL production line id (not a
    synthetic one): if a DialogueLine ever exists with this exact id,
    run_voice_line_batch automatically sends eleven_v3 + [laughs] --
    no manual script, no founder/Claude needing to remember anything."""
    from app.core.ai.line_performance_overrides import TORTOR_SCENE7_LAUGH_LINE_ID
    from app.core.models import Character, DialogueLine

    ss = SceneService()
    vps = VoiceProfileService()
    approvals = ApprovalService()
    character = Character(slug="tortor", name_ar="طُرطُر", name_en="Tortor")
    session.add(character)
    session.flush()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="طُرطُر: هاها! دبدوبك يحب اللعب في العشب!")
    character_id, speaker_key = ss.resolve_speaker(session, "طُرطُر")
    # The id column has a Python-side uuid4 default, freely overridable
    # -- constructed directly (rather than via sync_dialogue_lines) so
    # this test can exercise the exact real production line id.
    line = DialogueLine(
        id=TORTOR_SCENE7_LAUGH_LINE_ID,
        scene_id=scene.id,
        order_index=0,
        speaker_raw="طُرطُر",
        character_id=character_id,
        speaker_key=speaker_key,
        authored_text="هاها! دبدوبك يحب اللعب في العشب!",
        is_current=True,
    )
    session.add(line)
    session.flush()
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Tortor",
        provider_name="mock_provider", provider_voice_id="rFDdsCQRZCUL8cPOWtnP",
    )
    vps.set_active_voice_profile(session, profile.id)
    approvals.approve_entity(session, "voice_profile", profile.id, decided_by="founder")

    result = run_voice_line_batch(
        session,
        VoiceLineBatchRequest(
            provider_name="mock_provider", dialogue_line_id=TORTOR_SCENE7_LAUGH_LINE_ID, episode_id=episode.id
        ),
        orchestrator=_orchestrator(app_config),
        generation_jobs=GenerationJobService(),
    )

    job = result[0]
    assert job.parameters["authored_text"] == "هاها! دبدوبك يحب اللعب في العشب!"
    assert job.parameters["normalized_text_sent"] == "[laughs] دبدوبك يحب اللعب في العشب!"
    assert job.parameters["model_id"] == "eleven_v3"
    assert job.parameters["voice_id"] == "rFDdsCQRZCUL8cPOWtnP"


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
