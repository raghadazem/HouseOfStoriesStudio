"""GenerationJob model — persistent provenance for one AI generation attempt.

Real, asynchronous, paid/failable generation needs a queryable record of
what was attempted and what happened, independent of the (already
existing) supplemental ``generation_logger`` log file — this table is
the application-level source of truth for a generation attempt's
lifecycle and provenance; the log file remains operational/debugging
data only.

Every field that could change after the fact on the row it references
(a ``PromptTemplate``'s text, a ``CharacterVersion``'s prompt fields) is
snapshotted here instead of re-derived later: ``prompt_text``,
``negative_prompt_text``, and ``parameters`` are exactly what was sent
to the provider, immutable from the moment the job is created, even if
the template or character version is edited afterward. Reference
images are **not** duplicated as binary data — ``reference_asset_ids``
stores the identifiers of the already-immutable, checksum-verified
``Asset`` rows that were used, which is sufficient provenance without a
second copy of the bytes.

Status transitions are owned exclusively by
:class:`~app.core.ai.generation_job_service.GenerationJobService` — see
that module's docstring for the full lifecycle/cancellation semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from app.core.db.enums import GenerationJobStatus

if TYPE_CHECKING:
    from app.core.models.asset import Asset


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One attempt (successful, failed, or cancelled) to generate one asset."""

    __tablename__ = "generation_jobs"

    workflow_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # The specific model identifier used (e.g. "gemini-3.1-flash-image").
    # Nullable because not every provider has a model concept (MockProvider).
    provider_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[GenerationJobStatus] = mapped_column(
        Enum(GenerationJobStatus, native_enum=False, length=32),
        default=GenerationJobStatus.PENDING,
        nullable=False,
    )

    # Groups every GenerationJob produced by one logical human request
    # (e.g. "generate 4 candidates") — one row per provider call, since
    # not every provider supports native multi-candidate generation.
    # Not a foreign key: a batch is a grouping concept, not an entity
    # with its own row.
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    # Immutable provenance snapshot — see module docstring.
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # List of Asset.id (as strings) used as reference images for this
    # request — identifiers only, never a second copy of the bytes.
    reference_asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    character_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    character_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("character_versions.id", ondelete="SET NULL"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True
    )
    short_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shorts.id", ondelete="SET NULL"), nullable=True
    )
    # Milestone 9: which stable DialogueLine this voice-generation
    # attempt was for, if any. A real FK (not a JSON-embedded key) —
    # unlike most per-attempt provenance in ``parameters``, "is a job
    # already in flight for this exact line" is a real, frequent,
    # indexed query, not occasional inspection. SET NULL, matching
    # every other "which structural thing" FK here: a job's history
    # must survive even if the DialogueLine it targeted is later
    # superseded by a dialogue_ar edit.
    dialogue_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dialogue_lines.id", ondelete="SET NULL"), nullable=True, index=True
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set together on failure/cancellation. error_category is the raising
    # exception's class name (matching the convention already used by
    # app.core.ai.generation_logger), never a raw provider payload.
    error_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    result_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    retry_of_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
    )

    # Only ever set from an authoritative provider-reported figure.
    # NULL, never an estimate — see GenerationJobService.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    result_asset: Mapped[Asset | None] = relationship(foreign_keys=[result_asset_id])
    retry_of: Mapped[GenerationJob | None] = relationship(
        "GenerationJob", remote_side="GenerationJob.id", foreign_keys=[retry_of_job_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<GenerationJob {self.workflow_name} {self.status.value}>"
