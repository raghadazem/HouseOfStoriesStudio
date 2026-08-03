"""Tests for ApprovalService: the generic, immutable approval audit trail."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ApprovalStatus, AssetType
from app.core.models import Asset, Episode
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import NotFoundError, ValidationError


def _asset(session: Session, **overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "f.png",
        "relative_path": "episodes/ep001/images/f.png",
        "checksum": "a" * 64,
    }
    defaults.update(overrides)
    asset = Asset(**defaults)
    session.add(asset)
    session.flush()
    return asset


def test_approve_entity_rejects_unknown_entity_type(session: Session) -> None:
    service = ApprovalService()
    with pytest.raises(ValidationError, match="Unsupported entity_type"):
        service.approve_entity(session, "not_a_real_type", uuid.uuid4())


def test_approve_entity_rejects_missing_entity(session: Session) -> None:
    service = ApprovalService()
    with pytest.raises(NotFoundError):
        service.approve_entity(session, "asset", uuid.uuid4())


def test_reject_entity_requires_notes(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)
    with pytest.raises(ValidationError, match="Notes are required"):
        service.reject_entity(session, "asset", asset.id, notes="")


def test_request_changes_requires_notes(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)
    with pytest.raises(ValidationError, match="Notes are required"):
        service.request_changes(session, "asset", asset.id, notes="   ")


def test_approve_reject_and_history_ordering(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)

    service.approve_entity(session, "asset", asset.id, decided_by="founder")
    service.reject_entity(session, "asset", asset.id, notes="actually needs a redo")

    history = service.list_approval_history(session, "asset", asset.id)
    assert [r.decision for r in history] == [ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]


def test_get_current_approval_state_returns_latest(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)
    assert service.get_current_approval_state(session, "asset", asset.id) is None

    service.approve_entity(session, "asset", asset.id)
    assert service.get_current_approval_state(session, "asset", asset.id) == ApprovalDecision.APPROVED

    service.request_changes(session, "asset", asset.id, notes="fix the palette")
    assert (
        service.get_current_approval_state(session, "asset", asset.id)
        == ApprovalDecision.NEEDS_CHANGES
    )


def test_approval_records_are_never_mutated_in_place(session: Session) -> None:
    """Every decision is a new row; the audit log is append-only."""
    service = ApprovalService()
    asset = _asset(session)

    service.approve_entity(session, "asset", asset.id, notes="first pass")
    first_record = service.list_approval_history(session, "asset", asset.id)[0]
    first_id, first_decision, first_notes = first_record.id, first_record.decision, first_record.notes

    service.reject_entity(session, "asset", asset.id, notes="second pass, rejected")

    history = service.list_approval_history(session, "asset", asset.id)
    assert len(history) == 2
    unchanged = next(r for r in history if r.id == first_id)
    assert unchanged.decision == first_decision
    assert unchanged.notes == first_notes


def test_submit_for_review_validates_entity_without_writing_a_record(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)
    state = service.submit_for_review(session, "asset", asset.id)
    assert state is None  # no decision recorded yet
    assert service.list_approval_history(session, "asset", asset.id) == []


# --- Milestone 3.5: review queue (list_pending_review_assets) ---------


def test_list_pending_review_assets_returns_only_draft_assets(session: Session) -> None:
    service = ApprovalService()
    draft_asset = _asset(session)
    _asset(
        session,
        relative_path="episodes/ep001/images/g.png",
        checksum="b" * 64,
        approval_status=ApprovalStatus.APPROVED,
    )

    pending = service.list_pending_review_assets(session)

    assert [a.id for a in pending] == [draft_asset.id]


def test_list_pending_review_assets_filters_by_episode(session: Session) -> None:
    service = ApprovalService()
    episode = Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()

    in_episode = _asset(session, episode_id=episode.id)
    _asset(session, relative_path="episodes/ep002/images/g.png", checksum="c" * 64)

    pending = service.list_pending_review_assets(session, episode_id=episode.id)

    assert [a.id for a in pending] == [in_episode.id]


def test_list_pending_review_assets_filters_by_source_tool(session: Session) -> None:
    service = ApprovalService()
    _asset(session)
    generated = _asset(
        session,
        relative_path="episodes/ep001/images/h.png",
        checksum="d" * 64,
        source_tool="mock_provider",
    )

    pending = service.list_pending_review_assets(session, source_tool="mock_provider")

    assert [a.id for a in pending] == [generated.id]
