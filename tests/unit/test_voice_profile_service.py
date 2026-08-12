"""Tests for VoiceProfileService: lifecycle, exactly-one-active, character vs. narrator."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.models import Character
from app.core.models.voice_profile import SPEAKER_KEY_NARRATOR
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.voice_profile_service import VoiceProfileService


def _character(session: Session) -> Character:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    return character


def test_create_voice_profile_for_character(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)

    profile = vps.create_voice_profile(
        session,
        character_id=character.id,
        display_name="Melissa — Warm Young Girl",
        provider_name="elevenlabs",
        provider_voice_id="voice-abc",
    )

    assert profile.character_id == character.id
    assert profile.speaker_key is None
    assert profile.is_active is False
    assert profile.language == "ar"


def test_create_voice_profile_for_narrator(session: Session) -> None:
    vps = VoiceProfileService()

    profile = vps.create_voice_profile(
        session,
        speaker_key=SPEAKER_KEY_NARRATOR,
        display_name="Narrator",
        provider_name="elevenlabs",
        provider_voice_id="voice-narrator",
    )

    assert profile.character_id is None
    assert profile.speaker_key == SPEAKER_KEY_NARRATOR


def test_create_voice_profile_rejects_neither_identity(session: Session) -> None:
    vps = VoiceProfileService()
    with pytest.raises(ValidationError, match="Exactly one"):
        vps.create_voice_profile(
            session, display_name="Bad", provider_name="elevenlabs", provider_voice_id="x"
        )


def test_create_voice_profile_rejects_both_identities(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    with pytest.raises(ValidationError, match="Exactly one"):
        vps.create_voice_profile(
            session,
            character_id=character.id,
            speaker_key=SPEAKER_KEY_NARRATOR,
            display_name="Bad",
            provider_name="elevenlabs",
            provider_voice_id="x",
        )


def test_create_voice_profile_rejects_unknown_character(session: Session) -> None:
    vps = VoiceProfileService()
    with pytest.raises(NotFoundError):
        vps.create_voice_profile(
            session,
            character_id=uuid.uuid4(),
            display_name="Bad",
            provider_name="elevenlabs",
            provider_voice_id="x",
        )


def test_set_active_voice_profile_unsets_previous_sibling(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    first = vps.create_voice_profile(
        session, character_id=character.id, display_name="Take A",
        provider_name="elevenlabs", provider_voice_id="a",
    )
    second = vps.create_voice_profile(
        session, character_id=character.id, display_name="Take B",
        provider_name="elevenlabs", provider_voice_id="b",
    )
    vps.set_active_voice_profile(session, first.id)

    vps.set_active_voice_profile(session, second.id)

    session.refresh(first)
    session.refresh(second)
    assert first.is_active is False
    assert second.is_active is True


def test_set_active_voice_profile_does_not_affect_other_speakers(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    character_profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="elevenlabs", provider_voice_id="a",
    )
    narrator_profile = vps.create_voice_profile(
        session, speaker_key=SPEAKER_KEY_NARRATOR, display_name="Narrator",
        provider_name="elevenlabs", provider_voice_id="n",
    )
    vps.set_active_voice_profile(session, narrator_profile.id)

    vps.set_active_voice_profile(session, character_profile.id)

    session.refresh(narrator_profile)
    assert narrator_profile.is_active is True  # untouched -- different speaker


def test_get_active_voice_profile_returns_none_when_none_active(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="elevenlabs", provider_voice_id="a",
    )

    assert vps.get_active_voice_profile(session, character_id=character.id) is None


def test_get_active_voice_profile_by_character(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="elevenlabs", provider_voice_id="a",
    )
    vps.set_active_voice_profile(session, profile.id)

    active = vps.get_active_voice_profile(session, character_id=character.id)

    assert active is not None
    assert active.id == profile.id


def test_get_active_voice_profile_by_speaker_key(session: Session) -> None:
    vps = VoiceProfileService()
    profile = vps.create_voice_profile(
        session, speaker_key=SPEAKER_KEY_NARRATOR, display_name="Narrator",
        provider_name="elevenlabs", provider_voice_id="n",
    )
    vps.set_active_voice_profile(session, profile.id)

    active = vps.get_active_voice_profile(session, speaker_key=SPEAKER_KEY_NARRATOR)

    assert active is not None
    assert active.id == profile.id


def test_update_voice_profile_edits_allowed_fields(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="elevenlabs", provider_voice_id="a",
    )

    updated = vps.update_voice_profile(session, profile.id, voice_direction="warm, energetic")

    assert updated.voice_direction == "warm, energetic"


def test_update_voice_profile_rejects_unknown_field(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    profile = vps.create_voice_profile(
        session, character_id=character.id, display_name="Melissa",
        provider_name="elevenlabs", provider_voice_id="a",
    )

    with pytest.raises(ValidationError):
        vps.update_voice_profile(session, profile.id, is_active=True)


def test_list_voice_profiles_filters_by_character(session: Session) -> None:
    vps = VoiceProfileService()
    character = _character(session)
    vps.create_voice_profile(
        session, character_id=character.id, display_name="A",
        provider_name="elevenlabs", provider_voice_id="a",
    )
    vps.create_voice_profile(
        session, speaker_key=SPEAKER_KEY_NARRATOR, display_name="N",
        provider_name="elevenlabs", provider_voice_id="n",
    )

    profiles = vps.list_voice_profiles(session, character_id=character.id)

    assert len(profiles) == 1
    assert profiles[0].character_id == character.id
