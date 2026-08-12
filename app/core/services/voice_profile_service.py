"""VoiceProfileService — a character's (or the Narrator's) persistent voice identity.

Deliberately separate from
:class:`~app.core.services.character_version_service.CharacterVersionService`:
a voice identity has a different lifecycle than the visual design it's
paired with (see the model's own docstring). Approval is **not** a new
field on :class:`~app.core.models.voice_profile.VoiceProfile` — it
reuses :class:`~app.core.services.approval_service.ApprovalService`
with ``entity_type="voice_profile"``, the same generic mechanism every
other approvable entity in this codebase already uses.

At most one profile per speaker (``character_id`` or ``speaker_key``)
may be ``is_active`` — :meth:`set_active_voice_profile` unsets every
sibling in the same call, the same pattern
:meth:`~app.core.services.character_version_service.CharacterVersionService.set_canon_reference`
already established for canon reference images.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import Character, VoiceProfile
from app.core.services.exceptions import NotFoundError, ValidationError

_UPDATABLE_FIELDS = {
    "display_name",
    "provider_name",
    "provider_voice_id",
    "provider_model",
    "language",
    "dialect_style",
    "voice_direction",
    "default_parameters",
    "sample_asset_id",
}


class VoiceProfileService:
    """Create, edit, and select the active VoiceProfile for one speaker."""

    def create_voice_profile(
        self,
        session: Session,
        *,
        display_name: str,
        provider_name: str,
        provider_voice_id: str,
        character_id: uuid.UUID | None = None,
        speaker_key: str | None = None,
        provider_model: str | None = None,
        language: str = "ar",
        dialect_style: str | None = None,
        voice_direction: str | None = None,
        default_parameters: dict[str, object] | None = None,
        sample_asset_id: uuid.UUID | None = None,
    ) -> VoiceProfile:
        """Create a new (initially inactive) voice profile for one speaker.

        Raises:
            ValidationError: Neither or both of ``character_id``/
                ``speaker_key`` were given — exactly one must identify
                the speaker.
            NotFoundError: ``character_id`` was given but doesn't exist.
        """
        self._validate_speaker_identity(session, character_id, speaker_key)
        profile = VoiceProfile(
            character_id=character_id,
            speaker_key=speaker_key,
            display_name=display_name,
            provider_name=provider_name,
            provider_voice_id=provider_voice_id,
            provider_model=provider_model,
            language=language,
            dialect_style=dialect_style,
            voice_direction=voice_direction,
            default_parameters=dict(default_parameters or {}),
            sample_asset_id=sample_asset_id,
            is_active=False,
        )
        session.add(profile)
        session.flush()
        return profile

    def update_voice_profile(
        self, session: Session, profile_id: uuid.UUID, **fields: object
    ) -> VoiceProfile:
        """Edit a voice profile's fields. Never touches ``is_active`` — use
        :meth:`set_active_voice_profile` for that, so the unset-siblings
        guarantee can never be bypassed via a generic field update."""
        profile = self._get(session, profile_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown VoiceProfile fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(profile, key, value)
        session.flush()
        return profile

    def set_active_voice_profile(self, session: Session, profile_id: uuid.UUID) -> VoiceProfile:
        """Make ``profile_id`` the one active profile for its speaker.

        Unsets ``is_active`` on every sibling profile sharing the same
        ``character_id``/``speaker_key`` first, in the same flush.
        """
        profile = self._get(session, profile_id)
        for sibling in self._siblings(session, profile):
            sibling.is_active = sibling.id == profile.id
        session.flush()
        return profile

    def get_active_voice_profile(
        self,
        session: Session,
        *,
        character_id: uuid.UUID | None = None,
        speaker_key: str | None = None,
    ) -> VoiceProfile | None:
        """The active profile for one speaker, or ``None`` if none is active.

        Exactly one of ``character_id``/``speaker_key`` should be given
        (mirrors how a speaker is always identified elsewhere in this
        milestone — see ``SceneService.resolve_speaker``).
        """
        query = session.query(VoiceProfile).filter_by(is_active=True)
        if character_id is not None:
            query = query.filter_by(character_id=character_id)
        else:
            query = query.filter_by(speaker_key=speaker_key)
        return query.one_or_none()

    def list_voice_profiles(
        self,
        session: Session,
        *,
        character_id: uuid.UUID | None = None,
        speaker_key: str | None = None,
    ) -> list[VoiceProfile]:
        query = session.query(VoiceProfile)
        if character_id is not None:
            query = query.filter_by(character_id=character_id)
        if speaker_key is not None:
            query = query.filter_by(speaker_key=speaker_key)
        return query.order_by(VoiceProfile.created_at).all()

    def _siblings(self, session: Session, profile: VoiceProfile) -> list[VoiceProfile]:
        if profile.character_id is not None:
            return (
                session.query(VoiceProfile).filter_by(character_id=profile.character_id).all()
            )
        return session.query(VoiceProfile).filter_by(speaker_key=profile.speaker_key).all()

    @staticmethod
    def _validate_speaker_identity(
        session: Session, character_id: uuid.UUID | None, speaker_key: str | None
    ) -> None:
        if (character_id is None) == (speaker_key is None):
            raise ValidationError(
                "Exactly one of character_id/speaker_key must be set for a VoiceProfile."
            )
        if character_id is not None and session.get(Character, character_id) is None:
            raise NotFoundError(f"Character {character_id} not found.")

    def _get(self, session: Session, profile_id: uuid.UUID) -> VoiceProfile:
        profile = session.get(VoiceProfile, profile_id)
        if profile is None:
            raise NotFoundError(f"VoiceProfile {profile_id} not found.")
        return profile
