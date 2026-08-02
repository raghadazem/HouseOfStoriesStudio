"""CharacterService — identity-level Character CRUD.

Visual design (Character Lock) lives on ``CharacterVersion`` and is
managed by :class:`~app.core.services.character_version_service.CharacterVersionService`;
this service only touches the stable identity fields.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import Character
from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError

_UPDATABLE_FIELDS = {"name_ar", "name_en", "age", "role", "traits"}


class CharacterService:
    """CRUD for :class:`~app.core.models.character.Character` identity records."""

    def create_character(
        self,
        session: Session,
        *,
        slug: str,
        name_ar: str,
        name_en: str,
        age: int | None = None,
        role: str | None = None,
        traits: list[str] | None = None,
    ) -> Character:
        """Create a new character.

        Raises:
            ConflictError: If ``slug`` is already in use.
        """
        if session.query(Character).filter_by(slug=slug).count() > 0:
            raise ConflictError(f"Character slug {slug!r} already exists.")
        character = Character(
            slug=slug,
            name_ar=name_ar,
            name_en=name_en,
            age=age,
            role=role,
            traits=list(traits or []),
        )
        session.add(character)
        session.flush()
        return character

    def get_character(self, session: Session, character_id: uuid.UUID) -> Character:
        character = session.get(Character, character_id)
        if character is None:
            raise NotFoundError(f"Character {character_id} not found.")
        return character

    def get_character_by_slug(self, session: Session, slug: str) -> Character:
        character = session.query(Character).filter_by(slug=slug).one_or_none()
        if character is None:
            raise NotFoundError(f"Character with slug {slug!r} not found.")
        return character

    def list_characters(
        self, session: Session, *, include_archived: bool = False
    ) -> list[Character]:
        query = session.query(Character)
        if not include_archived:
            query = query.filter_by(is_archived=False)
        return query.order_by(Character.slug).all()

    def update_character(
        self, session: Session, character_id: uuid.UUID, **fields: object
    ) -> Character:
        """Update identity fields. ``slug`` is intentionally not updatable.

        The slug anchors the character's on-disk folder
        (``production/characters/<slug>/``) and every asset path under
        it — renaming it would orphan existing managed files.
        """
        character = self.get_character(session, character_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Character fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(character, key, value)
        session.flush()
        return character

    def archive_character(self, session: Session, character_id: uuid.UUID) -> Character:
        """Mark a character archived (soft-delete — history is never dropped)."""
        character = self.get_character(session, character_id)
        character.is_archived = True
        session.flush()
        return character
