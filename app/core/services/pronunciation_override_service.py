"""PronunciationOverrideService — small CRUD over the global term-replacement table.

Global, not scoped to a character/episode/voice profile — see
``app.core.models.pronunciation_override`` for why. Deliberately tiny:
create/update/remove/list, nothing else. Editable through a small
Settings GUI table so a future character's name never requires a
source-code release.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import PronunciationOverride
from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError


class PronunciationOverrideService:
    """Create, edit, remove, and list global pronunciation overrides."""

    def create_override(
        self, session: Session, *, term: str, replacement: str, notes: str | None = None
    ) -> PronunciationOverride:
        term = term.strip()
        replacement = replacement.strip()
        if not term or not replacement:
            raise ValidationError("Both term and replacement are required.")
        if session.query(PronunciationOverride).filter_by(term=term).count() > 0:
            raise ConflictError(f"A pronunciation override for {term!r} already exists.")
        override = PronunciationOverride(term=term, replacement=replacement, notes=notes)
        session.add(override)
        session.flush()
        return override

    def update_override(
        self,
        session: Session,
        override_id: uuid.UUID,
        *,
        replacement: str | None = None,
        notes: str | None = None,
    ) -> PronunciationOverride:
        override = self._get(session, override_id)
        if replacement is not None:
            replacement = replacement.strip()
            if not replacement:
                raise ValidationError("replacement cannot be empty.")
            override.replacement = replacement
        if notes is not None:
            override.notes = notes
        session.flush()
        return override

    def remove_override(self, session: Session, override_id: uuid.UUID) -> None:
        override = self._get(session, override_id)
        session.delete(override)
        session.flush()

    def list_overrides(self, session: Session) -> list[PronunciationOverride]:
        return session.query(PronunciationOverride).order_by(PronunciationOverride.term).all()

    def _get(self, session: Session, override_id: uuid.UUID) -> PronunciationOverride:
        override = session.get(PronunciationOverride, override_id)
        if override is None:
            raise NotFoundError(f"PronunciationOverride {override_id} not found.")
        return override
