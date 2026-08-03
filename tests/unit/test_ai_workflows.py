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
from app.core.services.exceptions import ValidationError
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


def _character_version(session: Session) -> CharacterVersion:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    version = CharacterVersion(
        character_id=character.id,
        version_number="v01",
        master_prompt="a young girl",
        color_palette=["#ffcc00"],
    )
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
