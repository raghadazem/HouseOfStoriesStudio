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

Milestone 3.5 (``docs/18_AI_ARCHITECTURE_PLAN.md`` §10) extends this
service with :meth:`list_pending_review_assets` — the "review queue"
for AI-generated (and manually imported) draft assets. This is a
read-only query over the same ``Asset.approval_status`` concept this
service already owns, not a new domain concept or module.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ApprovalStatus
from app.core.models import (
    Asset,
    CharacterReference,
    CharacterVersion,
    Episode,
    PromptTemplate,
    Scene,
    Script,
    Short,
    VoiceProfile,
)
from app.core.models.approval import ApprovalRecord
from app.core.services.exceptions import NotFoundError, ValidationError

ENTITY_TYPE_MODELS: dict[str, type] = {
    "asset": Asset,
    "character_version": CharacterVersion,
    "character_reference": CharacterReference,
    "episode": Episode,
    "scene": Scene,
    "script": Script,
    "short": Short,
    "prompt_template": PromptTemplate,
    # Milestone 9: VoiceProfile has no approval_status column of its
    # own -- it reuses this same generic mechanism, exactly like every
    # other approvable entity here.
    "voice_profile": VoiceProfile,
}


class ApprovalService:
    """Records and reads approval decisions for any of the 8 supported entity types."""

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
            .order_by(ApprovalRecord.revision)
            .all()
        )

    def get_current_approval_state(
        self, session: Session, entity_type: str, entity_id: uuid.UUID
    ) -> ApprovalDecision | None:
        """The decision with the highest ``revision`` for this entity, or
        ``None`` if never reviewed.

        Ordered by ``revision``, not ``decided_at``: two decisions can be
        recorded close enough together to land on the same wall-clock
        timestamp (clock resolution/scheduling variance — not specific to
        any one platform), which made timestamp ordering non-deterministic.
        ``revision`` is a real, transactionally-assigned monotonic integer
        per ``(entity_type, entity_id)``, so this is always deterministic.
        """
        self._validate_entity_type(entity_type)
        latest = (
            session.query(ApprovalRecord)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(ApprovalRecord.revision.desc())
            .first()
        )
        return latest.decision if latest is not None else None

    def decide_asset_review(
        self,
        session: Session,
        asset_id: uuid.UUID,
        decision: ApprovalDecision,
        *,
        notes: str | None = None,
        decided_by: str | None = None,
    ) -> Asset:
        """Approve or reject a pending (``draft``) asset from the review queue.

        The entity-specific counterpart to
        :meth:`CharacterVersionService.approve_character_version` /
        :meth:`~CharacterVersionService.reject_character_version` — this
        service already owns :meth:`list_pending_review_assets` (the
        review queue), so it owns deciding on those assets too, rather
        than a new ``AssetService`` existing solely for this one
        transition. Moves ``Asset.approval_status`` (``draft`` ->
        ``approved``/``rejected``) *and* records the audit-trail
        ``ApprovalRecord`` via :meth:`approve_entity`/:meth:`reject_entity`
        in the same flush — never one without the other.

        Raises:
            NotFoundError: The asset doesn't exist.
            ValidationError: The asset isn't currently ``draft``, an
                unsupported ``decision`` was passed, or ``decision`` is
                ``rejected``/``needs_changes`` without ``notes``.
        """
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError(f"Asset {asset_id} not found.")
        if asset.approval_status != ApprovalStatus.DRAFT:
            raise ValidationError(
                f"Only a draft asset can be reviewed (current: {asset.approval_status.value})."
            )
        if decision == ApprovalDecision.APPROVED:
            asset.approval_status = ApprovalStatus.APPROVED
            self.approve_entity(session, "asset", asset_id, decided_by=decided_by, notes=notes)
        elif decision == ApprovalDecision.REJECTED:
            self._require_notes(notes, action="reject")
            asset.approval_status = ApprovalStatus.REJECTED
            self.reject_entity(session, "asset", asset_id, notes=notes, decided_by=decided_by)
        else:
            raise ValidationError(
                f"decide_asset_review only accepts approved/rejected, not {decision.value!r} "
                "(there is no 'needs changes' state for an asset — reject it and re-import)."
            )
        session.flush()
        return asset

    def list_pending_review_assets(
        self,
        session: Session,
        *,
        episode_id: uuid.UUID | None = None,
        character_version_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
        source_tool: str | None = None,
    ) -> list[Asset]:
        """The asset review queue: every asset still awaiting a decision.

        "Pending review" is simply ``Asset.approval_status == draft`` —
        no new concept, no new table, and no distinction between an
        asset a human imported and one an AI workflow generated (see
        ``docs/18_AI_ARCHITECTURE_PLAN.md`` §10). Filter by
        ``source_tool`` (e.g. ``"mock_provider"``) to see only
        AI-generated candidates. ``scene_id`` (Milestone 8) scopes the
        queue to one scene's own candidate-review grid.
        """
        query = session.query(Asset).filter_by(approval_status=ApprovalStatus.DRAFT)
        if episode_id is not None:
            query = query.filter_by(episode_id=episode_id)
        if character_version_id is not None:
            query = query.filter_by(character_version_id=character_version_id)
        if scene_id is not None:
            query = query.filter_by(scene_id=scene_id)
        if source_tool is not None:
            query = query.filter_by(source_tool=source_tool)
        return query.order_by(Asset.created_at).all()

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
            revision=self._next_revision(session, entity_type, entity_id),
        )
        session.add(record)
        session.flush()
        return record

    @staticmethod
    def _next_revision(session: Session, entity_type: str, entity_id: uuid.UUID) -> int:
        """The next revision number for this entity: 1 for its first
        decision, otherwise one past the highest revision recorded so far.

        Computed here and inserted in the same flush as the new row (see
        :meth:`_record`) — a plain query-then-insert, not a
        ``SELECT ... FOR UPDATE``-style lock, because this is a
        single-user desktop application with one writer at a time, not a
        multi-process/multi-user server. The
        ``uq_approval_records_entity_revision`` unique constraint on
        ``ApprovalRecord`` is the backstop: if this assumption were ever
        wrong, a real collision surfaces as a clear ``IntegrityError``
        instead of silently producing two "latest" decisions.
        """
        current_max = (
            session.query(func.max(ApprovalRecord.revision))
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .scalar()
        )
        return (current_max or 0) + 1

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
