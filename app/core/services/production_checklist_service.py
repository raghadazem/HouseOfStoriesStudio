"""ProductionChecklistService — "is this Episode ready to publish?"

Runs every check the founder specified and returns one structured
report: which checks passed, which failed, which failures are
*blocking* (prevent Ready to Publish) vs. *warnings* (worth fixing but
don't block), a readiness percentage, and a final boolean.
:class:`~app.core.services.episode_service.EpisodeService` calls this
before allowing the ``ready_to_publish`` transition; nothing here
mutates any data — it's a pure read-only evaluation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.db.enums import (
    ApprovalDecision,
    ApprovalStatus,
    CharacterVersionStatus,
    PipelineStage,
    ProductionTaskStatus,
    ScriptStatus,
    StageState,
)
from app.core.models import Asset, CharacterVersion, Episode, ProductionTask, Script, Song
from app.core.models.asset import (
    ROLE_FINAL_MUSIC,
    ROLE_FINAL_THUMBNAIL,
    ROLE_FINAL_VIDEO,
    ROLE_FINAL_VOICE,
)
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import NotFoundError
from app.core.services.license_service import LicenseService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService

# Which workspace stage each CheckResult belongs to — used only by
# evaluate_stage_summary() to re-bucket results evaluate() already
# computed; it changes nothing about what evaluate()/is_ready mean.
_CHECK_STAGE: dict[str, str] = {
    "arabic_title_exists": "script",
    "english_title_exists": "script",
    "lesson_exists": "script",
    "runtime_target_valid": "script",
    "script_ready_for_production": "script",
    "scenes_exist": "storyboard",
    "scene_sequence_valid": "storyboard",
    "scene_fields_complete": "storyboard",
    "all_scenes_approved": "storyboard",
    "character_versions_approved_and_active": "storyboard",
    "linked_assets_use_approved_character_versions": "storyboard",
    "thumbnail_exists": "images",
    "thumbnail_approved": "images",
    "final_voice_ready": "voice",
    "final_music_ready": "music",
    "three_initial_shorts_exist": "video",
    "shorts_valid": "video",
    "final_video_asset_exists": "video",
    "final_video_asset_approved": "video",
    "export_metadata_complete": "seo",
    "license_requirements_satisfied": "export",
    "commercial_use_acceptable": "export",
    "attribution_present": "export",
    "production_tasks_complete": "export",
    "no_rejected_final_assets": "export",
}

_STAGES_IN_ORDER = (
    "script", "storyboard", "images", "voice", "music", "video", "seo", "export",
)


@dataclass
class StageStatus:
    """One workspace stage's own completion state (Episode Workspace).

    Computed by :meth:`ProductionChecklistService.evaluate_stage_summary`
    by re-bucketing the same :class:`CheckResult` data
    :meth:`ProductionChecklistService.evaluate` already computed — no
    validation logic is duplicated here.
    """

    stage: str
    status: StageState
    reason: str | None = None


@dataclass
class CheckResult:
    """One named pass/fail entry in a :class:`ChecklistReport`."""

    name: str
    passed: bool
    blocking: bool
    message: str


@dataclass
class ChecklistReport:
    """The full result of :meth:`ProductionChecklistService.evaluate`."""

    episode_id: uuid.UUID
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if c.passed]

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.failed_checks if not c.blocking]

    @property
    def blocking_issues(self) -> list[CheckResult]:
        return [c for c in self.failed_checks if c.blocking]

    @property
    def readiness_percent(self) -> float:
        if not self.checks:
            return 0.0
        return round(len(self.passed_checks) / len(self.checks) * 100, 1)

    @property
    def is_ready(self) -> bool:
        return not self.blocking_issues


class ProductionChecklistService:
    """Evaluates every founder-specified readiness rule for one episode."""

    def __init__(
        self,
        license_service: LicenseService | None = None,
        scene_service: SceneService | None = None,
        short_service: ShortService | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._licenses = license_service or LicenseService()
        self._scenes = scene_service or SceneService()
        self._shorts = short_service or ShortService()
        self._approvals = approval_service or ApprovalService()

    def evaluate(self, session: Session, episode_id: uuid.UUID) -> ChecklistReport:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        report = ChecklistReport(episode_id=episode_id)

        self._check_titles_and_lesson(episode, report)
        self._check_runtime(episode, report)
        self._check_script(session, episode_id, report)

        scenes = self._scenes.list_episode_scenes(session, episode_id)
        self._check_scenes(session, episode_id, scenes, report)

        shorts = self._shorts.list_episode_shorts(session, episode_id)
        self._check_shorts(session, episode_id, shorts, report)

        self._check_final_video(session, episode_id, report)
        self._check_thumbnail(session, episode_id, report)
        self._check_voice_and_music(session, episode, report)
        self._check_licensing(session, episode_id, report)
        self._check_characters(session, episode, report)
        self._check_tasks(session, episode_id, report)
        self._check_no_rejected_final_assets(session, episode_id, report)
        self._check_export_metadata(episode, report)

        return report

    def evaluate_stage_summary(
        self, session: Session, episode_id: uuid.UUID
    ) -> list[StageStatus]:
        """The Episode Workspace's 8-stage summary, derived from one :meth:`evaluate` call.

        Re-buckets ``evaluate()``'s existing :class:`CheckResult` list by
        workspace stage (see ``_CHECK_STAGE``) rather than re-validating
        anything — the only genuinely new logic here is the small,
        stage-specific "has this even started yet" distinction (e.g. zero
        scenes vs. incomplete scenes) that a flat pass/fail list can't
        express on its own, and the per-scene narration detail for the
        "voice" stage's blocking reason.
        """
        report = self.evaluate(session, episode_id)
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        by_stage: dict[str, list[CheckResult]] = {stage: [] for stage in _STAGES_IN_ORDER}
        for check in report.checks:
            stage = _CHECK_STAGE.get(check.name)
            if stage is not None:
                by_stage[stage].append(check)

        summaries = []
        for stage in _STAGES_IN_ORDER:
            handler = getattr(self, f"_stage_status_{stage}")
            summaries.append(handler(session, episode_id, episode, by_stage[stage], report))
        return summaries

    @staticmethod
    def _status_from_checks(stage: str, checks: list[CheckResult], *, not_started: bool) -> StageStatus:
        """The default rule most stages use: not-started / blocked / ready-with-warnings / completed."""
        if not_started:
            return StageStatus(stage, StageState.NOT_STARTED)
        blocking_failures = [c for c in checks if c.blocking and not c.passed]
        if blocking_failures:
            return StageStatus(stage, StageState.BLOCKED, blocking_failures[0].message)
        warning_failures = [c for c in checks if not c.blocking and not c.passed]
        if warning_failures:
            return StageStatus(stage, StageState.READY, warning_failures[0].message)
        return StageStatus(stage, StageState.COMPLETED)

    def _stage_status_script(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        script = session.query(Script).filter_by(episode_id=episode_id).one_or_none()
        has_content = script is not None and bool(script.full_script and script.full_script.strip())
        return self._status_from_checks("script", checks, not_started=not has_content)

    def _stage_status_storyboard(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        no_scenes = any(c.name == "scenes_exist" and not c.passed for c in checks)
        return self._status_from_checks("storyboard", checks, not_started=no_scenes)

    def _stage_status_images(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        unready = self._characters_missing_approved_version(session, episode)
        if unready:
            return StageStatus(
                "images", StageState.BLOCKED,
                f"Missing approved character reference art for: {', '.join(unready)}.",
            )
        no_thumbnail = any(c.name == "thumbnail_exists" and not c.passed for c in checks)
        return self._status_from_checks("images", checks, not_started=no_thumbnail)

    def _stage_status_voice(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        scenes = self._scenes.list_episode_scenes(session, episode_id)
        if not scenes:
            return StageStatus("voice", StageState.NOT_STARTED)
        missing_narration = [s for s in scenes if not (s.dialogue_ar and s.dialogue_ar.strip())]
        if missing_narration:
            first = missing_narration[0]
            return StageStatus(
                "voice", StageState.BLOCKED, f"Scene {first.order_index} has no narration."
            )
        return self._status_from_checks("voice", checks, not_started=False)

    def _stage_status_music(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        if not episode.includes_song:
            return StageStatus("music", StageState.COMPLETED, "Episode does not include a song.")
        has_music_asset = (
            session.query(Asset)
            .filter_by(episode_id=episode_id, role=ROLE_FINAL_MUSIC)
            .count() > 0
        )
        if not has_music_asset:
            song = session.query(Song).filter_by(episode_id=episode_id).one_or_none()
            if song is not None and song.lyrics_ar and song.lyrics_ar.strip():
                return StageStatus(
                    "music", StageState.IN_PROGRESS,
                    "Song lyrics and production notes are written; awaiting final produced audio.",
                )
        return self._status_from_checks("music", checks, not_started=not has_music_asset)

    def _stage_status_video(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        unready = self._characters_missing_approved_version(session, episode)
        if unready:
            return StageStatus(
                "video", StageState.BLOCKED,
                f"Missing approved character reference art for: {', '.join(unready)}.",
            )
        no_video = any(c.name == "final_video_asset_exists" and not c.passed for c in checks)
        no_shorts = any(c.name == "three_initial_shorts_exist" and not c.passed for c in checks)
        return self._status_from_checks("video", checks, not_started=no_video and no_shorts)

    def _stage_status_seo(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        any_field_set = bool(episode.description_ar or episode.description_en or episode.hashtags)
        complete = all(c.passed for c in checks)
        if complete:
            return StageStatus("seo", StageState.COMPLETED)
        if not any_field_set:
            return StageStatus("seo", StageState.NOT_STARTED)
        return StageStatus("seo", StageState.IN_PROGRESS, checks[0].message if checks else None)

    def _stage_status_export(
        self, session: Session, episode_id: uuid.UUID, episode: Episode,
        checks: list[CheckResult], report: ChecklistReport,
    ) -> StageStatus:
        if episode.pipeline_stage == PipelineStage.PUBLISHED:
            return StageStatus("export", StageState.COMPLETED)
        if report.is_ready:
            return StageStatus("export", StageState.READY)
        first_blocking = next((c for c in report.blocking_issues), None)
        return StageStatus(
            "export", StageState.BLOCKED, first_blocking.message if first_blocking else None
        )

    @staticmethod
    def _add(report: ChecklistReport, name: str, passed: bool, blocking: bool, message: str) -> None:
        report.checks.append(CheckResult(name=name, passed=passed, blocking=blocking, message=message))

    def _check_titles_and_lesson(self, episode: Episode, report: ChecklistReport) -> None:
        self._add(
            report, "arabic_title_exists", bool(episode.title_ar and episode.title_ar.strip()),
            True, "Arabic title is set." if episode.title_ar else "Arabic title is missing.",
        )
        self._add(
            report, "english_title_exists", bool(episode.title_en and episode.title_en.strip()),
            True, "English title is set." if episode.title_en else "English title is missing.",
        )
        self._add(
            report, "lesson_exists", bool(episode.lesson and episode.lesson.strip()),
            True, "Lesson is set." if episode.lesson else "Lesson is missing.",
        )

    def _check_runtime(self, episode: Episode, report: ChecklistReport) -> None:
        valid = (
            episode.runtime_target_minutes_min > 0
            and episode.runtime_target_minutes_max >= episode.runtime_target_minutes_min
        )
        self._add(
            report, "runtime_target_valid", valid,
            True, "Runtime target is valid." if valid else "Runtime target min/max is invalid.",
        )

    def _check_script(self, session: Session, episode_id: uuid.UUID, report: ChecklistReport) -> None:
        script = session.query(Script).filter_by(episode_id=episode_id).one_or_none()
        approved = script is not None and script.status == ScriptStatus.APPROVED
        self._add(
            report, "script_ready_for_production", approved,
            True,
            "Script is approved." if approved
            else "Script has not been created yet." if script is None
            else f"Script is {script.status.value}, not yet approved.",
        )

    def _check_scenes(
        self, session: Session, episode_id: uuid.UUID, scenes: list, report: ChecklistReport
    ) -> None:
        has_scenes = len(scenes) > 0
        self._add(
            report, "scenes_exist", has_scenes,
            True, f"{len(scenes)} scene(s) exist." if has_scenes else "No scenes exist yet.",
        )
        sequence = self._scenes.validate_scene_sequence(session, episode_id)
        self._add(
            report, "scene_sequence_valid", sequence.is_valid,
            True, "Scene sequence is contiguous." if sequence.is_valid else "; ".join(sequence.issues),
        )
        incomplete = [s for s in scenes if not (s.description and s.dialogue_ar)]
        self._add(
            report, "scene_fields_complete", not incomplete,
            False,
            "All scenes have a description and dialogue." if not incomplete
            else f"{len(incomplete)} scene(s) missing description/dialogue.",
        )
        not_approved = [
            s for s in scenes
            if self._approvals.get_current_approval_state(session, "scene", s.id)
            != ApprovalDecision.APPROVED
        ]
        self._add(
            report, "all_scenes_approved", has_scenes and not not_approved,
            True,
            "All scenes are approved." if has_scenes and not not_approved
            else "No scenes exist yet." if not has_scenes
            else f"{len(not_approved)} scene(s) not yet approved: "
            f"{[s.order_index for s in not_approved]}.",
        )

    def _check_shorts(
        self, session: Session, episode_id: uuid.UUID, shorts: list, report: ChecklistReport
    ) -> None:
        has_three = {1, 2, 3}.issubset({s.short_index for s in shorts})
        self._add(
            report, "three_initial_shorts_exist", has_three,
            True, "The three initial Shorts exist." if has_three else "Fewer than 3 initial Shorts exist.",
        )
        invalid: list[tuple[int, list[str]]] = []
        for short in shorts:
            validation = self._shorts.validate_short(session, short.id)
            if not validation.is_valid:
                invalid.append((short.short_index, validation.issues))
        self._add(
            report, "shorts_valid", not invalid,
            False, "All Shorts are content-complete." if not invalid else f"Incomplete Shorts: {invalid}",
        )

    def _check_final_video(self, session: Session, episode_id: uuid.UUID, report: ChecklistReport) -> None:
        asset = self._latest_role_asset(session, episode_id, ROLE_FINAL_VIDEO)
        self._add(
            report, "final_video_asset_exists", asset is not None,
            True, "Final video asset exists." if asset is not None else "No final video asset linked.",
        )
        approved = asset is not None and asset.approval_status == ApprovalStatus.APPROVED
        self._add(
            report, "final_video_asset_approved", approved,
            True, "Final video asset is approved." if approved else "Final video asset is missing or not approved.",
        )

    def _check_thumbnail(self, session: Session, episode_id: uuid.UUID, report: ChecklistReport) -> None:
        asset = self._latest_role_asset(session, episode_id, ROLE_FINAL_THUMBNAIL)
        self._add(
            report, "thumbnail_exists", asset is not None,
            True, "Thumbnail exists." if asset is not None else "No thumbnail asset linked.",
        )
        approved = asset is not None and asset.approval_status == ApprovalStatus.APPROVED
        self._add(
            report, "thumbnail_approved", approved,
            True, "Thumbnail is approved." if approved else "Thumbnail is missing or not approved.",
        )

    def _check_voice_and_music(
        self, session: Session, episode: Episode, report: ChecklistReport
    ) -> None:
        voice = self._latest_role_asset(session, episode.id, ROLE_FINAL_VOICE)
        voice_ok = voice is not None and voice.approval_status == ApprovalStatus.APPROVED
        self._add(
            report, "final_voice_ready", voice_ok,
            True, "Final voice asset is approved." if voice_ok else "Final voice asset is missing or not approved.",
        )
        if episode.includes_song:
            music = self._latest_role_asset(session, episode.id, ROLE_FINAL_MUSIC)
            music_ok = music is not None and music.approval_status == ApprovalStatus.APPROVED
            self._add(
                report, "final_music_ready", music_ok,
                True,
                "Final music asset is approved." if music_ok
                else "Episode includes a song but no approved final music asset is linked.",
            )
        else:
            self._add(report, "final_music_ready", True, True, "Episode does not include a song.")

    def _check_licensing(self, session: Session, episode_id: uuid.UUID, report: ChecklistReport) -> None:
        final_assets = self._final_assets(session, episode_id)
        if not final_assets:
            self._add(report, "license_requirements_satisfied", False, True, "No final assets exist yet to license.")
            self._add(report, "commercial_use_acceptable", False, True, "No final assets exist yet to evaluate.")
            self._add(report, "attribution_present", False, True, "No final assets exist yet to evaluate.")
            return

        no_license: list[str] = []
        commercial_issues: list[str] = []
        attribution_issues: list[str] = []
        for asset in final_assets:
            history = self._licenses.list_asset_license_history(session, asset.id)
            if not history:
                no_license.append(asset.role or str(asset.id))
                continue
            latest = history[-1]
            if latest.commercial_use_allowed is not True:
                commercial_issues.append(f"{asset.role}: commercial_use_allowed={latest.commercial_use_allowed}")
            if latest.attribution_required and not (
                latest.attribution_text and latest.attribution_text.strip()
            ):
                attribution_issues.append(f"{asset.role}: attribution required but missing")

        self._add(
            report, "license_requirements_satisfied", not no_license,
            True, "Every final asset has a license record." if not no_license
            else f"Final assets missing any license record: {no_license}",
        )
        self._add(
            report, "commercial_use_acceptable", not commercial_issues,
            True, "All final assets have acceptable commercial-use status." if not commercial_issues
            else f"Issues: {commercial_issues}",
        )
        self._add(
            report, "attribution_present", not attribution_issues,
            True, "Required attribution is present." if not attribution_issues
            else f"Issues: {attribution_issues}",
        )

    @staticmethod
    def _characters_missing_approved_version(session: Session, episode: Episode) -> list[str]:
        """Slugs of every featured character with no approved, active ``CharacterVersion``.

        Shared by :meth:`_check_characters` (the ``character_versions_approved_and_active``
        checklist entry) and the Images/Video stage handlers — the same
        "does this episode have real, approved reference art yet" test,
        computed once rather than twice.
        """
        not_ready: list[str] = []
        for character in episode.characters_featured:
            if character.active_version_id is None:
                not_ready.append(character.slug)
                continue
            version = session.get(CharacterVersion, character.active_version_id)
            if version is None or version.status != CharacterVersionStatus.APPROVED_CANON:
                not_ready.append(character.slug)
        return not_ready

    def _check_characters(self, session: Session, episode: Episode, report: ChecklistReport) -> None:
        not_ready = self._characters_missing_approved_version(session, episode)
        self._add(
            report, "character_versions_approved_and_active", not not_ready,
            True,
            "All featured characters have an approved, active version." if not not_ready
            else f"Characters missing an approved active version: {not_ready}",
        )

        linked = (
            session.query(Asset)
            .filter(Asset.episode_id == episode.id, Asset.character_version_id.isnot(None))
            .all()
        )
        mismatched = [
            a.id for a in linked
            if a.character_version is not None
            and a.character_version.status != CharacterVersionStatus.APPROVED_CANON
        ]
        self._add(
            report, "linked_assets_use_approved_character_versions", not mismatched,
            False,
            "All character-linked assets use an approved version." if not mismatched
            else f"{len(mismatched)} asset(s) reference a non-approved character version.",
        )

    def _check_tasks(self, session: Session, episode_id: uuid.UUID, report: ChecklistReport) -> None:
        tasks = session.query(ProductionTask).filter_by(episode_id=episode_id).all()
        incomplete = [t for t in tasks if t.status != ProductionTaskStatus.DONE]
        self._add(
            report, "production_tasks_complete", not incomplete,
            True, "All production tasks are done." if not incomplete
            else f"{len(incomplete)} task(s) not yet done.",
        )

    def _check_no_rejected_final_assets(
        self, session: Session, episode_id: uuid.UUID, report: ChecklistReport
    ) -> None:
        rejected = [
            a for a in self._final_assets(session, episode_id)
            if a.approval_status == ApprovalStatus.REJECTED
        ]
        self._add(
            report, "no_rejected_final_assets", not rejected,
            True, "No rejected asset is linked as final." if not rejected
            else f"{len(rejected)} rejected asset(s) still linked with a final_* role.",
        )

    def _check_export_metadata(self, episode: Episode, report: ChecklistReport) -> None:
        complete = bool(episode.description_ar and episode.description_en and episode.hashtags)
        self._add(
            report, "export_metadata_complete", complete,
            False, "Export metadata is complete." if complete
            else "Export metadata (description_ar/description_en/hashtags) is incomplete.",
        )

    @staticmethod
    def _latest_role_asset(session: Session, episode_id: uuid.UUID, role: str) -> Asset | None:
        return (
            session.query(Asset)
            .filter_by(episode_id=episode_id, role=role)
            .order_by(Asset.created_at.desc())
            .first()
        )

    @staticmethod
    def _final_assets(session: Session, episode_id: uuid.UUID) -> list[Asset]:
        return (
            session.query(Asset)
            .filter(Asset.episode_id == episode_id, Asset.role.isnot(None), Asset.role.like("final_%"))
            .all()
        )
