"""SceneService — an episode's ordered script/storyboard breakdown.

Scene ordering is kept contiguous (1..N, no gaps or duplicates) at all
times — insertion, deletion, and explicit reordering all renormalize
``order_index`` as part of the same operation, so callers never have to
manage sequence numbers themselves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus
from app.core.models import Asset, Character, Episode, Scene
from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError

_UPDATABLE_FIELDS = {
    "location",
    "description",
    "dialogue_ar",
    "estimated_duration_seconds",
}


@dataclass(frozen=True)
class SceneSequenceValidation:
    """Result of :meth:`SceneService.validate_scene_sequence`."""

    is_valid: bool
    issues: list[str] = field(default_factory=list)


class SceneService:
    """CRUD, ordering, and validation for an episode's scenes."""

    def add_scene(
        self,
        session: Session,
        episode_id: uuid.UUID,
        *,
        order_index: int | None = None,
        location: str | None = None,
        description: str | None = None,
        dialogue_ar: str | None = None,
        estimated_duration_seconds: int | None = None,
        character_ids: list[uuid.UUID] | None = None,
    ) -> Scene:
        """Insert a scene. Appends at the end if ``order_index`` is omitted.

        If ``order_index`` is given and falls within the existing range,
        every scene at or after that position is shifted down by one to
        make room, keeping the sequence contiguous.
        """
        if session.get(Episode, episode_id) is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        scenes = self.list_episode_scenes(session, episode_id)
        count = len(scenes)
        if order_index is None:
            order_index = count + 1
        elif not (1 <= order_index <= count + 1):
            raise ValidationError(
                f"order_index must be between 1 and {count + 1} (inclusive), got {order_index}."
            )
        else:
            self._shift_up(session, scenes, from_index=order_index)

        scene = Scene(
            episode_id=episode_id,
            order_index=order_index,
            location=location,
            description=description,
            dialogue_ar=dialogue_ar,
            estimated_duration_seconds=estimated_duration_seconds,
        )
        if character_ids:
            scene.characters_present = self._load_characters(session, character_ids)
        session.add(scene)
        session.flush()
        return scene

    @staticmethod
    def _shift_up(session: Session, scenes: list[Scene], *, from_index: int) -> None:
        """Move every scene at/after ``from_index`` up by one, avoiding transient collisions."""
        affected = [s for s in scenes if s.order_index >= from_index]
        for scene in affected:
            scene.order_index = -scene.order_index  # temp, avoids the unique constraint
        session.flush()
        for scene in affected:
            scene.order_index = -scene.order_index + 1
        session.flush()

    def get_scene(self, session: Session, scene_id: uuid.UUID) -> Scene:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise NotFoundError(f"Scene {scene_id} not found.")
        return scene

    def update_scene(self, session: Session, scene_id: uuid.UUID, **fields: object) -> Scene:
        """Edit scene content. Use :meth:`reorder_scenes` to change ``order_index``."""
        scene = self.get_scene(session, scene_id)
        if "order_index" in fields:
            raise ValidationError("Use reorder_scenes() to change order_index, not update_scene().")
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Scene fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(scene, key, value)
        session.flush()
        return scene

    def delete_scene(self, session: Session, scene_id: uuid.UUID, *, force: bool = False) -> None:
        """Delete a scene and renormalize the remaining sequence.

        Raises:
            ConflictError: If the scene has an approved "final_*" asset
                linked, or is used as a source scene by any Short, and
                ``force`` is not set.
        """
        scene = self.get_scene(session, scene_id)

        if not force:
            reasons: list[str] = []
            has_final_asset = (
                session.query(Asset)
                .filter(
                    Asset.scene_id == scene_id,
                    Asset.approval_status == ApprovalStatus.APPROVED,
                    Asset.role.isnot(None),
                    Asset.role.like("final_%"),
                )
                .count()
                > 0
            )
            if has_final_asset:
                reasons.append("an approved final asset is linked to this scene")
            if scene.source_for_shorts:
                reasons.append(
                    f"this scene is a source scene for {len(scene.source_for_shorts)} Short(s)"
                )
            if reasons:
                raise ConflictError(
                    f"Refusing to delete Scene {scene_id}: {'; '.join(reasons)}. "
                    "Pass force=True to override."
                )

        episode_id = scene.episode_id
        removed_index = scene.order_index
        session.delete(scene)
        session.flush()

        # Two-phase update (negative, then final) — SQLAlchemy does not
        # guarantee flush order matches this loop's iteration order, so
        # updating straight to the final values risks a transient
        # unique-constraint collision if a higher-indexed row's UPDATE
        # happens to be issued before a lower-indexed one vacates its slot.
        later_scenes = [
            s for s in self.list_episode_scenes(session, episode_id) if s.order_index > removed_index
        ]
        for later_scene in later_scenes:
            later_scene.order_index = -later_scene.order_index
        session.flush()
        for later_scene in later_scenes:
            later_scene.order_index = -later_scene.order_index - 1
        session.flush()

    def reorder_scenes(
        self, session: Session, episode_id: uuid.UUID, ordered_scene_ids: list[uuid.UUID]
    ) -> list[Scene]:
        """Reassign ``order_index`` 1..N to match ``ordered_scene_ids`` exactly."""
        scenes = self.list_episode_scenes(session, episode_id)
        current_ids = {s.id for s in scenes}
        given_ids = set(ordered_scene_ids)
        if current_ids != given_ids:
            raise ValidationError(
                "reorder_scenes requires exactly the episode's current scene ids "
                f"(missing: {current_ids - given_ids}, unexpected: {given_ids - current_ids})."
            )

        by_id = {s.id: s for s in scenes}
        for scene in scenes:
            scene.order_index = -scene.order_index  # avoid transient unique collisions
        session.flush()
        for position, scene_id in enumerate(ordered_scene_ids, start=1):
            by_id[scene_id].order_index = position
        session.flush()
        return self.list_episode_scenes(session, episode_id)

    def duplicate_scene(self, session: Session, scene_id: uuid.UUID) -> Scene:
        """Copy a scene's content into a new scene inserted immediately after it."""
        source = self.get_scene(session, scene_id)
        return self.add_scene(
            session,
            source.episode_id,
            order_index=source.order_index + 1,
            location=source.location,
            description=source.description,
            dialogue_ar=source.dialogue_ar,
            estimated_duration_seconds=source.estimated_duration_seconds,
            character_ids=[c.id for c in source.characters_present],
        )

    def list_episode_scenes(self, session: Session, episode_id: uuid.UUID) -> list[Scene]:
        return (
            session.query(Scene)
            .filter_by(episode_id=episode_id)
            .order_by(Scene.order_index)
            .all()
        )

    def calculate_total_scene_duration(self, session: Session, episode_id: uuid.UUID) -> int:
        """Sum of every scene's ``estimated_duration_seconds`` (treating missing as 0)."""
        scenes = self.list_episode_scenes(session, episode_id)
        return sum(scene.estimated_duration_seconds or 0 for scene in scenes)

    def validate_scene_sequence(
        self, session: Session, episode_id: uuid.UUID
    ) -> SceneSequenceValidation:
        scenes = self.list_episode_scenes(session, episode_id)
        issues: list[str] = []
        expected = list(range(1, len(scenes) + 1))
        actual = [s.order_index for s in scenes]
        if actual != expected:
            issues.append(f"order_index sequence is {actual}, expected {expected}.")
        return SceneSequenceValidation(is_valid=not issues, issues=issues)

    @staticmethod
    def _load_characters(session: Session, character_ids: list[uuid.UUID]) -> list[Character]:
        characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
        found_ids = {c.id for c in characters}
        missing = set(character_ids) - found_ids
        if missing:
            raise NotFoundError(f"Character(s) not found: {sorted(missing)}")
        return characters
