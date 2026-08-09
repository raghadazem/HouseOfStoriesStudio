"""Tests for SongService: the Episode Workspace's Music stage's written song package."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.models import Episode
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.song_service import SongService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
    )
    session.add(episode)
    session.flush()
    return episode


def test_get_or_create_song_creates_an_empty_row(session: Session) -> None:
    service = SongService()
    episode = _episode(session)
    song = service.get_or_create_song(session, episode.id)
    assert song.episode_id == episode.id
    assert song.lyrics_ar is None


def test_get_or_create_song_is_idempotent(session: Session) -> None:
    service = SongService()
    episode = _episode(session)
    first = service.get_or_create_song(session, episode.id)
    second = service.get_or_create_song(session, episode.id)
    assert first.id == second.id


def test_get_or_create_song_rejects_missing_episode(session: Session) -> None:
    service = SongService()
    with pytest.raises(NotFoundError):
        service.get_or_create_song(session, uuid.uuid4())


def test_update_song_rejects_unknown_fields(session: Session) -> None:
    service = SongService()
    episode = _episode(session)
    song = service.get_or_create_song(session, episode.id)
    with pytest.raises(ValidationError):
        service.update_song(session, song.id, status="approved")


def test_update_song_sets_allowed_fields(session: Session) -> None:
    service = SongService()
    episode = _episode(session)
    song = service.get_or_create_song(session, episode.id)
    updated = service.update_song(
        session, song.id,
        lyrics_ar="معاً نستطيع",
        purpose="Reinforce the lesson through a catchy chorus.",
        duration_seconds=60,
        production_notes="Upbeat, ukulele, ~100 BPM.",
        suno_style_prompt="Children's animated sing-along, warm acoustic pop.",
    )
    assert updated.lyrics_ar == "معاً نستطيع"
    assert updated.purpose == "Reinforce the lesson through a catchy chorus."
    assert updated.duration_seconds == 60
    assert updated.production_notes == "Upbeat, ukulele, ~100 BPM."
    assert updated.suno_style_prompt == "Children's animated sing-along, warm acoustic pop."


def test_update_song_rejects_missing_song(session: Session) -> None:
    service = SongService()
    with pytest.raises(NotFoundError):
        service.update_song(session, uuid.uuid4(), lyrics_ar="x")
