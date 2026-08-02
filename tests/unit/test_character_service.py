"""Tests for CharacterService: identity CRUD and archiving."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.services.character_service import CharacterService
from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError


def test_create_character(session: Session) -> None:
    cs = CharacterService()
    melissa = cs.create_character(
        session, slug="melissa", name_ar="ميليسا", name_en="Melissa", age=6,
        role="older sister", traits=["brave", "curious"],
    )
    assert melissa.name_ar == "ميليسا"
    assert melissa.is_archived is False


def test_create_character_rejects_duplicate_slug(session: Session) -> None:
    cs = CharacterService()
    cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    with pytest.raises(ConflictError):
        cs.create_character(session, slug="melissa", name_ar="بيلسان", name_en="Bilsan")


def test_get_character_by_slug(session: Session) -> None:
    cs = CharacterService()
    cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    found = cs.get_character_by_slug(session, "melissa")
    assert found.name_en == "Melissa"


def test_get_character_by_slug_not_found(session: Session) -> None:
    cs = CharacterService()
    with pytest.raises(NotFoundError):
        cs.get_character_by_slug(session, "nope")


def test_get_character_not_found(session: Session) -> None:
    cs = CharacterService()
    with pytest.raises(NotFoundError):
        cs.get_character(session, uuid.uuid4())


def test_update_character_rejects_slug_change(session: Session) -> None:
    cs = CharacterService()
    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    with pytest.raises(ValidationError):
        cs.update_character(session, melissa.id, slug="renamed")


def test_update_character_allowed_fields(session: Session) -> None:
    cs = CharacterService()
    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    updated = cs.update_character(session, melissa.id, age=7)
    assert updated.age == 7


def test_archive_character(session: Session) -> None:
    cs = CharacterService()
    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    cs.archive_character(session, melissa.id)
    assert melissa.is_archived is True


def test_list_characters_excludes_archived_by_default(session: Session) -> None:
    cs = CharacterService()
    melissa = cs.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    cs.create_character(session, slug="bilsan", name_ar="بيلسان", name_en="Bilsan")
    cs.archive_character(session, melissa.id)

    active = cs.list_characters(session)
    assert {c.slug for c in active} == {"bilsan"}

    everyone = cs.list_characters(session, include_archived=True)
    assert {c.slug for c in everyone} == {"melissa", "bilsan"}
