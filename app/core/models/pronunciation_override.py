"""PronunciationOverride model — a small, global term-to-replacement lookup.

Global, not scoped to a character/episode/voice profile: a word like
"تورتور" should be pronounced the same way regardless of which
character or scene speaks it. Deliberately not a "generalized
linguistic platform" — a flat table of (term, replacement) pairs,
applied as a substring substitution pass in
``app.core.ai.text_normalization``, editable through a small Settings
GUI table so a future character's name never requires a source-code
release. See ``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md``.
"""

from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PronunciationOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One term -> pronunciation-friendly replacement, applied globally."""

    __tablename__ = "pronunciation_overrides"
    __table_args__ = (UniqueConstraint("term", name="uq_pronunciation_override_term"),)

    term: Mapped[str] = mapped_column(String(128), nullable=False)
    replacement: Mapped[str] = mapped_column(String(256), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<PronunciationOverride {self.term!r} -> {self.replacement!r}>"
