"""Integration tests for Milestone 6: Episode 001's real production content.

Exercises ``populate_episode_001_production_content`` end to end against
the real service layer (Script, Scene, Song, Short, Episode, and the
readiness checklist) — the thing this milestone is actually about: can
the studio manage one complete, real episode, honestly reporting what
is and isn't ready, without ever faking a review that didn't happen.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db.engine import create_session_factory
from app.core.db.enums import ApprovalDecision, CharacterVersionStatus, ScriptStatus, StageState
from app.core.db.episode_001_production import TORTOR_SLUG, populate_episode_001_production_content
from app.core.db.seed import BILSAN_SLUG, EPISODE_001_SLUG, MELISSA_SLUG
from app.core.models import Character, CharacterVersion, Episode, Script, Short, Song
from app.core.services.approval_service import ApprovalService
from app.core.services.episode_service import EpisodeService
from app.core.services.production_checklist_service import ProductionChecklistService
from app.core.services.scene_service import SceneService


def test_populate_creates_fifteen_ordered_scenes(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    assert [s.order_index for s in episode.scenes] == list(range(1, 16))
    assert all(s.title for s in episode.scenes)


def test_populate_scene_duration_matches_the_runtime_target(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    total = SceneService().calculate_total_scene_duration(session, episode.id)
    # 8-10 minute target (480-600s); real content should land inside it.
    assert 480 <= total <= 600


def test_populate_script_is_real_content_but_not_approved(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    script = session.query(Script).filter_by(episode_id=episode.id).one()
    assert script.full_script and len(script.full_script) > 500
    assert "مساعدة" in script.summary
    assert script.status == ScriptStatus.DRAFT  # no fake approval


def test_populate_features_all_three_characters_as_unapproved_drafts(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    slugs = {c.slug for c in episode.characters_featured}
    assert slugs == {MELISSA_SLUG, BILSAN_SLUG, TORTOR_SLUG}

    for slug in slugs:
        character = session.query(Character).filter_by(slug=slug).one()
        assert character.active_version_id is None
        version = character.versions[0]
        assert version.status == CharacterVersionStatus.DRAFT  # no fake approval


def test_populate_composed_prompts_have_no_locked_character_data_yet(session: Session) -> None:
    """Truthful composition: since no character has an approved active
    version, the composed prompt correctly omits any "Characters:"
    section — it isn't faked in to make the prompt look more complete
    than the actual production state supports."""
    episode = populate_episode_001_production_content(session)
    discovery_scene = next(s for s in episode.scenes if s.order_index == 3)
    assert discovery_scene.prompt_text
    assert "Characters:" not in discovery_scene.prompt_text
    assert "Visual description:" in discovery_scene.prompt_text
    assert discovery_scene.negative_prompt_text  # the manual baseline still merges in


def test_populate_song_data(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    assert episode.includes_song is True
    song = session.query(Song).filter_by(episode_id=episode.id).one()
    assert "معاً نستطيع" in song.lyrics_ar
    assert 45 <= song.duration_seconds <= 75
    assert song.suno_style_prompt


def test_populate_voice_package_covers_every_named_speaker(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    lines = SceneService().build_voice_package(session, episode.id)
    speakers = {line.speaker for line in lines}
    assert {"ميليسا", "بيلسان", "الراوي", "طُرطُر"}.issubset(speakers)
    assert len(lines) > 20


def test_populate_creates_three_content_complete_shorts(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    shorts = session.query(Short).filter_by(episode_id=episode.id).order_by(Short.short_index).all()
    assert len(shorts) == 3
    for short in shorts:
        assert short.title_ar
        assert short.spoken_text_ar
        assert short.on_screen_text_ar
        assert short.target_duration_seconds
        assert short.editing_notes
        assert short.source_scenes  # linked, not just described


def test_populate_seo_metadata(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    assert episode.description_ar and episode.description_en
    assert episode.hashtags
    assert episode.credits_text


def test_readiness_blocks_images_and_video_for_missing_character_references(
    session: Session,
) -> None:
    """No fake approvals: real content exists, but Images/Video correctly
    report BLOCKED (not a fabricated COMPLETED) because no character has
    approved reference artwork yet."""
    episode = populate_episode_001_production_content(session)
    checklist = ProductionChecklistService()
    summary = {s.stage: s for s in checklist.evaluate_stage_summary(session, episode.id)}

    assert summary["images"].status == StageState.BLOCKED
    for slug in (MELISSA_SLUG, BILSAN_SLUG, TORTOR_SLUG):
        assert slug in summary["images"].reason
        assert slug in summary["video"].reason
    assert summary["video"].status == StageState.BLOCKED

    # None of the 8 stages is a fake COMPLETED except the genuinely
    # complete one (SEO) and music's honest "written, not yet produced".
    completed_stages = {stage for stage, status in summary.items() if status.status == StageState.COMPLETED}
    assert completed_stages == {"seo"}


def test_readiness_reflects_no_approved_scenes_or_script(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    approvals = ApprovalService()
    for scene in episode.scenes:
        assert approvals.get_current_approval_state(session, "scene", scene.id) != ApprovalDecision.APPROVED
    script = session.query(Script).filter_by(episode_id=episode.id).one()
    assert approvals.get_current_approval_state(session, "script", script.id) != ApprovalDecision.APPROVED

    report = ProductionChecklistService().evaluate(session, episode.id)
    assert report.is_ready is False


def test_populate_is_idempotent_across_repeated_calls(session: Session) -> None:
    populate_episode_001_production_content(session)
    populate_episode_001_production_content(session)

    episode = session.query(Episode).filter_by(slug=EPISODE_001_SLUG).one()
    assert session.query(Character).count() == 3
    assert len(episode.scenes) == 15
    assert len(episode.shorts) == 3
    assert session.query(Song).filter_by(episode_id=episode.id).count() == 1
    assert session.query(CharacterVersion).count() == 3  # no duplicate versions either


def test_populate_never_overwrites_a_human_edit(session: Session) -> None:
    episode = populate_episode_001_production_content(session)
    EpisodeService().update_episode(session, episode.id, description_ar="EDITED BY A HUMAN")
    session.commit()

    episode_again = populate_episode_001_production_content(session)

    assert episode_again.description_ar == "EDITED BY A HUMAN"


def test_populate_persists_across_a_close_and_reopen(engine: Engine) -> None:
    """Simulates closing and reopening the app: a brand-new Session on
    the same database must see every populated field, not just the one
    that wrote it."""
    factory = create_session_factory(engine)

    with factory() as first_session:
        populate_episode_001_production_content(first_session)

    with factory() as reopened_session:
        episode = reopened_session.query(Episode).filter_by(slug=EPISODE_001_SLUG).one()
        assert len(episode.scenes) == 15
        assert len(episode.shorts) == 3
        script = reopened_session.query(Script).filter_by(episode_id=episode.id).one()
        assert script.full_script
        song = reopened_session.query(Song).filter_by(episode_id=episode.id).one()
        assert song.lyrics_ar
        assert {c.slug for c in episode.characters_featured} == {
            MELISSA_SLUG, BILSAN_SLUG, TORTOR_SLUG,
        }
