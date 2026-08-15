"""DialogueLine model — a stable, persisted identity for one line of a Scene's dialogue.

``Scene.dialogue_ar`` remains the single authored source of truth (a
human types/edits it as one flowing text block, exactly as before this
model existed). ``DialogueLine`` is a synchronized structural index over
it, never a second editing surface: :meth:`~app.core.services.scene_service.SceneService.sync_dialogue_lines`
re-parses ``dialogue_ar`` on every edit and reconciles the result
against existing rows, preserving each row's ``id`` whenever its exact
``(speaker_raw, authored_text)`` still appears anywhere in the new
parse — regardless of position. This is what lets a dialogue line
survive being reordered or having another line inserted before it,
while an edit to the line's own words correctly retires the old row
(``is_current=False``, never deleted) and creates a new one, since
previously-generated audio genuinely no longer matches changed text.

See ``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md`` for the
full reconciliation algorithm and rationale.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.core.models.character import Character
    from app.core.models.episode import Scene


class DialogueLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One stable-identity line within a Scene's authored dialogue."""

    __tablename__ = "dialogue_lines"

    scene_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Display/sort order only -- not an identity, no uniqueness needed.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Exactly as it appeared in dialogue_ar, e.g. "ميليسا" or "Narrator".
    speaker_raw: Mapped[str] = mapped_column(String(128), nullable=False)
    # Resolved cache, re-resolved on every sync -- at most one of
    # character_id/speaker_key is set (enforced in SceneService, not a
    # CHECK constraint, matching CharacterReference's own precedent).
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    speaker_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Copied verbatim from the parse -- never independently editable.
    authored_text: Mapped[str] = mapped_column(Text, nullable=False)

    # A human-reviewed, fully/appropriately vocalized (diacritized)
    # rendering of authored_text for TTS purposes only -- NULL until a
    # human has actually reviewed this exact row's pronunciation.
    # Never auto-derived (no LLM/heuristic writes this), never fed back
    # into authored_text, and inherently tied to one authored_text
    # revision: editing dialogue_ar retires this row (is_current=False)
    # and creates a brand-new row with this column NULL again, so a
    # stale vocalization can never silently survive a script edit. When
    # set, VoiceLineWorkflow-bound generation (run_voice_line_batch) and
    # VoiceProductionCandidateService use it as the base text instead of
    # normalize_arabic_line(authored_text) -- see
    # docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md. A registered
    # LinePerformanceOverride (e.g. Tortor's Scene 7 laugh cue) still
    # takes precedence over this, since that's a performance
    # substitution, not a pronunciation refinement.
    reviewed_tts_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # False once superseded by a later dialogue_ar edit. Never deleted,
    # so every GenerationJob/Asset that pointed at this row stays valid
    # history -- see the module docstring.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    scene: Mapped[Scene] = relationship()
    character: Mapped[Character | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<DialogueLine {self.speaker_raw!r} scene={self.scene_id} current={self.is_current}>"
