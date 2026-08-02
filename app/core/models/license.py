"""LicenseRecord model — detailed licensing/commercial-use documentation for an asset.

``Asset`` itself carries quick-glance ``license_status`` /
``commercial_use_status`` fields for at-a-glance display; a
``LicenseRecord`` holds the fuller documentation (source URL, terms,
verification) an asset's rights claim should be backed by before it's
relied on for a monetized upload.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.models._path_validation import validate_relative_path

if TYPE_CHECKING:
    from app.core.models.asset import Asset


class LicenseRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One licensing/commercial-use documentation entry for an asset."""

    __tablename__ = "license_records"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    license_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    terms_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    commercial_use_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Proof of license (a screenshot of terms, a purchase receipt, etc.)
    # is itself an imported file — like every other asset, only a
    # managed-storage-relative path is ever stored here, never a blob.
    proof_relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attribution_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset: Mapped[Asset] = relationship()

    @validates("proof_relative_path")
    def validate_proof_relative_path(self, key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_relative_path("LicenseRecord.proof_relative_path", value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<LicenseRecord asset={self.asset_id} {self.license_type!r}>"
