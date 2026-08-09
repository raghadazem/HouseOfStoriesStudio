"""Tests for ScriptService: the Episode Workspace's Script stage lifecycle."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ScriptStatus
from app.core.models import Episode
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import InvalidTransitionError, NotFoundError, ValidationError
from app.core.services.script_service import ScriptService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
    )
    session.add(episode)
    session.flush()
    return episode


def test_get_or_create_script_creates_a_draft(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    assert script.status == ScriptStatus.DRAFT
    assert script.episode_id == episode.id


def test_get_or_create_script_is_idempotent(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    first = service.get_or_create_script(session, episode.id)
    second = service.get_or_create_script(session, episode.id)
    assert first.id == second.id


def test_get_or_create_script_rejects_missing_episode(session: Session) -> None:
    service = ScriptService()
    with pytest.raises(NotFoundError):
        service.get_or_create_script(session, uuid.uuid4())


def test_update_script_rejects_unknown_fields(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    with pytest.raises(ValidationError):
        service.update_script(session, script.id, status=ScriptStatus.APPROVED)


def test_update_script_sets_allowed_fields(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    updated = service.update_script(
        session, script.id, summary="A turtle is lost.", full_script="...", notes="draft v1"
    )
    assert updated.summary == "A turtle is lost."
    assert updated.full_script == "..."
    assert updated.notes == "draft v1"


def test_submit_script_ready_requires_draft(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    service.submit_script_ready(session, script.id)
    assert script.status == ScriptStatus.READY
    with pytest.raises(InvalidTransitionError):
        service.submit_script_ready(session, script.id)


def test_approve_script_requires_ready_and_records_history(session: Session) -> None:
    service = ScriptService()
    approvals = ApprovalService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)

    with pytest.raises(InvalidTransitionError):
        service.approve_script(session, script.id)

    service.submit_script_ready(session, script.id)
    service.approve_script(session, script.id, decided_by="founder")

    assert script.status == ScriptStatus.APPROVED
    assert (
        approvals.get_current_approval_state(session, "script", script.id)
        == ApprovalDecision.APPROVED
    )


def test_reject_script_returns_to_draft_with_history(session: Session) -> None:
    service = ScriptService()
    approvals = ApprovalService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    service.submit_script_ready(session, script.id)

    service.reject_script(session, script.id, notes="lesson isn't clear")

    assert script.status == ScriptStatus.DRAFT
    assert (
        approvals.get_current_approval_state(session, "script", script.id)
        == ApprovalDecision.REJECTED
    )


def test_reject_script_requires_ready_or_approved(session: Session) -> None:
    service = ScriptService()
    episode = _episode(session)
    script = service.get_or_create_script(session, episode.id)
    with pytest.raises(InvalidTransitionError):
        service.reject_script(session, script.id, notes="not ready to judge yet")
