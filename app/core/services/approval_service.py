"""ApprovalService — a generic, immutable approval audit trail.

Deliberately entity-status-agnostic: this service only ever creates and
reads :class:`~app.core.models.approval.ApprovalRecord` rows keyed by
``(entity_type, entity_id)``. It never mutates the target entity's own
state (e.g. it does not flip ``CharacterVersion.status`` or
``Asset.approval_status``) — entity-specific services
(``CharacterVersionService.approve_character_version``, etc.) call into
this service as a building block *and* perform their own domain
validation before/around it, so approval here can never bypass that
validation. See ``docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision
from app.core.models import (
    Asset,
    CharacterReference,
    CharacterVersion,
    Episode,
    PromptTemplate,
    Scene,
    Short,
)
from app.core.models.approval import ApprovalRecord
from app.core.services.exceptions import NotFoundError, ValidationError

ENTITY_TYPE_MODELS: dict[str, type] = {
    "asset": Asset,
    "character_version": CharacterVersion,
    "character_reference": CharacterReference,
    "episode": Episode,
    "scene": Scene,
    "short": Short,
    "prompt_template": PromptTemplate,
}


class ApprovalService:
    """Records and reads approval decisions for any of the 7 supported entity types."""

    def submit_for_review(
        self, session: Session, entity_type: str, entity_id: uuid.UUID
    ) -> ApprovalDecision | None:
        """Validate the entity exists and return its current approval state.

        Does not write an ``ApprovalRecord`` — "submitted" is not one of
        the recorded decisions (approved/rejected/needs_changes). Actual
        review-state transitions (e.g. a ``CharacterVersion`` moving
        ``draft -> in_review``) belong to that entity's own service;
        this is a validation checkpoint shared across entity types.
        """
        self._require_entity(session, entity_type, entity_id)
        return self.get_current_approval_state(session, entity_type, entity_id)

    def approve_entity(
        self,
        session: Session,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        decided_by: str | None = None,
        notes: str | None = None,
    ) -> ApprovalRecord:
        self._require_entity(session, entity_type, entity_id)
        return self._record(
            session,
            entity_type,
            entity_id,
            decision=ApprovalDecision.APPROVED,
            decided_by=decided_by,
            notes=notes,
        )

    def reject_entity(
        self,
        session: Session,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        notes: str,
        decided_by: str | None = None,
    ) -> ApprovalRecord:
        self._require_notes(notes, action="reject")
        self._require_entity(session, entity_type, entity_id)
        return self._record(
            session,
            entity_type,
            entity_id,
            decision=ApprovalDecision.REJECTED,
            decided_by=decided_by,
            notes=notes,
        )

    def request_changes(
        self,
        session: Session,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        notes: str,
        decided_by: str | None = None,
    ) -> ApprovalRecord:
        self._require_notes(notes, action="request changes on")
        self._require_entity(session, entity_type, entity_id)
        return self._record(
            session,
            entity_type,
            entity_id,
            decision=ApprovalDecision.NEEDS_CHANGES,
            decided_by=decided_by,
            notes=notes,
        )

    def list_approval_history(
        self, session: Session, entity_type: str, entity_id: uuid.UUID
    ) -> list[ApprovalRecord]:
        self._validate_entity_type(entity_type)
        return (
            session.query(ApprovalRecord)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(ApprovalRecord.decided_at)
            .all()
        )

    def get_current_approval_state(
        self, session: Session, entity_type: str, entity_id: uuid.UUID
    ) -> ApprovalDecision | None:
        """The most recent decision recorded for this entity, or ``None`` if never reviewed."""
        self._validate_entity_type(entity_type)
        latest = (
            session.query(ApprovalRecord)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(ApprovalRecord.decided_at.desc())
            .first()
        )
        return latest.decision if latest is not None else None

    def _record(
        self,
        session: Session,
        entity_type: str,
        entity_id: uuid.UUID,
        *,
        decision: ApprovalDecision,
        decided_by: str | None,
        notes: str | None,
    ) -> ApprovalRecord:
        # ApprovalRecord rows are never modified once written (see the
        # model docstring) — every call here is an INSERT, building an
        # append-only history, never an UPDATE of a prior row.
        record = ApprovalRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            decision=decision,
            decided_by=decided_by,
            notes=notes,
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def _validate_entity_type(entity_type: str) -> None:
        if entity_type not in ENTITY_TYPE_MODELS:
            raise ValidationError(
                f"Unsupported entity_type {entity_type!r}. "
                f"Expected one of: {sorted(ENTITY_TYPE_MODELS)}."
            )

    @staticmethod
    def _require_notes(notes: str | None, *, action: str) -> None:
        if not notes or not notes.strip():
            raise ValidationError(f"Notes are required to {action} an entity.")

    def _require_entity(self, session: Session, entity_type: str, entity_id: uuid.UUID) -> object:
        self._validate_entity_type(entity_type)
        model = ENTITY_TYPE_MODELS[entity_type]
        entity = session.get(model, entity_id)
        if entity is None:
            raise NotFoundError(f"{entity_type} {entity_id} not found.")
        return entity
