"""ApprovalRecord model — an audit trail entry for any approve/reject decision.

Deliberately polymorphic (``entity_type`` + ``entity_id``) rather than
one table per approvable thing, since the same approve/reject/needs-
changes decision shape applies to a :class:`~app.core.models.character.CharacterVersion`,
an :class:`~app.core.models.asset.Asset`, or anything approved in the
future — one small table beats a growing family of near-identical ones.
``entity_id`` is intentionally not a foreign key: it can point at rows
in different tables depending on ``entity_type``, which SQLite/SQLAlchemy
cannot express as a single FK constraint.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from app.core.db.enums import ApprovalDecision


class ApprovalRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One approve/reject/needs-changes decision on some other entity."""

    __tablename__ = "approval_records"
    __table_args__ = (
        Index("ix_approval_records_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, native_enum=False, length=32), nullable=False
    )
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<ApprovalRecord {self.entity_type}:{self.entity_id} {self.decision.value}>"
