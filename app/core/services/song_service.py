"""SongService — the Episode Workspace's Music stage's written song package.

Deliberately minimal: unlike ``ScriptService``, there is no status
lifecycle here — nothing in this milestone reviews or approves lyrics.
This service only ever assembles/edits plain text (lyrics, purpose,
production notes, a Suno-ready style prompt) for a human or an external
tool to actually produce the audio from. No AI provider is ever called
with this data.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import Episode, Song
from app.core.services.exceptions import NotFoundError, ValidationError

_UPDATABLE_FIELDS = {"lyrics_ar", "purpose", "duration_seconds", "production_notes", "suno_style_prompt"}


class SongService:
    """Manages the one-per-episode Song record."""

    def get_or_create_song(self, session: Session, episode_id: uuid.UUID) -> Song:
        """Return this episode's Song, creating an empty one if needed.

        Mirrors :meth:`~app.core.services.script_service.ScriptService.get_or_create_script`:
        a Song always exists once the workspace's Music tab has been
        opened once — there is no separate "create song" action.
        """
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        song = session.query(Song).filter_by(episode_id=episode_id).one_or_none()
        if song is None:
            song = Song(episode_id=episode_id)
            session.add(song)
            session.flush()
        return song

    def update_song(self, session: Session, song_id: uuid.UUID, **fields: object) -> Song:
        song = self._get(session, song_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Song fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(song, key, value)
        session.flush()
        return song

    @staticmethod
    def _get(session: Session, song_id: uuid.UUID) -> Song:
        song = session.get(Song, song_id)
        if song is None:
            raise NotFoundError(f"Song {song_id} not found.")
        return song
