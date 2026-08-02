"""PromptTemplate model.

Covers both reusable fragments (character-lock / style-lock blocks,
``is_reusable=True``) and one-off, scene-specific prompts, per
``docs/07_DEVELOPMENT_PLAN.md`` §17. Prompts are stored in English
(``text_en``) even though the story content they illustrate is Arabic,
since external generators perform best with English prompts.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import PromptCategory, PromptType

if TYPE_CHECKING:
    from app.core.models.character import Character
    from app.core.models.episode import Episode, Scene


class PromptTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, versioned prompt for an image/video/voice/music/text generator.

    May be fully global (no character/episode/scene link at all) — a
    reusable style-lock or category-level block usable anywhere — or
    scoped to a specific character/episode/scene for one-off prompts.
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_name_version"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="v01", nullable=False)
    category: Mapped[PromptCategory] = mapped_column(
        Enum(PromptCategory, native_enum=False, length=32),
        nullable=False,
        server_default=PromptCategory.STORY.name,
    )
    prompt_type: Mapped[PromptType] = mapped_column(
        Enum(PromptType, native_enum=False, length=32), nullable=False
    )
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    is_reusable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    target_tool: Mapped[str | None] = mapped_column(String(128), nullable=True)

    character_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True
    )

    character: Mapped[Character | None] = relationship()
    episode: Mapped[Episode | None] = relationship()
    scene: Mapped[Scene | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<PromptTemplate {self.name!r} {self.version}>"
