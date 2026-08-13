"""VoiceProfile model — a character's (or the Narrator's) persistent voice identity.

Deliberately separate from :class:`~app.core.models.character.CharacterVersion`:
a voice identity has a different lifecycle than the visual design it's
paired with — Melissa's voice must stay the same across every future
``CharacterVersion`` (an outfit/palette redesign), not be re-selected
every time the visual design changes. See
``docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md``.

The Narrator is not a fake :class:`~app.core.models.character.Character`
row — narration has no visual design, no scenes "feature" it. Exactly
one of ``character_id``/``speaker_key`` is set per profile (enforced in
:class:`~app.core.services.voice_profile_service.VoiceProfileService`,
not a CHECK constraint, matching
:class:`~app.core.models.character.CharacterReference`'s own precedent
for cross-field invariants).

At most one profile per speaker may be ``is_active`` at a time —
enforced by :meth:`VoiceProfileService.set_active_voice_profile`, the
same "unset every sibling in one call" pattern
:meth:`~app.core.services.character_version_service.CharacterVersionService.set_canon_reference`
already established for canon reference images.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.core.models.asset import Asset
    from app.core.models.character import Character

# speaker_key values kept as plain string constants (not an enum) since a
# future episode can introduce another non-character speaker without a
# schema change -- see NON_CHARACTER_SPEAKERS below.
SPEAKER_KEY_NARRATOR = "narrator"
SPEAKER_KEY_BIRD = "bird"
SPEAKER_KEY_TURTLE_MOTHER = "turtle_mother"


@dataclass(frozen=True)
class NonCharacterSpeaker:
    """One non-Character speaker identity: its persisted ``speaker_key``,
    a human-readable label for the GUI, and every raw ``dialogue_ar``
    speaker string that should resolve to it.

    ``aliases`` is matched case-insensitively (Arabic text is unaffected
    by ``str.lower()``, so this is free for English aliases without a
    separate code path). Exact membership only -- no fuzzy matching, no
    substrings, no inference. Adding a future non-character speaker (e.g.
    a new episode's one-off supporting character) means adding one more
    entry to :data:`NON_CHARACTER_SPEAKERS`, not a new table or a new
    special case in :meth:`~app.core.services.scene_service.SceneService.resolve_speaker`.
    """

    speaker_key: str
    display_label: str
    aliases: frozenset[str]


# The complete set of non-Character speaker identities Milestone 9 (and
# Episode 001's Bird/Turtle Mother extension) needs. The single source of
# truth for both SceneService.resolve_speaker's alias matching and the
# Voice tab's Voice Profiles summary -- neither re-derives or duplicates
# this list.
NON_CHARACTER_SPEAKERS: tuple[NonCharacterSpeaker, ...] = (
    NonCharacterSpeaker(
        speaker_key=SPEAKER_KEY_NARRATOR,
        display_label="Narrator",
        aliases=frozenset({"narrator", "الراوي", "راوي"}),
    ),
    NonCharacterSpeaker(
        speaker_key=SPEAKER_KEY_BIRD,
        display_label="Bird",
        aliases=frozenset({"bird", "العصفور"}),
    ),
    NonCharacterSpeaker(
        speaker_key=SPEAKER_KEY_TURTLE_MOTHER,
        display_label="Turtle Mother",
        aliases=frozenset({"turtle_mother", "turtle mother", "أم السلحفاة"}),
    ),
)


class VoiceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A persistent, reproducible voice identity for one character or the Narrator."""

    __tablename__ = "voice_profiles"

    character_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=True
    )
    speaker_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    language: Mapped[str] = mapped_column(String(32), default="ar", nullable=False)
    dialect_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Free-text guidance a human used to choose/tune this voice: age
    # impression, gender presentation, speaking style, pace, pitch,
    # emotional range -- collapsed into one field (mirrors
    # CharacterVersion.master_prompt's own shape) since nothing queries
    # these independently; see the design doc for why six speculative
    # columns were rejected.
    voice_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider-specific generation knobs (e.g. stability/similarity_boost/
    # style for ElevenLabs) -- passed straight into
    # GenerationRequest.parameters, same pattern as image_size (Milestone 8).
    default_parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    sample_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    character: Mapped[Character | None] = relationship()
    sample_asset: Mapped[Asset | None] = relationship(foreign_keys=[sample_asset_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        speaker = self.character_id or self.speaker_key
        return f"<VoiceProfile {self.display_name!r} speaker={speaker} active={self.is_active}>"
