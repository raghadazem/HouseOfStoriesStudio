"""Character, CharacterVersion, and CharacterReference models.

Together these implement the approved Character Lock workflow
(``docs/07_DEVELOPMENT_PLAN.md`` §13): a character has a stable
identity (:class:`Character`), a history of design revisions each with
its own approval state (:class:`CharacterVersion`), and links to the
actual approved artwork files that make up the current canon reference
set (:class:`CharacterReference`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import CharacterVersionStatus

if TYPE_CHECKING:
    from app.core.models.asset import Asset


class Character(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A main character (e.g. Melissa, Bilsan).

    Holds the stable identity fields from the Character Bible. Visual
    design details that can change over time (outfit, palette, prompt
    blocks) live on :class:`CharacterVersion`, not here, so the design
    can evolve without losing history.
    """

    __tablename__ = "characters"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str] = mapped_column(String(128), nullable=False)
    age: Mapped[int | None] = mapped_column(nullable=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    traits: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    versions: Mapped[list[CharacterVersion]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        order_by="CharacterVersion.version_number",
    )
    references: Mapped[list[CharacterReference]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Character {self.slug!r}>"


class CharacterVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single approved-or-candidate design revision of a character.

    This is the Character Lock record: visual specification, master and
    negative prompt blocks, palette, accessories, and approval status
    all live here, versioned, so an episode produced against ``v01`` can
    always be traced back to exactly what "on-model" meant at the time —
    even after the design moves on to ``v02``.
    """

    __tablename__ = "character_versions"
    __table_args__ = (
        UniqueConstraint(
            "character_id", "version_number", name="uq_character_version_number"
        ),
    )

    character_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[str] = mapped_column(String(16), nullable=False)  # e.g. "v01"
    outfit_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    description_of_change: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    color_palette: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_accessories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    relative_height: Mapped[str | None] = mapped_column(String(64), nullable=True)

    master_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[CharacterVersionStatus] = mapped_column(
        Enum(CharacterVersionStatus, native_enum=False, length=32),
        default=CharacterVersionStatus.DRAFT,
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    character: Mapped[Character] = relationship(back_populates="versions")
    references: Mapped[list[CharacterReference]] = relationship(
        back_populates="character_version"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<CharacterVersion {self.character_id} {self.version_number!r} {self.status.value}>"


class CharacterReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Links one approved artwork :class:`Asset` to a character (and version).

    A thin join, not a duplicate store of file metadata — the asset row
    itself (path, checksum, license, approval status) is the single
    source of truth for the file; this table just marks *which*
    character/version that file is canon reference art for, and under
    what label (front view, outfit close-up, expression sheet, ...).
    """

    __tablename__ = "character_references"

    character_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    character_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("character_versions.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_current_canon: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    character: Mapped[Character] = relationship(back_populates="references")
    character_version: Mapped[CharacterVersion | None] = relationship(
        back_populates="references"
    )
    asset: Mapped[Asset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<CharacterReference {self.character_id} label={self.label!r}>"
