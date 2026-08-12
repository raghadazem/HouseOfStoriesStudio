"""Tests for PronunciationOverrideService: small global CRUD."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.services.pronunciation_override_service import PronunciationOverrideService


def test_create_override(session: Session) -> None:
    service = PronunciationOverrideService()

    override = service.create_override(session, term="تورتور", replacement="طُرطُر")

    assert override.term == "تورتور"
    assert override.replacement == "طُرطُر"


def test_create_override_rejects_duplicate_term(session: Session) -> None:
    service = PronunciationOverrideService()
    service.create_override(session, term="تورتور", replacement="طُرطُر")

    with pytest.raises(ConflictError):
        service.create_override(session, term="تورتور", replacement="different")


def test_create_override_rejects_empty_term_or_replacement(session: Session) -> None:
    service = PronunciationOverrideService()
    with pytest.raises(ValidationError):
        service.create_override(session, term="  ", replacement="x")
    with pytest.raises(ValidationError):
        service.create_override(session, term="x", replacement="  ")


def test_update_override_replacement(session: Session) -> None:
    service = PronunciationOverrideService()
    override = service.create_override(session, term="تورتور", replacement="طُرطُر")

    updated = service.update_override(session, override.id, replacement="طرطور")

    assert updated.replacement == "طرطور"


def test_remove_override(session: Session) -> None:
    service = PronunciationOverrideService()
    override = service.create_override(session, term="تورتور", replacement="طُرطُر")

    service.remove_override(session, override.id)

    assert service.list_overrides(session) == []


def test_remove_unknown_override_raises(session: Session) -> None:
    service = PronunciationOverrideService()
    with pytest.raises(NotFoundError):
        service.remove_override(session, uuid.uuid4())


def test_list_overrides_ordered_by_term(session: Session) -> None:
    service = PronunciationOverrideService()
    service.create_override(session, term="ب", replacement="x")
    service.create_override(session, term="أ", replacement="y")

    overrides = service.list_overrides(session)

    assert [o.term for o in overrides] == ["أ", "ب"]
