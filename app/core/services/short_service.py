"""ShortService — the YouTube Shorts cut from a long episode.

Every long episode produces exactly three Shorts by default
(:meth:`generate_default_three_shorts`); additional Shorts may be added
later via :meth:`create_short`. A Short's source scenes must always
belong to the same episode as the Short itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, ShortStatus
from app.core.models import Asset, Episode, Scene, Short
from app.core.models.asset import ROLE_FINAL_VIDEO
from app.core.services.exceptions import NotFoundError, ValidationError

_UPDATABLE_FIELDS = {
    "title_ar",
    "working_title_en",
    "hook_ar",
    "caption_ar",
    "hashtags",
    "source_timestamp_range",
    "status",
    "export_asset_id",
    "spoken_text_ar",
    "on_screen_text_ar",
    "target_duration_seconds",
    "editing_notes",
}


@dataclass(frozen=True)
class ShortValidation:
    """Result of :meth:`ShortService.validate_short`."""

    is_valid: bool
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ShortReadiness:
    """Result of :meth:`ShortService.calculate_short_readiness`."""

    is_ready: bool
    reason: str


class ShortService:
    """CRUD, ordering, source-scene linking, and readiness for Shorts."""

    def create_short(
        self,
        session: Session,
        episode_id: uuid.UUID,
        *,
        short_index: int | None = None,
        title_ar: str | None = None,
        working_title_en: str | None = None,
        hook_ar: str | None = None,
        caption_ar: str | None = None,
        hashtags: list[str] | None = None,
        source_timestamp_range: str | None = None,
    ) -> Short:
        if session.get(Episode, episode_id) is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        shorts = self.list_episode_shorts(session, episode_id)
        count = len(shorts)
        if short_index is None:
            short_index = count + 1
        elif not (1 <= short_index <= count + 1):
            raise ValidationError(
                f"short_index must be between 1 and {count + 1} (inclusive), got {short_index}."
            )
        else:
            self._shift_up(session, shorts, from_index=short_index)

        short = Short(
            episode_id=episode_id,
            short_index=short_index,
            title_ar=title_ar,
            working_title_en=working_title_en,
            hook_ar=hook_ar,
            caption_ar=caption_ar,
            hashtags=list(hashtags or []),
            source_timestamp_range=source_timestamp_range,
            status=ShortStatus.PLANNED,
        )
        session.add(short)
        session.flush()
        return short

    @staticmethod
    def _shift_up(session: Session, shorts: list[Short], *, from_index: int) -> None:
        affected = [s for s in shorts if s.short_index >= from_index]
        for short in affected:
            short.short_index = -short.short_index
        session.flush()
        for short in affected:
            short.short_index = -short.short_index + 1
        session.flush()

    def generate_default_three_shorts(self, session: Session, episode_id: uuid.UUID) -> list[Short]:
        """Ensure exactly Shorts #1, #2, #3 exist for this episode. Idempotent."""
        if session.get(Episode, episode_id) is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        existing_indexes = {s.short_index for s in self.list_episode_shorts(session, episode_id)}
        created: list[Short] = []
        for index in (1, 2, 3):
            if index in existing_indexes:
                continue
            short = Short(episode_id=episode_id, short_index=index, status=ShortStatus.PLANNED)
            session.add(short)
            created.append(short)
        session.flush()
        return created

    def get_short(self, session: Session, short_id: uuid.UUID) -> Short:
        short = session.get(Short, short_id)
        if short is None:
            raise NotFoundError(f"Short {short_id} not found.")
        return short

    def update_short(self, session: Session, short_id: uuid.UUID, **fields: object) -> Short:
        """Edit a Short. Use :meth:`reorder_shorts` to change ``short_index``."""
        short = self.get_short(session, short_id)
        if "short_index" in fields:
            raise ValidationError("Use reorder_shorts() to change short_index, not update_short().")
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Short fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(short, key, value)
        session.flush()
        return short

    def delete_short(self, session: Session, short_id: uuid.UUID) -> None:
        short = self.get_short(session, short_id)
        episode_id = short.episode_id
        removed_index = short.short_index
        session.delete(short)
        session.flush()

        # Two-phase update — see SceneService.delete_scene for why a
        # direct decrement risks a transient unique-constraint collision.
        later_shorts = [
            s for s in self.list_episode_shorts(session, episode_id) if s.short_index > removed_index
        ]
        for later_short in later_shorts:
            later_short.short_index = -later_short.short_index
        session.flush()
        for later_short in later_shorts:
            later_short.short_index = -later_short.short_index - 1
        session.flush()

    def reorder_shorts(
        self, session: Session, episode_id: uuid.UUID, ordered_short_ids: list[uuid.UUID]
    ) -> list[Short]:
        shorts = self.list_episode_shorts(session, episode_id)
        current_ids = {s.id for s in shorts}
        given_ids = set(ordered_short_ids)
        if current_ids != given_ids:
            raise ValidationError(
                "reorder_shorts requires exactly the episode's current short ids "
                f"(missing: {current_ids - given_ids}, unexpected: {given_ids - current_ids})."
            )

        by_id = {s.id: s for s in shorts}
        for short in shorts:
            short.short_index = -short.short_index
        session.flush()
        for position, short_id in enumerate(ordered_short_ids, start=1):
            by_id[short_id].short_index = position
        session.flush()
        return self.list_episode_shorts(session, episode_id)

    def link_source_scenes(
        self, session: Session, short_id: uuid.UUID, scene_ids: list[uuid.UUID]
    ) -> Short:
        """Add scenes as sources for this Short.

        Raises:
            ValidationError: If any scene doesn't belong to the same
                episode as the Short.
        """
        short = self.get_short(session, short_id)
        scenes = session.query(Scene).filter(Scene.id.in_(scene_ids)).all()
        found_ids = {s.id for s in scenes}
        missing = set(scene_ids) - found_ids
        if missing:
            raise NotFoundError(f"Scene(s) not found: {sorted(missing)}")

        mismatched = [s.id for s in scenes if s.episode_id != short.episode_id]
        if mismatched:
            raise ValidationError(
                f"Scene(s) {mismatched} do not belong to Short {short_id}'s episode "
                f"({short.episode_id})."
            )

        already_linked = {s.id for s in short.source_scenes}
        for scene in scenes:
            if scene.id not in already_linked:
                short.source_scenes.append(scene)
        session.flush()
        return short

    def unlink_source_scene(self, session: Session, short_id: uuid.UUID, scene_id: uuid.UUID) -> Short:
        short = self.get_short(session, short_id)
        short.source_scenes = [s for s in short.source_scenes if s.id != scene_id]
        session.flush()
        return short

    def list_episode_shorts(self, session: Session, episode_id: uuid.UUID) -> list[Short]:
        return (
            session.query(Short)
            .filter_by(episode_id=episode_id)
            .order_by(Short.short_index)
            .all()
        )

    def validate_short(self, session: Session, short_id: uuid.UUID) -> ShortValidation:
        """Content-completeness check (not asset readiness — see :meth:`calculate_short_readiness`)."""
        short = self.get_short(session, short_id)
        issues: list[str] = []
        if not short.title_ar and not short.working_title_en:
            issues.append("missing a working title (Arabic or English)")
        if not short.hook_ar:
            issues.append("missing hook_ar")
        if not short.caption_ar:
            issues.append("missing caption_ar")
        if not short.source_scenes:
            issues.append("no source scenes linked")
        return ShortValidation(is_valid=not issues, issues=issues)

    def calculate_short_readiness(self, session: Session, short_id: uuid.UUID) -> ShortReadiness:
        """Is this Short's final video asset in place and approved?"""
        short = self.get_short(session, short_id)
        if short.export_asset_id is not None:
            asset = session.get(Asset, short.export_asset_id)
            if asset is not None and asset.approval_status == ApprovalStatus.APPROVED:
                return ShortReadiness(True, "Final video asset is approved.")
            if asset is not None:
                return ShortReadiness(
                    False, f"Final video asset exists but is {asset.approval_status.value}, not approved."
                )

        final_asset = (
            session.query(Asset)
            .filter_by(short_id=short_id, role=ROLE_FINAL_VIDEO)
            .order_by(Asset.created_at.desc())
            .first()
        )
        if final_asset is None:
            return ShortReadiness(False, "No final video asset has been linked to this Short.")
        if final_asset.approval_status != ApprovalStatus.APPROVED:
            return ShortReadiness(
                False,
                f"Final video asset exists but is {final_asset.approval_status.value}, not approved.",
            )
        return ShortReadiness(True, "Final video asset is approved.")
