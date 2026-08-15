"""Workflow-level tests: prompt -> MockProvider -> real Asset via AssetImportService.

Each workflow is instantiated directly (not through ``AIOrchestrator``)
with an ``app_config``-bound ``AssetImportService`` — exactly like
``tests/unit/test_asset_import_service.py`` — because
``AssetImportService()``'s no-arg default reads the process-wide
cached ``AppConfig``, which would otherwise point at the real
project's ``production/``/``data/`` directories instead of this test's
isolated ``tmp_path``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.prompt_engine import PromptEngine
from app.core.ai.providers.mock_provider import MockProvider
from app.core.ai.workflows.base import WorkflowContext
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.ai.workflows.scene_image_workflow import SceneImageWorkflow
from app.core.ai.workflows.thumbnail_workflow import ThumbnailWorkflow
from app.core.ai.workflows.voice_line_workflow import VoiceLineWorkflow
from app.core.db.enums import ApprovalStatus, AssetType, PromptCategory, PromptType
from app.core.models import Character, CharacterVersion, Episode, PromptTemplate, Scene
from app.core.services.asset_import_service import AssetImportService
from app.core.services.exceptions import CharacterLockIncompleteError, ValidationError
from app.core.services.prompt_template_service import PromptTemplateService
from app.core.services.storage_service import StorageService


def _asset_import(app_config: AppConfig) -> AssetImportService:
    return AssetImportService(app_config, StorageService(app_config))


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
    )
    session.add(episode)
    session.flush()
    return episode


def _scene(session: Session, episode: Episode) -> Scene:
    scene = Scene(episode_id=episode.id, order_index=1, location="forest")
    session.add(scene)
    session.flush()
    return scene


def _character_version(session: Session, **overrides: object) -> CharacterVersion:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    defaults: dict[str, object] = {
        "character_id": character.id,
        "version_number": "v01",
        "master_prompt": "a young girl",
        "visual_summary": "Two ponytails, denim dress.",
        "negative_prompt": "no extra characters",
        "color_palette": ["#ffcc00"],
        "relative_height": "taller than Bilsan",
    }
    defaults.update(overrides)
    version = CharacterVersion(**defaults)
    session.add(version)
    session.flush()
    return version


def _template(
    session: Session, *, name: str, category: PromptCategory, prompt_type: PromptType, text_en: str
) -> PromptTemplate:
    return PromptTemplateService().create_prompt_template(
        session, name=name, category=category, prompt_type=prompt_type, text_en=text_en
    )


# --- CharacterReferenceWorkflow ---------------------------------------


def test_character_reference_workflow_creates_draft_asset(
    session: Session, app_config: AppConfig
) -> None:
    version = _character_version(session)
    template = _template(
        session,
        name="char_ref",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="A picture of {{ character_master_prompt }}.",
    )
    workflow = CharacterReferenceWorkflow(
        prompt_engine=PromptEngine(), asset_import=_asset_import(app_config)
    )
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        character_version_id=version.id,
    )

    result = workflow.run(ctx)

    assert result.asset.approval_status == ApprovalStatus.DRAFT
    assert result.asset.character_version_id == version.id
    assert result.asset.source_tool == "mock_provider"
    assert result.asset.prompt_used_id == template.id
    assert result.asset.asset_type == AssetType.IMAGE


def test_character_reference_workflow_requires_character_version(
    session: Session, app_config: AppConfig
) -> None:
    template = _template(
        session,
        name="char_ref_missing",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="A character portrait.",
    )
    workflow = CharacterReferenceWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(session=session, provider=MockProvider(), prompt_template_id=template.id)

    with pytest.raises(ValidationError, match="character_version_id"):
        workflow.run(ctx)


def test_character_reference_workflow_rejects_incomplete_character_lock(
    session: Session, app_config: AppConfig
) -> None:
    """Production-generation policy (Milestone 7): a CharacterVersion
    missing required prompt fields must never be used for generation —
    enforced identically for MockProvider as for any real provider, per
    the founder's "production rules belong to the workflow/domain, not
    the provider" requirement."""
    version = _character_version(session, visual_summary=None, negative_prompt=None)
    template = _template(
        session,
        name="char_ref_incomplete",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="A picture of {{ character_master_prompt }}.",
    )
    workflow = CharacterReferenceWorkflow(
        prompt_engine=PromptEngine(), asset_import=_asset_import(app_config)
    )
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        character_version_id=version.id,
    )

    with pytest.raises(CharacterLockIncompleteError) as exc_info:
        workflow.run(ctx)

    assert set(exc_info.value.missing_fields) == {"visual_summary", "negative_prompt"}


# --- SceneImageWorkflow -------------------------------------------------


def test_scene_image_workflow_creates_draft_asset(session: Session, app_config: AppConfig) -> None:
    episode = _episode(session)
    scene = _scene(session, episode)
    template = _template(
        session,
        name="scene_only",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A quiet forest.",
    )
    workflow = SceneImageWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        episode_id=episode.id,
        scene_id=scene.id,
    )

    result = workflow.run(ctx)

    assert result.asset.episode_id == episode.id
    assert result.asset.scene_id == scene.id
    assert result.asset.role is None
    assert result.asset.asset_type == AssetType.IMAGE


def test_scene_image_workflow_requires_episode_and_scene(
    session: Session, app_config: AppConfig
) -> None:
    template = _template(
        session,
        name="scene_missing",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A forest.",
    )
    workflow = SceneImageWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(session=session, provider=MockProvider(), prompt_template_id=template.id)

    with pytest.raises(ValidationError, match="episode_id and scene_id"):
        workflow.run(ctx)


def test_scene_image_workflow_direct_text_path_bypasses_prompt_engine(
    session: Session, app_config: AppConfig
) -> None:
    """rendered_prompt_text set, no prompt_template_id at all -- proves
    the direct path never touches PromptEngine/PromptTemplate."""
    episode = _episode(session)
    scene = _scene(session, episode)
    workflow = SceneImageWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=None,
        episode_id=episode.id,
        scene_id=scene.id,
        rendered_prompt_text="A quiet forest at dawn.",
        rendered_negative_prompt_text="no text overlays",
    )

    result = workflow.run(ctx)

    assert result.generation_request.prompt_text == "A quiet forest at dawn."
    assert result.generation_request.negative_prompt_text == "no text overlays"
    assert result.asset.prompt_used_id is None  # no PromptTemplate was ever involved
    assert result.asset.scene_id == scene.id


def test_scene_image_workflow_direct_text_path_sends_multiple_reference_paths(
    session: Session, app_config: AppConfig
) -> None:
    """Proves the direct-text path is not capped at one character —
    the exact multi-character-consistency gap Milestone 8 closes."""
    episode = _episode(session)
    scene = _scene(session, episode)
    workflow = SceneImageWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        episode_id=episode.id,
        scene_id=scene.id,
        rendered_prompt_text="Melissa and Bilsan share a picnic.",
        rendered_reference_asset_paths=["characters/melissa/v01/ref.png", "characters/bilsan/v01/ref.png"],
    )

    result = workflow.run(ctx)

    assert result.generation_request.reference_asset_paths == [
        "characters/melissa/v01/ref.png",
        "characters/bilsan/v01/ref.png",
    ]


def test_scene_image_workflow_legacy_template_path_still_works(
    session: Session, app_config: AppConfig
) -> None:
    """rendered_prompt_text left unset (default None) -- the pre-Milestone-8
    template path must still work unchanged, byte for byte."""
    episode = _episode(session)
    scene = _scene(session, episode)
    template = _template(
        session,
        name="scene_legacy",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A quiet forest.",
    )
    workflow = SceneImageWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        episode_id=episode.id,
        scene_id=scene.id,
    )

    result = workflow.run(ctx)

    assert result.generation_request.prompt_text == "A quiet forest."
    assert result.asset.prompt_used_id == template.id


# --- VoiceLineWorkflow ---------------------------------------------------


def test_voice_line_workflow_creates_draft_asset(session: Session, app_config: AppConfig) -> None:
    episode = _episode(session)
    template = _template(
        session,
        name="voice_line",
        category=PromptCategory.VOICE,
        prompt_type=PromptType.VOICE,
        text_en="Say: hello there.",
    )
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        episode_id=episode.id,
    )

    result = workflow.run(ctx)

    assert result.asset.asset_type == AssetType.VOICE
    assert result.asset.episode_id == episode.id


def test_voice_line_workflow_requires_episode(session: Session, app_config: AppConfig) -> None:
    template = _template(
        session,
        name="voice_line_missing",
        category=PromptCategory.VOICE,
        prompt_type=PromptType.VOICE,
        text_en="Say hi.",
    )
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(session=session, provider=MockProvider(), prompt_template_id=template.id)

    with pytest.raises(ValidationError, match="episode_id"):
        workflow.run(ctx)


def test_voice_line_workflow_direct_text_path_bypasses_prompt_engine(
    session: Session, app_config: AppConfig
) -> None:
    """rendered_prompt_text set, no prompt_template_id -- proves the
    direct path never touches PromptEngine/PromptTemplate."""
    episode = _episode(session)
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=None,
        episode_id=episode.id,
        rendered_prompt_text="مرحباً يا أصدقاء",
    )

    result = workflow.run(ctx)

    assert result.generation_request.prompt_text == "مرحباً يا أصدقاء"
    assert result.generation_request.modality == "voice"
    assert result.asset.prompt_used_id is None  # no PromptTemplate was ever involved
    assert result.asset.asset_type == AssetType.VOICE


def test_voice_line_workflow_direct_text_path_measures_real_duration(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session)
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        episode_id=episode.id,
        rendered_prompt_text="نص قصير",
    )

    result = workflow.run(ctx)

    # MockProvider's voice output is a real, wave-openable 1.0s clip
    # (see mock_provider.py) -- proves duration is genuinely measured
    # from the file, not invented.
    assert result.asset.duration_seconds == 1.0


def _minimal_mp3_bytes(n_frames: int) -> bytes:
    """A real, structurally-valid MPEG-1 Layer III CBR 128kbps/44100Hz
    mono MP3 -- silent frame data, but genuinely tinytag-parseable
    (verified against real tinytag output), so tests never depend on an
    external encoder or a real ElevenLabs call."""
    header = bytes([0xFF, 0xFB, 0x90, 0xC0])
    frame_size = 417  # floor(144 * 128000 / 44100)
    frame = header + bytes(frame_size - len(header))
    return frame * n_frames


def test_voice_line_workflow_measures_real_mp3_duration_via_tinytag(
    session: Session, app_config: AppConfig, tmp_path
) -> None:
    """Milestone 9 Creator-tier compatibility fix: an .mp3 output file's
    duration is measured via tinytag, exactly as authoritatively as the
    .wav path measures via Python's wave module -- never invented."""
    mp3_path = tmp_path / "elevenlabs_test.mp3"
    mp3_path.write_bytes(_minimal_mp3_bytes(n_frames=10))

    duration = VoiceLineWorkflow._measure_duration_seconds(mp3_path)

    assert duration == pytest.approx(10 * (1152 / 44100))


def test_voice_line_workflow_duration_none_for_unrecognized_extension(
    tmp_path,
) -> None:
    other_path = tmp_path / "not_audio.txt"
    other_path.write_bytes(b"not audio")

    assert VoiceLineWorkflow._measure_duration_seconds(other_path) is None


def test_voice_line_workflow_direct_text_path_sets_dialogue_line_id(
    session: Session, app_config: AppConfig
) -> None:
    from app.core.services.scene_service import SceneService

    episode = _episode(session)
    scene = SceneService().add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    line = SceneService().sync_dialogue_lines(session, scene.id)[0]
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        episode_id=episode.id,
        dialogue_line_id=line.id,
        rendered_prompt_text="مرحباً",
    )

    result = workflow.run(ctx)

    assert result.asset.dialogue_line_id == line.id


def test_voice_line_workflow_forwards_model_id_override_unchanged(
    session: Session, app_config: AppConfig
) -> None:
    """A per-line performance-cue model override (e.g. eleven_v3 for a
    laugh cue) placed in ctx.parameters must reach
    GenerationRequest.parameters verbatim -- the workflow must not
    strip, rename, or otherwise touch it. This is what makes the
    override's provenance trustworthy: GenerationJob.parameters is this
    same dict, persisted as-is."""
    episode = _episode(session)
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        episode_id=episode.id,
        rendered_prompt_text="[laughs] دبدوبك يحب اللعب في العشب!",
        parameters={
            "voice_id": "rFDdsCQRZCUL8cPOWtnP",
            "model_id": "eleven_v3",
            "output_format": "mp3_44100_128",
            "authored_text": "هاها! دبدوبك يحب اللعب في العشب!",
            "normalized_text_sent": "[laughs] دبدوبك يحب اللعب في العشب!",
        },
    )

    result = workflow.run(ctx)

    assert result.generation_request.parameters["model_id"] == "eleven_v3"
    assert result.generation_request.parameters["voice_id"] == "rFDdsCQRZCUL8cPOWtnP"
    assert result.generation_request.parameters["authored_text"] == "هاها! دبدوبك يحب اللعب في العشب!"
    assert result.generation_request.prompt_text == "[laughs] دبدوبك يحب اللعب في العشب!"


def test_voice_line_workflow_legacy_template_path_still_works(
    session: Session, app_config: AppConfig
) -> None:
    """rendered_prompt_text left unset (default None) -- the
    pre-Milestone-9 template path must still work unchanged."""
    episode = _episode(session)
    template = _template(
        session,
        name="voice_line_legacy",
        category=PromptCategory.VOICE,
        prompt_type=PromptType.VOICE,
        text_en="Say: hello there.",
    )
    workflow = VoiceLineWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        episode_id=episode.id,
    )

    result = workflow.run(ctx)

    assert result.generation_request.prompt_text == "Say: hello there."
    assert result.asset.prompt_used_id == template.id
    assert result.asset.duration_seconds is None  # legacy path never measures duration


# --- ThumbnailWorkflow ---------------------------------------------------


def test_thumbnail_workflow_creates_draft_asset(session: Session, app_config: AppConfig) -> None:
    episode = _episode(session)
    template = _template(
        session,
        name="thumbnail_prompt",
        category=PromptCategory.THUMBNAIL,
        prompt_type=PromptType.IMAGE,
        text_en="A bright, eye-catching thumbnail.",
    )
    workflow = ThumbnailWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(
        session=session,
        provider=MockProvider(),
        prompt_template_id=template.id,
        episode_id=episode.id,
    )

    result = workflow.run(ctx)

    assert result.asset.asset_type == AssetType.THUMBNAIL
    assert result.asset.episode_id == episode.id
    assert result.asset.role is None  # no automatic promotion to "final_thumbnail"


def test_thumbnail_workflow_requires_episode(session: Session, app_config: AppConfig) -> None:
    template = _template(
        session,
        name="thumbnail_missing",
        category=PromptCategory.THUMBNAIL,
        prompt_type=PromptType.IMAGE,
        text_en="A thumbnail.",
    )
    workflow = ThumbnailWorkflow(asset_import=_asset_import(app_config))
    ctx = WorkflowContext(session=session, provider=MockProvider(), prompt_template_id=template.id)

    with pytest.raises(ValidationError, match="episode_id"):
        workflow.run(ctx)


def test_two_scene_workflow_runs_never_collide_on_checksum(
    session: Session, app_config: AppConfig
) -> None:
    """Two different scenes must not be rejected as duplicate imports of each other."""
    episode = _episode(session)
    scene_a = _scene(session, episode)
    scene_b = Scene(episode_id=episode.id, order_index=2, location="beach")
    session.add(scene_b)
    session.flush()

    template_a = _template(
        session,
        name="scene_a",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A quiet forest.",
    )
    template_b = _template(
        session,
        name="scene_b",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A sunny beach.",
    )
    asset_import = _asset_import(app_config)
    workflow = SceneImageWorkflow(asset_import=asset_import)

    result_a = workflow.run(
        WorkflowContext(
            session=session,
            provider=MockProvider(),
            prompt_template_id=template_a.id,
            episode_id=episode.id,
            scene_id=scene_a.id,
        )
    )
    result_b = workflow.run(
        WorkflowContext(
            session=session,
            provider=MockProvider(),
            prompt_template_id=template_b.id,
            episode_id=episode.id,
            scene_id=scene_b.id,
        )
    )

    assert result_a.asset.id != result_b.asset.id
    assert result_a.asset.checksum != result_b.asset.checksum
