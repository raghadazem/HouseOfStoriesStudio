"""Episode, Scene, and Short models.

An :class:`Episode` is the long-form (8-10 minute) video; it owns an
ordered list of :class:`Scene` rows (the working script/storyboard
breakdown) and exactly the three :class:`Short` records the approved
production spec calls for. ``characters_featured``/``characters_present``
are many-to-many links to :class:`~app.core.models.character.Character`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import PipelineStage, ShortStatus

if TYPE_CHECKING:
    from app.core.models.asset import Asset
    from app.core.models.character import Character

episode_characters = Table(
    "episode_characters",
    Base.metadata,
    Column("episode_id", ForeignKey("episodes.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)

scene_characters = Table(
    "scene_characters",
    Base.metadata,
    Column("scene_id", ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)


class Episode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One long-form episode and its position in the production pipeline."""

    __tablename__ = "episodes"

    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    season: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    title_ar: Mapped[str] = mapped_column(String(256), nullable=False)
    title_en: Mapped[str] = mapped_column(String(256), nullable=False)
    lesson: Mapped[str] = mapped_column(String(256), nullable=False)
    logline_ar: Mapped[str | None] = mapped_column(Text, nullable=True)

    dialogue_language: Mapped[str] = mapped_column(
        String(64), default="simple_white_arabic", nullable=False
    )
    runtime_target_minutes_min: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    runtime_target_minutes_max: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    includes_song: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    pipeline_stage: Mapped[PipelineStage] = mapped_column(
        Enum(PipelineStage, native_enum=False, length=32),
        default=PipelineStage.IDEA,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    scenes: Mapped[list[Scene]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        order_by="Scene.order_index",
    )
    shorts: Mapped[list[Short]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        order_by="Short.short_index",
    )
    characters_featured: Mapped[list[Character]] = relationship(secondary=episode_characters)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Episode #{self.number} {self.slug!r}>"


class Scene(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One scene within an episode's script/storyboard breakdown."""

    __tablename__ = "scenes"
    __table_args__ = (
        UniqueConstraint("episode_id", "order_index", name="uq_scene_order_per_episode"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue_ar: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="scenes")
    characters_present: Mapped[list[Character]] = relationship(secondary=scene_characters)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Scene episode={self.episode_id} #{self.order_index}>"


class Short(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the three YouTube Shorts cut from a long episode."""

    __tablename__ = "shorts"
    __table_args__ = (
        UniqueConstraint("episode_id", "short_index", name="uq_short_index_per_episode"),
    )

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    short_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, or 3
    title_ar: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_timestamp_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ShortStatus] = mapped_column(
        Enum(ShortStatus, native_enum=False, length=32),
        default=ShortStatus.PLANNED,
        nullable=False,
    )
    export_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    episode: Mapped[Episode] = relationship(back_populates="shorts")
    export_asset: Mapped[Asset | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Short episode={self.episode_id} #{self.short_index}>"
