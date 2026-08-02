"""LicenseService — license/commercial-use documentation and readiness.

Per the founder's approved decision, multiple :class:`~app.core.models.license.LicenseRecord`
rows per asset are valid and expected — they form an append-only
history, not one mutable record. ``verify_license``/``invalidate_license``
still mutate a *specific existing* record (marking it verified, or
appending an invalidation note) rather than deleting it; the history
itself is never pruned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.models import Asset, LicenseRecord
from app.core.services.exceptions import NotFoundError, ValidationError

_UPDATABLE_FIELDS = {
    "license_type",
    "source_url",
    "terms_summary",
    "commercial_use_allowed",
    "proof_relative_path",
    "attribution_required",
    "attribution_text",
    "notes",
}


@dataclass(frozen=True)
class CommercialReadinessResult:
    """Result of :meth:`LicenseService.calculate_asset_commercial_readiness`."""

    asset_id: uuid.UUID
    is_ready: bool
    reason: str


class LicenseService:
    """Add, verify, and query license/commercial-use records for assets."""

    def add_license_record(
        self,
        session: Session,
        asset_id: uuid.UUID,
        *,
        license_type: str,
        source_url: str | None = None,
        terms_summary: str | None = None,
        commercial_use_allowed: bool | None = None,
        proof_relative_path: str | None = None,
        attribution_required: bool = False,
        attribution_text: str | None = None,
        notes: str | None = None,
    ) -> LicenseRecord:
        """Record a new license entry for an asset. Never the first/only record — see class docstring."""
        if session.get(Asset, asset_id) is None:
            raise NotFoundError(f"Asset {asset_id} not found.")
        record = LicenseRecord(
            asset_id=asset_id,
            license_type=license_type,
            source_url=source_url,
            terms_summary=terms_summary,
            commercial_use_allowed=commercial_use_allowed,
            proof_relative_path=proof_relative_path,
            attribution_required=attribution_required,
            attribution_text=attribution_text,
            notes=notes,
        )
        session.add(record)
        session.flush()
        return record

    def update_license_record(
        self, session: Session, record_id: uuid.UUID, **fields: object
    ) -> LicenseRecord:
        """Correct a specific record's fields (e.g. a typo in ``terms_summary``)."""
        record = self._get(session, record_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown LicenseRecord fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(record, key, value)
        session.flush()
        return record

    def verify_license(
        self, session: Session, record_id: uuid.UUID, *, verified_by: str | None = None
    ) -> LicenseRecord:
        record = self._get(session, record_id)
        record.verified = True
        record.verified_at = datetime.now(UTC)
        if verified_by:
            note = f"Verified by {verified_by}."
            record.notes = f"{record.notes}\n{note}" if record.notes else note
        session.flush()
        return record

    def invalidate_license(
        self, session: Session, record_id: uuid.UUID, *, reason: str
    ) -> LicenseRecord:
        """Mark a record's license as no longer valid for commercial use.

        Appends an invalidation note and flips ``commercial_use_allowed``
        to ``False`` rather than deleting the record — the fact that a
        license was once believed valid and later invalidated is itself
        worth keeping in the audit history.
        """
        if not reason or not reason.strip():
            raise ValidationError("invalidate_license requires a reason.")
        record = self._get(session, record_id)
        record.commercial_use_allowed = False
        marker = f"[INVALIDATED {datetime.now(UTC).isoformat()}]: {reason}"
        record.notes = f"{record.notes}\n{marker}" if record.notes else marker
        session.flush()
        return record

    def list_asset_license_history(self, session: Session, asset_id: uuid.UUID) -> list[LicenseRecord]:
        return (
            session.query(LicenseRecord)
            .filter_by(asset_id=asset_id)
            .order_by(LicenseRecord.created_at)
            .all()
        )

    def calculate_asset_commercial_readiness(
        self, session: Session, asset_id: uuid.UUID
    ) -> CommercialReadinessResult:
        """Is this asset clear to use in a monetized upload right now?

        An asset is *not* ready when: it has no license record at all
        (unknown), its most recent record's ``commercial_use_allowed``
        is ``None`` (unknown) or ``False`` (forbidden), or attribution
        is required but ``attribution_text`` is missing.
        """
        if session.get(Asset, asset_id) is None:
            raise NotFoundError(f"Asset {asset_id} not found.")

        history = self.list_asset_license_history(session, asset_id)
        if not history:
            return CommercialReadinessResult(
                asset_id, False, "No license record exists; commercial use is unknown."
            )

        latest = history[-1]
        if latest.commercial_use_allowed is None:
            return CommercialReadinessResult(
                asset_id, False, "Commercial use status is unknown for the latest license record."
            )
        if latest.commercial_use_allowed is False:
            return CommercialReadinessResult(
                asset_id, False, "Commercial use is forbidden under the current license."
            )
        if latest.attribution_required and not (
            latest.attribution_text and latest.attribution_text.strip()
        ):
            return CommercialReadinessResult(
                asset_id, False, "Attribution is required but attribution_text is missing."
            )
        return CommercialReadinessResult(
            asset_id, True, "Commercial use allowed and license requirements are satisfied."
        )

    def generate_attribution_text(self, session: Session, asset_id: uuid.UUID) -> str:
        """Combine attribution text from every record that requires it, de-duplicated."""
        history = self.list_asset_license_history(session, asset_id)
        texts = [
            record.attribution_text
            for record in history
            if record.attribution_required and record.attribution_text
        ]
        return "\n".join(dict.fromkeys(texts))

    def _get(self, session: Session, record_id: uuid.UUID) -> LicenseRecord:
        record = session.get(LicenseRecord, record_id)
        if record is None:
            raise NotFoundError(f"LicenseRecord {record_id} not found.")
        return record
