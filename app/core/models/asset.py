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
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models._path_validation import validate_relative_path

if TYPE_CHECKING:
    from app.core.models.character import CharacterVersion
    from app.core.models.episode import Episode, Scene, Short
    from app.core.models.generation_job import GenerationJob
    from app.core.models.prompt import PromptTemplate

_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")

# Free-text convention, not an enum: marks which asset is THE current
# deliverable of its kind for an episode/short, e.g. "final_video",
# "final_thumbnail", "final_voice", "final_music". Anything without a
# "final_" role is a draft/candidate/work-in-progress asset. Kept a
# plain string (not an enum) since new roles may be needed without a
# schema change, and only ProductionChecklistService/ExportPackageService
# interpret the convention.
ROLE_FINAL_VIDEO = "final_video"
ROLE_FINAL_THUMBNAIL = "final_thumbnail"
ROLE_FINAL_VOICE = "final_voice"
ROLE_FINAL_MUSIC = "final_music"
# Reserved (Milestone 8): identifies the one Asset that is a Scene's
# current approved key image (Asset.scene_id + this role, no dedicated
# table — see docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md).
# Unlike the four roles above, this one may ONLY ever be assigned via
# SceneService.set_scene_key_image — never through a generic/manual
# import — because that method is what guarantees at most one Asset
# holds it per scene (unsetting the previous holder in the same
# transaction). AssetImportService enforces this at the boundary; see
# ImportRequest.role validation.
ROLE_FINAL_SCENE_IMAGE = "final_scene_image"


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

    # Which "slot" this asset fills, e.g. "final_video" — see the
    # ROLE_* constants above. Nullable: most imported candidates/drafts
    # have no special role at all.
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)

    prompt_used_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
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
    # The GenerationJob that produced this asset, if any. NULL for every
    # manually imported asset and for every asset imported before
    # Milestone 7 — existing/manual imports remain valid with no change.
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
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
    scene: Mapped[Scene | None] = relationship(back_populates="assets")
    short: Mapped[Short | None] = relationship(foreign_keys=[short_id])
    generation_job: Mapped[GenerationJob | None] = relationship(
        foreign_keys=[generation_job_id]
    )

    @validates("relative_path")
    def validate_relative_path(self, key: str, value: str) -> str:
        """Reject absolute paths and ``..`` traversal; normalize separators.

        Assets are always addressed relative to
        ``AppConfig.production_dir`` so the repository stays portable
        between machines (and between the founder's Windows PC and any
        other environment) — an absolute path baked into the database
        would silently break the moment the project folder moved.
        """
        return validate_relative_path("Asset.relative_path", value)

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
