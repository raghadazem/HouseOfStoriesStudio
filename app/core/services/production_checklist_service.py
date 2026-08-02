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

from app.core.db.enums import ApprovalStatus, CharacterVersionStatus, ProductionTaskStatus
from app.core.models import Asset, CharacterVersion, Episode, ProductionTask
from app.core.models.asset import (
    ROLE_FINAL_MUSIC,
    ROLE_FINAL_THUMBNAIL,
    ROLE_FINAL_VIDEO,
    ROLE_FINAL_VOICE,
)
from app.core.services.exceptions import NotFoundError
from app.core.services.license_service import LicenseService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService


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
    ) -> None:
        self._licenses = license_service or LicenseService()
        self._scenes = scene_service or SceneService()
        self._shorts = short_service or ShortService()

    def evaluate(self, session: Session, episode_id: uuid.UUID) -> ChecklistReport:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        report = ChecklistReport(episode_id=episode_id)

        self._check_titles_and_lesson(episode, report)
        self._check_runtime(episode, report)

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

    def _check_characters(self, session: Session, episode: Episode, report: ChecklistReport) -> None:
        not_ready: list[str] = []
        for character in episode.characters_featured:
            if character.active_version_id is None:
                not_ready.append(character.slug)
                continue
            version = session.get(CharacterVersion, character.active_version_id)
            if version is None or version.status != CharacterVersionStatus.APPROVED_CANON:
                not_ready.append(character.slug)
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
