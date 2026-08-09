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
    JSON,
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
from app.core.db.enums import PipelineStage, ScriptStatus, ShortStatus

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

# Which Scenes a Short was cut from. A Short's source scenes must all
# belong to the same Episode the Short itself belongs to — enforced in
# ShortService, not at the schema level (SQLite can't express a
# cross-table "same parent" constraint declaratively).
short_scenes = Table(
    "short_scenes",
    Base.metadata,
    Column("short_id", ForeignKey("shorts.id", ondelete="CASCADE"), primary_key=True),
    Column("scene_id", ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
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

    # Export/SEO metadata. Kept as structured columns (rather than only
    # existing in the hand-edited 07_seo.md file) so ExportPackageService
    # can generate export files deterministically without parsing
    # Markdown.
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    credits_text: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    script: Mapped[Script | None] = relationship(
        back_populates="episode", cascade="all, delete-orphan", uselist=False
    )
    song: Mapped[Song | None] = relationship(
        back_populates="episode", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Episode #{self.number} {self.slug!r}>"


class Script(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The Episode Workspace's Script stage — one per Episode.

    Deliberately does not duplicate ``Episode.title_ar``/``title_en``/
    ``lesson``/``dialogue_language``: those already exist on ``Episode``
    and the Script tab reads/writes them there via
    ``EpisodeService.update_episode``. ``status`` follows the same
    draft/reviewed split as ``CharacterVersionStatus``: DRAFT->READY is
    a plain self-transition, READY->APPROVED (or back to DRAFT) is
    recorded via :class:`~app.core.models.approval.ApprovalRecord` — see
    ``ScriptService``.
    """

    __tablename__ = "scripts"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ScriptStatus] = mapped_column(
        Enum(ScriptStatus, native_enum=False, length=32),
        default=ScriptStatus.DRAFT,
        nullable=False,
    )

    episode: Mapped[Episode] = relationship(back_populates="script")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Script episode={self.episode_id} status={self.status.value}>"


class Song(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The Episode Workspace's Music stage's written song package — one per Episode.

    Deliberately minimal and un-versioned (unlike ``Script``/``CharacterVersion``):
    nothing in this milestone reviews or approves lyrics, so there is no
    status lifecycle here. This is *planning content* — lyrics, purpose,
    and a Suno-ready style prompt for a human (or an external tool) to
    actually produce the audio from; no AI provider is ever called with
    this data. The Music tab's existing ``Asset``/``AssetImportService``
    flow is still how the final produced audio file itself gets in.
    """

    __tablename__ = "songs"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    lyrics_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    production_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    suno_style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="song")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Song episode={self.episode_id}>"


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
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Prompt Composer output (PromptComposerService.compose_scene_prompt) —
    # stored so it survives without regenerating, and freely hand-editable
    # afterward via SceneService.update_scene. Never sent to an AI
    # provider by anything in this milestone.
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Voice-direction guidance for this scene's dialogue: emotional tone,
    # pacing, and pronunciation notes together as one short paragraph —
    # not split into separate columns, since these are normally authored
    # together as a single piece of direction for whoever performs the
    # lines. The lines themselves stay in ``dialogue_ar`` (already a full
    # narration+dialogue script per Milestone 5's SceneCard labeling).
    voice_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Founder-estimated (not auto-derived) length of this scene, used by
    # SceneService.calculate_total_scene_duration. Nullable: most scenes
    # won't have a duration estimate until later in production.
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="scenes")
    characters_present: Mapped[list[Character]] = relationship(secondary=scene_characters)
    source_for_shorts: Mapped[list[Short]] = relationship(
        secondary=short_scenes, back_populates="source_scenes"
    )
    assets: Mapped[list[Asset]] = relationship(back_populates="scene")

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
    short_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3, ...
    title_ar: Mapped[str | None] = mapped_column(String(256), nullable=True)  # working title (Arabic)
    working_title_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hook_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_timestamp_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Milestone 6 additions — the Short's own edit script, distinct from
    # its source Scenes' full dialogue: what's actually spoken/on-screen
    # in the cut-down clip, its own target length, and free-text notes
    # for whoever edits it together.
    spoken_text_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    on_screen_text_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ShortStatus] = mapped_column(
        Enum(ShortStatus, native_enum=False, length=32),
        default=ShortStatus.PLANNED,
        nullable=False,
    )
    export_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    episode: Mapped[Episode] = relationship(back_populates="shorts")
    export_asset: Mapped[Asset | None] = relationship(foreign_keys=[export_asset_id])
    source_scenes: Mapped[list[Scene]] = relationship(
        secondary=short_scenes, back_populates="source_for_shorts", order_by="Scene.order_index"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Short episode={self.episode_id} #{self.short_index}>"
