"""Tests for ApprovalService: the generic, immutable approval audit trail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, ApprovalStatus, AssetType
from app.core.models import Asset, Episode, Scene
from app.core.models.approval import ApprovalRecord
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
    # Ordered by revision (deterministic), not decided_at (can tie) — see
    # docs/engineering/WINDOWS_DEVELOPMENT.md for why this changed.
    assert [r.revision for r in history] == [1, 2]


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


# --- Windows/Test Stabilization: deterministic revision ordering ------
# See docs/engineering/WINDOWS_DEVELOPMENT.md for the full root-cause
# writeup (ORDER BY decided_at DESC alone was non-deterministic when two
# decisions land on the same timestamp).


def test_revision_numbers_are_assigned_sequentially_and_deterministically(
    session: Session,
) -> None:
    service = ApprovalService()
    asset = _asset(session)

    first = service.approve_entity(session, "asset", asset.id)
    second = service.request_changes(session, "asset", asset.id, notes="fix it")
    third = service.reject_entity(session, "asset", asset.id, notes="never mind, reject")

    assert (first.revision, second.revision, third.revision) == (1, 2, 3)


def test_current_state_returns_highest_revision_even_with_identical_timestamps(
    session: Session,
) -> None:
    """The exact bug this migration fixes: two decisions sharing a
    ``decided_at`` value used to make "current state" non-deterministic.
    Forces the tie directly (rather than hoping two real calls race)
    so this test is itself deterministic."""
    service = ApprovalService()
    asset = _asset(session)
    tied_timestamp = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

    first = service.approve_entity(session, "asset", asset.id)
    first.decided_at = tied_timestamp
    second = service.request_changes(session, "asset", asset.id, notes="actually, fix this")
    second.decided_at = tied_timestamp  # identical to `first` — the tie
    session.flush()

    assert first.decided_at == second.decided_at  # confirm the tie is real
    assert second.revision > first.revision
    assert (
        service.get_current_approval_state(session, "asset", asset.id)
        == ApprovalDecision.NEEDS_CHANGES
    )


def test_approval_history_order_is_deterministic_with_identical_timestamps(
    session: Session,
) -> None:
    service = ApprovalService()
    asset = _asset(session)
    tied_timestamp = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

    service.approve_entity(session, "asset", asset.id)
    service.reject_entity(session, "asset", asset.id, notes="no good")
    for record in service.list_approval_history(session, "asset", asset.id):
        record.decided_at = tied_timestamp
    session.flush()

    history = service.list_approval_history(session, "asset", asset.id)
    assert [r.decision for r in history] == [ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]
    assert [r.revision for r in history] == [1, 2]


def test_two_entities_maintain_independent_revision_sequences(session: Session) -> None:
    service = ApprovalService()
    asset_a = _asset(session)
    asset_b = _asset(session, relative_path="episodes/ep001/images/b.png", checksum="b" * 64)

    service.approve_entity(session, "asset", asset_a.id)
    a_second = service.reject_entity(session, "asset", asset_a.id, notes="redo")

    b_first = service.approve_entity(session, "asset", asset_b.id)

    assert a_second.revision == 2
    assert b_first.revision == 1  # unaffected by asset_a's history


def test_duplicate_revision_for_same_entity_violates_unique_constraint(
    session: Session,
) -> None:
    """Guards the invariant ApprovalService._next_revision relies on —
    bypassing the service and writing a raw duplicate must fail loudly,
    not silently produce two "revision 1" rows for the same entity."""
    asset = _asset(session)
    session.add(
        ApprovalRecord(
            entity_type="asset", entity_id=asset.id,
            decision=ApprovalDecision.APPROVED, revision=1,
        )
    )
    session.flush()

    session.add(
        ApprovalRecord(
            entity_type="asset", entity_id=asset.id,
            decision=ApprovalDecision.REJECTED, revision=1, notes="dup",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


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


def test_list_pending_review_assets_filters_by_scene(session: Session) -> None:
    service = ApprovalService()
    episode = Episode(slug="ep001_scene_test", number=2, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    scene = Scene(episode_id=episode.id, order_index=1)
    session.add(scene)
    session.flush()

    in_scene = _asset(
        session, relative_path="episodes/ep001/images/scene.png", checksum="e" * 64, scene_id=scene.id
    )
    _asset(session, relative_path="episodes/ep001/images/other.png", checksum="f" * 64)

    pending = service.list_pending_review_assets(session, scene_id=scene.id)

    assert [a.id for a in pending] == [in_scene.id]


# --- Milestone 4B: decide_asset_review (the review queue's Approve/Reject) ---


def test_decide_asset_review_approves_and_records_history(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)

    result = service.decide_asset_review(
        session, asset.id, ApprovalDecision.APPROVED, decided_by="founder"
    )

    assert result.approval_status == ApprovalStatus.APPROVED
    history = service.list_approval_history(session, "asset", asset.id)
    assert [r.decision for r in history] == [ApprovalDecision.APPROVED]
    assert history[0].decided_by == "founder"


def test_decide_asset_review_rejects_and_requires_notes(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)

    with pytest.raises(ValidationError, match="Notes are required"):
        service.decide_asset_review(session, asset.id, ApprovalDecision.REJECTED)

    result = service.decide_asset_review(
        session, asset.id, ApprovalDecision.REJECTED, notes="blurry, redo"
    )
    assert result.approval_status == ApprovalStatus.REJECTED
    history = service.list_approval_history(session, "asset", asset.id)
    assert history[0].decision == ApprovalDecision.REJECTED
    assert history[0].notes == "blurry, redo"


def test_decide_asset_review_rejects_non_draft_assets(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session, approval_status=ApprovalStatus.APPROVED)

    with pytest.raises(ValidationError, match="Only a draft asset can be reviewed"):
        service.decide_asset_review(session, asset.id, ApprovalDecision.APPROVED)


def test_decide_asset_review_rejects_needs_changes_decision(session: Session) -> None:
    service = ApprovalService()
    asset = _asset(session)

    with pytest.raises(ValidationError, match="only accepts approved/rejected"):
        service.decide_asset_review(session, asset.id, ApprovalDecision.NEEDS_CHANGES, notes="x")


def test_decide_asset_review_rejects_missing_asset(session: Session) -> None:
    service = ApprovalService()
    with pytest.raises(NotFoundError):
        service.decide_asset_review(session, uuid.uuid4(), ApprovalDecision.APPROVED)
