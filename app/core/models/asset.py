"""Asset model — metadata for one imported file.

Per the founder's approved rules, the database never stores binary
media itself: only ``relative_path`` (relative to
``AppConfig.production_dir``), a checksum for duplicate detection, and
the provenance/licensing/approval metadata every imported asset must
carry.
"""

from __future__ import annotations

import re
import uuid
from pathlib import PurePath
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import ApprovalStatus, AssetType

if TYPE_CHECKING:
    from app.core.models.character import CharacterVersion
    from app.core.models.episode import Episode
    from app.core.models.prompt import PromptTemplate

_WINDOWS_ABS_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")


def _looks_absolute(value: str) -> bool:
    """Detect an absolute path under POSIX *or* Windows conventions.

    Uses simple prefix checks (rather than relying solely on
    ``pathlib.PurePath.is_absolute()``) because the app must run on
    Windows, but its tests may run on Linux/macOS, where
    ``PurePath("C:\\\\foo").is_absolute()`` is ``False``.
    """
    if value.startswith(("/", "\\")):
        return True
    if _WINDOWS_ABS_RE.match(value):
        return True
    return PurePath(value).is_absolute()


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata for one imported media/document file.

    ``relative_path`` and ``checksum`` are both unique: the former
    because two assets can't occupy the same file location, the latter
    as a database-level guard against importing the same bytes twice
    under different names (the founder's "duplicate detection" rule
    from the Development Plan, enforced here rather than left to
    optimistic manual discipline).
    """

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("relative_path", name="uq_asset_relative_path"),
        UniqueConstraint("checksum", name="uq_asset_checksum"),
    )

    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, native_enum=False, length=32), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex digest

    source_tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    license_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commercial_use_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    prompt_used_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    character_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("character_versions.id", ondelete="SET NULL"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True
    )

    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, native_enum=False, length=32),
        default=ApprovalStatus.DRAFT,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt_used: Mapped[PromptTemplate | None] = relationship(
        foreign_keys=[prompt_used_id]
    )
    character_version: Mapped[CharacterVersion | None] = relationship()
    episode: Mapped[Episode | None] = relationship()

    @validates("relative_path")
    def validate_relative_path(self, key: str, value: str) -> str:
        """Reject absolute paths and ``..`` traversal; normalize separators.

        Assets are always addressed relative to
        ``AppConfig.production_dir`` so the repository stays portable
        between machines (and between the founder's Windows PC and any
        other environment) — an absolute path baked into the database
        would silently break the moment the project folder moved.
        """
        if not value or not value.strip():
            raise ValueError("Asset.relative_path must not be empty.")
        if _looks_absolute(value):
            raise ValueError(
                f"Asset.relative_path must be relative to production_dir, "
                f"got an absolute path: {value!r}"
            )
        normalized = value.replace("\\", "/")
        if ".." in PurePath(normalized).parts:
            raise ValueError(
                f"Asset.relative_path must not contain '..' path traversal: {value!r}"
            )
        return normalized

    @validates("checksum")
    def validate_checksum(self, key: str, value: str) -> str:
        """Require a lowercase 64-character sha256 hex digest."""
        if not value:
            raise ValueError("Asset.checksum must not be empty.")
        normalized = value.lower()
        if not _CHECKSUM_RE.match(normalized):
            raise ValueError(
                f"Asset.checksum must be a 64-character sha256 hex digest, "
                f"got: {value!r}"
            )
        return normalized

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<Asset {self.asset_type.value} {self.relative_path!r}>"
