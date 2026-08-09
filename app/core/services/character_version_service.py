"""CharacterVersionService — the Character Lock workflow.

Each :class:`~app.core.models.character.CharacterVersion` is one design
revision; this service manages its lifecycle (draft -> in_review ->
approved_canon), the reference artwork linked to it, which version is
the character's single active one, and the completeness check the
founder's approved Character Lock fields require.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType, CharacterVersionStatus
from app.core.models import Asset, Character, CharacterReference, CharacterVersion
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import (
    CharacterLockIncompleteError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)

_UPDATABLE_FIELDS = {
    "outfit_version",
    "description_of_change",
    "visual_summary",
    "color_palette",
    "allowed_accessories",
    "relative_height",
    "master_prompt",
    "negative_prompt",
}

_REQUIRED_LOCK_FIELDS = (
    "visual_summary",
    "master_prompt",
    "negative_prompt",
    "color_palette",
    "relative_height",
)


@dataclass(frozen=True)
class PromptCompletenessResult:
    """Result of :meth:`CharacterVersionService.validate_prompt_completeness`.

    A narrower check than :class:`CharacterLockValidationResult`: only
    the fields that feed a generation prompt, not the approved-reference
    requirement. Deliberately reused as a component of the full
    Character Lock check rather than a duplicate rule set — see that
    method's docstring for why the two must stay separate.
    """

    character_version_id: uuid.UUID
    is_complete: bool
    missing_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterLockValidationResult:
    """Result of :meth:`CharacterVersionService.validate_character_lock`."""

    character_version_id: uuid.UUID
    is_complete: bool
    missing_fields: list[str] = field(default_factory=list)


class CharacterVersionService:
    """Manages Character Lock records: their lifecycle, references, and validation."""

    def __init__(self, approval_service: ApprovalService | None = None) -> None:
        self._approvals = approval_service or ApprovalService()

    def create_character_version(
        self,
        session: Session,
        character_id: uuid.UUID,
        *,
        version_number: str | None = None,
        outfit_version: str | None = None,
        description_of_change: str | None = None,
        visual_summary: str | None = None,
        color_palette: list[str] | None = None,
        allowed_accessories: list[str] | None = None,
        relative_height: str | None = None,
        master_prompt: str | None = None,
        negative_prompt: str | None = None,
    ) -> CharacterVersion:
        character = session.get(Character, character_id)
        if character is None:
            raise NotFoundError(f"Character {character_id} not found.")

        if version_number is None:
            version_number = self._next_version_number(session, character_id)
        elif (
            session.query(CharacterVersion)
            .filter_by(character_id=character_id, version_number=version_number)
            .count()
            > 0
        ):
            raise ConflictError(
                f"Character {character.slug!r} already has version {version_number!r}."
            )

        version = CharacterVersion(
            character_id=character_id,
            version_number=version_number,
            status=CharacterVersionStatus.DRAFT,
            outfit_version=outfit_version,
            description_of_change=description_of_change,
            visual_summary=visual_summary,
            color_palette=list(color_palette or []),
            allowed_accessories=list(allowed_accessories or []),
            relative_height=relative_height,
            master_prompt=master_prompt,
            negative_prompt=negative_prompt,
        )
        session.add(version)
        session.flush()
        return version

    @staticmethod
    def _next_version_number(session: Session, character_id: uuid.UUID) -> str:
        count = session.query(CharacterVersion).filter_by(character_id=character_id).count()
        return f"v{count + 1:02d}"

    def update_character_version(
        self, session: Session, version_id: uuid.UUID, **fields: object
    ) -> CharacterVersion:
        """Edit a version's design fields.

        Raises:
            InvalidTransitionError: If the version is ``approved_canon``
                or ``archived`` — history is never overwritten in place;
                create a new version instead.
        """
        version = self._get(session, version_id)
        if version.status in (CharacterVersionStatus.APPROVED_CANON, CharacterVersionStatus.ARCHIVED):
            raise InvalidTransitionError(
                f"CharacterVersion {version_id} is {version.status.value}; "
                "create a new version instead of editing it."
            )
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(
                f"Cannot update unknown CharacterVersion fields: {sorted(unknown)}"
            )
        for key, value in fields.items():
            setattr(version, key, value)
        session.flush()
        return version

    def submit_character_version_for_review(
        self, session: Session, version_id: uuid.UUID
    ) -> CharacterVersion:
        version = self._get(session, version_id)
        if version.status != CharacterVersionStatus.DRAFT:
            raise InvalidTransitionError(
                f"Only a draft version can be submitted for review "
                f"(current: {version.status.value})."
            )
        version.status = CharacterVersionStatus.IN_REVIEW
        session.flush()
        return version

    def approve_character_version(
        self,
        session: Session,
        version_id: uuid.UUID,
        *,
        decided_by: str | None = None,
        notes: str | None = None,
    ) -> CharacterVersion:
        """Approve an in-review version, promoting it to ``approved_canon``.

        Raises:
            InvalidTransitionError: The version isn't ``in_review``.
            CharacterLockIncompleteError: The Character Lock isn't
                complete (see :meth:`validate_character_lock`) —
                production generation must never silently consume an
                unfinished design, so a version cannot become canon
                until its lock is whole.
        """
        version = self._get(session, version_id)
        if version.status != CharacterVersionStatus.IN_REVIEW:
            raise InvalidTransitionError(
                f"Only an in-review version can be approved (current: {version.status.value})."
            )
        lock_result = self.validate_character_lock(session, version_id)
        if not lock_result.is_complete:
            raise CharacterLockIncompleteError(
                f"CharacterVersion {version_id} cannot become approved_canon: "
                f"Character Lock is incomplete, missing {lock_result.missing_fields}.",
                missing_fields=lock_result.missing_fields,
            )
        version.status = CharacterVersionStatus.APPROVED_CANON
        version.decided_at = datetime.now(UTC)
        version.decided_by = decided_by
        if notes:
            version.review_notes = notes
        self._approvals.approve_entity(
            session, "character_version", version_id, decided_by=decided_by, notes=notes
        )
        session.flush()
        return version

    def reject_character_version(
        self,
        session: Session,
        version_id: uuid.UUID,
        *,
        notes: str,
        decided_by: str | None = None,
    ) -> CharacterVersion:
        """Reject an in-review version, sending it back to draft.

        There is no dedicated "rejected" status (see
        ``CharacterVersionStatus``) — rejection is recorded permanently
        in the approval history, while the version itself returns to
        ``draft`` for revision.
        """
        version = self._get(session, version_id)
        if version.status != CharacterVersionStatus.IN_REVIEW:
            raise InvalidTransitionError(
                f"Only an in-review version can be rejected (current: {version.status.value})."
            )
        version.status = CharacterVersionStatus.DRAFT
        version.decided_at = datetime.now(UTC)
        version.decided_by = decided_by
        version.review_notes = notes
        self._approvals.reject_entity(
            session, "character_version", version_id, decided_by=decided_by, notes=notes
        )
        session.flush()
        return version

    def set_active_character_version(
        self, session: Session, character_id: uuid.UUID, version_id: uuid.UUID
    ) -> Character:
        """Make ``version_id`` the character's single active version.

        The previously active version is left entirely untouched (still
        ``approved_canon``, still in ``character.versions`` history) —
        only the pointer moves. Both the pointer update and the read
        that validated it happen in this one flush, inside whatever
        transaction the caller's ``session_scope`` owns.

        Raises:
            NotFoundError: Character or version doesn't exist.
            ValidationError: The version doesn't belong to this character.
            InvalidTransitionError: The version isn't ``approved_canon``.

        Note: no separate Character Lock completeness check is needed
        here — ``approved_canon`` is itself only reachable through
        :meth:`approve_character_version`, which already requires a
        complete lock, so requiring that status transitively guarantees
        an active version's lock is complete too.
        """
        character = session.get(Character, character_id)
        if character is None:
            raise NotFoundError(f"Character {character_id} not found.")
        version = self._get(session, version_id)
        if version.character_id != character_id:
            raise ValidationError(
                f"CharacterVersion {version_id} does not belong to character {character_id}."
            )
        if version.status != CharacterVersionStatus.APPROVED_CANON:
            raise InvalidTransitionError(
                f"Only an approved_canon version may become active (current: {version.status.value})."
            )
        character.active_version_id = version.id
        session.flush()
        return character

    def add_character_reference(
        self,
        session: Session,
        *,
        character_id: uuid.UUID,
        asset_id: uuid.UUID,
        character_version_id: uuid.UUID | None = None,
        label: str | None = None,
        is_current_canon: bool = False,
    ) -> CharacterReference:
        """Link an approved artwork asset as reference art for a character.

        Raises:
            ValidationError: The asset isn't an image/video, isn't
                approved, or belongs to a different character's version.
            ConflictError: The asset is already linked as a reference.

        Note on personal photographs: this method has no way to
        classify an asset as a "personal photo" because no such
        classification exists (see ``AssetType`` — there is no
        personal-photo value) and because ``AssetImportService``
        already refuses to import from configured restricted
        directories. By the time an ``Asset`` row exists at all, it can
        only be an approved, original, non-personal file.
        """
        character = session.get(Character, character_id)
        if character is None:
            raise NotFoundError(f"Character {character_id} not found.")
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError(f"Asset {asset_id} not found.")
        if asset.asset_type not in (AssetType.IMAGE, AssetType.VIDEO):
            raise ValidationError(
                f"Character reference assets must be image or video, got {asset.asset_type.value}."
            )
        if asset.approval_status != ApprovalStatus.APPROVED:
            raise ValidationError(
                "Only an approved asset may become character reference artwork."
            )
        if character_version_id is not None:
            version = self._get(session, character_version_id)
            if version.character_id != character_id:
                raise ValidationError(
                    f"CharacterVersion {character_version_id} does not belong to "
                    f"character {character_id}."
                )
        if session.query(CharacterReference).filter_by(asset_id=asset_id).count() > 0:
            raise ConflictError(f"Asset {asset_id} is already a character reference.")

        reference = CharacterReference(
            character_id=character_id,
            character_version_id=character_version_id,
            asset_id=asset_id,
            label=label,
            is_current_canon=is_current_canon,
        )
        session.add(reference)
        session.flush()
        return reference

    def remove_character_reference(self, session: Session, reference_id: uuid.UUID) -> None:
        reference = session.get(CharacterReference, reference_id)
        if reference is None:
            raise NotFoundError(f"CharacterReference {reference_id} not found.")
        session.delete(reference)
        session.flush()

    def list_character_references(
        self,
        session: Session,
        character_id: uuid.UUID,
        *,
        version_id: uuid.UUID | None = None,
    ) -> list[CharacterReference]:
        query = session.query(CharacterReference).filter_by(character_id=character_id)
        if version_id is not None:
            query = query.filter_by(character_version_id=version_id)
        return query.all()

    def validate_prompt_completeness(
        self, session: Session, version_id: uuid.UUID
    ) -> PromptCompletenessResult:
        """Report every prompt-relevant field still missing on this version.

        This is the *single source of truth* for "does this version have
        enough authored design data to be worth spending a real,
        paid generation call on" — deliberately narrower than
        :meth:`validate_character_lock`, which additionally requires an
        already-approved reference asset. That requirement would make
        this specific check circular for the very workflow that
        produces a version's first reference image: you cannot require
        an approved reference to exist before generating the reference
        that would become one. See
        ``app.core.ai.workflows.character_reference_workflow`` for where
        this is enforced.
        """
        version = self._get(session, version_id)
        missing = [attr for attr in _REQUIRED_LOCK_FIELDS if not getattr(version, attr)]
        return PromptCompletenessResult(
            character_version_id=version_id,
            is_complete=not missing,
            missing_fields=missing,
        )

    def validate_character_lock(
        self, session: Session, version_id: uuid.UUID
    ) -> CharacterLockValidationResult:
        """Report every Character Lock field still missing on this version.

        Composes :meth:`validate_prompt_completeness` (the single source
        of truth for the prompt-relevant fields) with the one additional
        requirement full lock completeness needs: at least one approved
        reference asset already linked. Checks everything, not just the
        first failure, so the caller can show a complete checklist
        rather than one error at a time.
        """
        prompt_result = self.validate_prompt_completeness(session, version_id)
        missing = list(prompt_result.missing_fields)

        has_reference = (
            session.query(CharacterReference).filter_by(character_version_id=version_id).count()
            > 0
        )
        if not has_reference:
            missing.append("approved_reference_assets")

        return CharacterLockValidationResult(
            character_version_id=version_id,
            is_complete=not missing,
            missing_fields=missing,
        )

    def _get(self, session: Session, version_id: uuid.UUID) -> CharacterVersion:
        version = session.get(CharacterVersion, version_id)
        if version is None:
            raise NotFoundError(f"CharacterVersion {version_id} not found.")
        return version
