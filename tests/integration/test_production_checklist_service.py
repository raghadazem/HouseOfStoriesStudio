"""Integration test: an Episode's readiness checklist, from totally incomplete to fully ready.

Exercises every service together (Episode, Scene, Short, Character,
CharacterVersion, Asset import semantics, License, ProductionTask) to
prove the checklist's failure and success paths both work against the
real service layer, not just mocked pieces.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType, StageState
from app.core.models import Asset
from app.core.services.character_service import CharacterService
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.episode_service import EpisodeService
from app.core.services.license_service import LicenseService
from app.core.services.production_checklist_service import ProductionChecklistService
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.scene_service import SceneService
from app.core.services.script_service import ScriptService
from app.core.services.short_service import ShortService
from app.core.services.song_service import SongService


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
    scripts = ScriptService()
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

    script = scripts.get_or_create_script(session, episode.id)
    scripts.update_script(session, script.id, full_script="Once upon a time...")
    scripts.submit_script_ready(session, script.id)
    scripts.approve_script(session, script.id, decided_by="founder")

    scene = ss.add_scene(
        session, episode.id, location="forest", description="Finding the turtle.",
        dialogue_ar="لقد وجدنا السلحفاة!",
    )
    ss.approve_scene(session, scene.id, decided_by="founder")

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

    # The Episode Workspace's 8-stage summary agrees: every stage completed
    # (or, for export, reflects the just-published state).
    summary = {s.stage: s.status for s in checklist.evaluate_stage_summary(session, episode.id)}
    assert all(status == StageState.COMPLETED for status in summary.values())


def test_evaluate_stage_summary_on_a_freshly_created_episode(session: Session) -> None:
    """Every stage reads NOT_STARTED (or the stage's own equivalent) before
    any work has been done — the incomplete-episode counterpart to the
    fully-ready test above."""
    es = EpisodeService()
    checklist = ProductionChecklistService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
        include_shorts=False,
        include_default_tasks=False,
    )

    summary = {s.stage: s for s in checklist.evaluate_stage_summary(session, episode.id)}

    assert summary["script"].status == StageState.NOT_STARTED
    assert summary["storyboard"].status == StageState.NOT_STARTED
    assert summary["images"].status == StageState.NOT_STARTED
    assert summary["voice"].status == StageState.NOT_STARTED
    assert summary["video"].status == StageState.NOT_STARTED
    assert summary["seo"].status == StageState.NOT_STARTED
    assert summary["music"].status == StageState.COMPLETED  # includes_song defaults to False
    assert summary["export"].status == StageState.BLOCKED


def test_evaluate_stage_summary_voice_blocked_reports_missing_narration_scene(
    session: Session,
) -> None:
    es = EpisodeService()
    ss = SceneService()
    checklist = ProductionChecklistService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
        include_shorts=False,
        include_default_tasks=False,
    )
    ss.add_scene(session, episode.id, description="Scene one.", dialogue_ar="واحد")
    ss.add_scene(session, episode.id, description="Scene two.", dialogue_ar="اثنان")
    ss.add_scene(session, episode.id, description="Scene three.", dialogue_ar="ثلاثة")
    ss.add_scene(session, episode.id, description="Scene four, missing narration.")

    summary = {s.stage: s for s in checklist.evaluate_stage_summary(session, episode.id)}

    assert summary["voice"].status == StageState.BLOCKED
    assert summary["voice"].reason == "Scene 4 has no narration."


def test_evaluate_stage_summary_images_and_video_blocked_when_character_refs_missing(
    session: Session,
) -> None:
    """A featured character with no approved active CharacterVersion blocks
    Images/Video specifically for that reason, not just "not started" —
    the truthful-readiness rule Milestone 6 requires (no fake approvals,
    no green stages the work doesn't actually support yet)."""
    cs = CharacterService()
    es = EpisodeService()
    checklist = ProductionChecklistService()

    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    bilsan = cs.create_character(session, slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
        character_ids=[melissa.id, bilsan.id],
        include_shorts=False,
        include_default_tasks=False,
    )

    summary = {s.stage: s for s in checklist.evaluate_stage_summary(session, episode.id)}

    assert summary["images"].status == StageState.BLOCKED
    assert "melissa" in summary["images"].reason
    assert "bilsan" in summary["images"].reason
    assert summary["video"].status == StageState.BLOCKED
    assert "melissa" in summary["video"].reason
    assert "bilsan" in summary["video"].reason


def test_evaluate_stage_summary_music_in_progress_when_lyrics_written(session: Session) -> None:
    """Once real song content exists but no final audio asset is linked
    yet, Music should read IN_PROGRESS, not NOT_STARTED — distinguishing
    "written, not yet produced" from "nothing written at all"."""
    es = EpisodeService()
    songs = SongService()
    checklist = ProductionChecklistService()
    episode = es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
        includes_song=True,
        include_shorts=False,
        include_default_tasks=False,
    )
    song = songs.get_or_create_song(session, episode.id)
    songs.update_song(session, song.id, lyrics_ar="معاً نستطيع")

    summary = {s.stage: s for s in checklist.evaluate_stage_summary(session, episode.id)}

    assert summary["music"].status == StageState.IN_PROGRESS
    assert "awaiting final produced audio" in summary["music"].reason
