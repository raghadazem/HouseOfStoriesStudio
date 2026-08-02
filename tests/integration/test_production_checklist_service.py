"""Integration test: an Episode's readiness checklist, from totally incomplete to fully ready.

Exercises every service together (Episode, Scene, Short, Character,
CharacterVersion, Asset import semantics, License, ProductionTask) to
prove the checklist's failure and success paths both work against the
real service layer, not just mocked pieces.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset
from app.core.services.character_service import CharacterService
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.episode_service import EpisodeService
from app.core.services.license_service import LicenseService
from app.core.services.production_checklist_service import ProductionChecklistService
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService


def _approved_asset(session: Session, *, episode_id, role: str, asset_type=AssetType.VIDEO, **overrides) -> Asset:
    relative_path = overrides.get("relative_path", f"episodes/ep001/final/{role}.bin")
    defaults = {
        "asset_type": asset_type,
        "original_filename": f"{role}.bin",
        "relative_path": relative_path,
        "checksum": hashlib.sha256(relative_path.encode()).hexdigest(),
        "episode_id": episode_id,
        "role": role,
        "approval_status": ApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    asset = Asset(**defaults)
    session.add(asset)
    session.flush()
    return asset


def test_episode_readiness_failure_on_freshly_created_episode(session: Session) -> None:
    es = EpisodeService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
    )
    checklist = ProductionChecklistService()
    report = checklist.evaluate(session, episode.id)

    assert report.is_ready is False
    assert report.readiness_percent < 100
    blocking_names = {c.name for c in report.blocking_issues}
    assert "scenes_exist" in blocking_names
    assert "final_video_asset_exists" in blocking_names
    assert "thumbnail_exists" in blocking_names


def test_episode_readiness_success_when_everything_is_satisfied(session: Session) -> None:
    cs = CharacterService()
    cvs = CharacterVersionService()
    es = EpisodeService()
    ss = SceneService()
    shs = ShortService()
    ts = ProductionTaskService()
    ls = LicenseService()
    checklist = ProductionChecklistService()

    # Character with an approved, active version.
    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    version = cvs.create_character_version(
        session,
        melissa.id,
        visual_summary="Two ponytails, denim dress.",
        master_prompt="Melissa...",
        negative_prompt="no extras",
        color_palette=["denim blue"],
        relative_height="taller than Bilsan",
    )
    cvs.submit_character_version_for_review(session, version.id)
    cvs.approve_character_version(session, version.id, decided_by="founder")
    cvs.set_active_character_version(session, melissa.id, version.id)

    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
        character_ids=[melissa.id],
    )
    es.update_episode(
        session,
        episode.id,
        description_ar="وصف الحلقة بالعربية.",
        description_en="Episode description in English.",
        hashtags=["#kids", "#arabic"],
    )

    scene = ss.add_scene(
        session, episode.id, location="forest", description="Finding the turtle.",
        dialogue_ar="لقد وجدنا السلحفاة!",
    )

    for short in shs.list_episode_shorts(session, episode.id):
        shs.update_short(
            session, short.id,
            title_ar="عنوان", working_title_en="Title", hook_ar="خطاف", caption_ar="تعليق",
        )
        shs.link_source_scenes(session, short.id, [scene.id])
        video = _approved_asset(
            session, episode_id=episode.id, role="final_video",
            relative_path=f"episodes/ep001/shorts/{short.id}/video.mp4",
        )
        ls.add_license_record(session, video.id, license_type="original", commercial_use_allowed=True)
        session.query(Asset).filter_by(id=video.id).update({"short_id": short.id, "episode_id": None})
        short.export_asset_id = video.id
    session.flush()

    final_video = _approved_asset(session, episode_id=episode.id, role="final_video")
    final_thumb = _approved_asset(
        session, episode_id=episode.id, role="final_thumbnail", asset_type=AssetType.THUMBNAIL,
        relative_path="episodes/ep001/final/thumb.png",
    )
    final_voice = _approved_asset(
        session, episode_id=episode.id, role="final_voice", asset_type=AssetType.VOICE,
        relative_path="episodes/ep001/final/voice.wav", character_version_id=version.id,
    )
    for asset in (final_video, final_thumb, final_voice):
        ls.add_license_record(session, asset.id, license_type="original", commercial_use_allowed=True)

    for task in ts.list_tasks(session, episode.id):
        ts.complete_task(session, task.id)

    session.commit()

    report = checklist.evaluate(session, episode.id)
    failure_summary = [(c.name, c.message) for c in report.failed_checks]
    assert report.is_ready is True, f"Unexpected failures: {failure_summary}"
    assert report.readiness_percent == 100.0

    # And EpisodeService's ready_to_publish gate now succeeds.
    from app.core.db.enums import PipelineStage

    es.change_episode_status(session, episode.id, PipelineStage.READY_TO_PUBLISH)
    assert episode.pipeline_stage == PipelineStage.READY_TO_PUBLISH
    es.change_episode_status(session, episode.id, PipelineStage.PUBLISHED)
    assert episode.pipeline_stage == PipelineStage.PUBLISHED
    assert episode.published_at is not None
