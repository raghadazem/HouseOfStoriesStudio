"""ProductionTask model — a single checklist item within an episode's production."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import ProductionTaskStatus

if TYPE_CHECKING:
    from app.core.models.episode import Episode


class ProductionTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One actionable checklist item tied to an episode's production.

    Deliberately free-form (``task_type`` is a plain string, not an
    enum) since the set of possible tasks is open-ended and defined by
    the founder's own workflow, not fixed by the schema.
    """

    __tablename__ = "production_tasks"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProductionTaskStatus] = mapped_column(
        Enum(ProductionTaskStatus, native_enum=False, length=32),
        default=ProductionTaskStatus.PENDING,
        nullable=False,
    )

    episode: Mapped[Episode] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<ProductionTask {self.task_type!r} {self.status.value}>"
