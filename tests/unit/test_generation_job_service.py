"""Tests for GenerationJobService: lifecycle, honest cancellation, retry, batching.

Pure persistence/state-machine tests — no provider, no workflow, no
network. See ``tests/unit/test_generation_runner.py`` for the tests
that exercise this service together with ``AIOrchestrator``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.ai.generation_job_service import GenerationJobService
from app.core.db.enums import ApprovalStatus, AssetType, GenerationJobStatus
from app.core.models import Asset, Character, CharacterVersion, Episode, Scene
from app.core.services.exceptions import InvalidTransitionError, NotFoundError


def _real_asset_id(session: Session) -> uuid.UUID:
    """GenerationJob.result_asset_id is a real FK — SQLite enforces it
    (PRAGMA foreign_keys=ON), so tests need an actual Asset row, not a
    random UUID."""
    asset = Asset(
        asset_type=AssetType.IMAGE,
        original_filename="ref.png",
        relative_path=f"characters/test/{uuid.uuid4()}.png",
        checksum=uuid.uuid4().hex.ljust(64, "0"),
        approval_status=ApprovalStatus.DRAFT,
    )
    session.add(asset)
    session.flush()
    return asset.id


def _real_character_version_id(session: Session) -> uuid.UUID:
    character = Character(slug=f"char-{uuid.uuid4().hex[:8]}", name_ar="ش", name_en="Char")
    session.add(character)
    session.flush()
    version = CharacterVersion(character_id=character.id, version_number="v01")
    session.add(version)
    session.flush()
    return version.id


def _real_scene_id(session: Session) -> uuid.UUID:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    scene = Scene(episode_id=episode.id, order_index=1)
    session.add(scene)
    session.flush()
    return scene.id


def _create(session: Session, jobs: GenerationJobService, **overrides):
    defaults = {
        "workflow_name": "character_reference_image",
        "provider_name": "mock_provider",
        "provider_model": None,
        "batch_id": uuid.uuid4(),
        "prompt_text": "a picture of a girl",
    }
    defaults.update(overrides)
    return jobs.create_job(session, **defaults)


def test_create_job_starts_pending(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    assert job.status == GenerationJobStatus.PENDING
    assert job.started_at is None
    assert job.completed_at is None


def test_create_job_stores_immutable_snapshot(session: Session) -> None:
    jobs = GenerationJobService()
    ref_id = uuid.uuid4()
    job = _create(
        session,
        jobs,
        prompt_text="rendered prompt text",
        negative_prompt_text="no cats",
        parameters={"size": "1024x1024"},
        reference_asset_ids=[ref_id],
    )
    assert job.prompt_text == "rendered prompt text"
    assert job.negative_prompt_text == "no cats"
    assert job.parameters == {"size": "1024x1024"}
    assert job.reference_asset_ids == [str(ref_id)]


def test_new_batch_id_is_unique() -> None:
    jobs = GenerationJobService()
    assert jobs.new_batch_id() != jobs.new_batch_id()


def test_mark_running_from_pending(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    updated = jobs.mark_running(session, job.id)
    assert updated.status == GenerationJobStatus.RUNNING
    assert updated.started_at is not None


def test_mark_running_rejects_non_pending(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    with pytest.raises(InvalidTransitionError):
        jobs.mark_running(session, job.id)


def test_mark_succeeded_from_running(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    asset_id = _real_asset_id(session)

    updated = jobs.mark_succeeded(session, job.id, result_asset_id=asset_id, cost_usd=Decimal("0.04"))

    assert updated.status == GenerationJobStatus.SUCCEEDED
    assert updated.result_asset_id == asset_id
    assert updated.cost_usd == Decimal("0.04")
    assert updated.completed_at is not None


def test_mark_succeeded_rejects_non_running(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)  # still pending
    with pytest.raises(InvalidTransitionError):
        jobs.mark_succeeded(session, job.id, result_asset_id=_real_asset_id(session))


def test_mark_succeeded_cost_usd_defaults_to_none(session: Session) -> None:
    """Never invented/estimated — NULL unless the caller passes an
    authoritative provider-reported figure."""
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    updated = jobs.mark_succeeded(session, job.id, result_asset_id=_real_asset_id(session))
    assert updated.cost_usd is None


def test_mark_failed_from_running(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)

    updated = jobs.mark_failed(
        session, job.id, error_category="ProviderTimeoutError", error_message="timed out"
    )

    assert updated.status == GenerationJobStatus.FAILED
    assert updated.error_category == "ProviderTimeoutError"
    assert updated.error_message == "timed out"
    assert updated.completed_at is not None


def test_mark_failed_rejects_non_running(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    with pytest.raises(InvalidTransitionError):
        jobs.mark_failed(session, job.id, error_category="X", error_message="x")


# --- honest cancellation ------------------------------------------------


def test_request_cancel_pending_job_cancels_immediately(session: Session) -> None:
    """No provider call was ever made, so PENDING -> CANCELLED is direct
    and immediate — nothing dishonest about it."""
    jobs = GenerationJobService()
    job = _create(session, jobs)

    updated = jobs.request_cancel(session, job.id)

    assert updated.status == GenerationJobStatus.CANCELLED
    assert updated.completed_at is not None
    assert "ever called" in updated.error_message


def test_request_cancel_running_job_moves_to_cancel_requested_not_cancelled(
    session: Session,
) -> None:
    """A running job's in-flight call can't be interrupted — cancelling it
    must not lie and claim CANCELLED while it might still be running."""
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)

    updated = jobs.request_cancel(session, job.id)

    assert updated.status == GenerationJobStatus.CANCEL_REQUESTED
    assert updated.completed_at is None  # still not terminal


def test_request_cancel_rejects_already_terminal_job(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    jobs.mark_succeeded(session, job.id, result_asset_id=_real_asset_id(session))

    with pytest.raises(InvalidTransitionError):
        jobs.request_cancel(session, job.id)


def test_finalize_cancelled_after_running_discards_successful_result(session: Session) -> None:
    """A result that arrives after cancellation was requested is recorded
    truthfully (result_asset_id still set — the asset genuinely exists)
    but the job stays CANCELLED, never silently promoted to SUCCEEDED."""
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    jobs.request_cancel(session, job.id)
    asset_id = _real_asset_id(session)

    updated = jobs.finalize_cancelled_after_running(
        session, job.id, provider_outcome="provider completed after cancellation", result_asset_id=asset_id
    )

    assert updated.status == GenerationJobStatus.CANCELLED
    assert updated.result_asset_id == asset_id
    assert updated.error_message == "provider completed after cancellation"
    assert updated.completed_at is not None


def test_finalize_cancelled_after_running_records_subsequent_failure_too(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)
    jobs.request_cancel(session, job.id)

    updated = jobs.finalize_cancelled_after_running(
        session, job.id, provider_outcome="provider call also failed: boom"
    )

    assert updated.status == GenerationJobStatus.CANCELLED
    assert updated.result_asset_id is None
    assert "also failed" in updated.error_message


def test_finalize_cancelled_after_running_rejects_non_cancel_requested(session: Session) -> None:
    jobs = GenerationJobService()
    job = _create(session, jobs)
    jobs.mark_running(session, job.id)  # never cancelled

    with pytest.raises(InvalidTransitionError):
        jobs.finalize_cancelled_after_running(session, job.id, provider_outcome="x")


# --- retry lineage --------------------------------------------------------


def test_retry_job_creates_new_pending_job_linked_to_original(session: Session) -> None:
    jobs = GenerationJobService()
    original = _create(session, jobs, prompt_text="original prompt")
    jobs.mark_running(session, original.id)
    jobs.mark_failed(session, original.id, error_category="X", error_message="boom")

    retry = jobs.retry_job(session, original.id)

    assert retry.id != original.id
    assert retry.status == GenerationJobStatus.PENDING
    assert retry.retry_of_job_id == original.id
    assert retry.prompt_text == "original prompt"
    assert retry.batch_id == original.batch_id


def test_retry_job_never_mutates_the_original(session: Session) -> None:
    jobs = GenerationJobService()
    original = _create(session, jobs)
    jobs.mark_running(session, original.id)
    jobs.mark_failed(session, original.id, error_category="X", error_message="boom")

    jobs.retry_job(session, original.id)

    refetched = jobs.get_job(session, original.id)
    assert refetched.status == GenerationJobStatus.FAILED
    assert refetched.error_category == "X"


def test_retry_job_preserves_reference_asset_ids(session: Session) -> None:
    jobs = GenerationJobService()
    ref_id = uuid.uuid4()
    original = _create(session, jobs, reference_asset_ids=[ref_id])
    retry = jobs.retry_job(session, original.id)
    assert retry.reference_asset_ids == [str(ref_id)]


# --- queries ---------------------------------------------------------------


def test_list_jobs_for_batch_returns_only_that_batch_in_order(session: Session) -> None:
    jobs = GenerationJobService()
    batch_id = uuid.uuid4()
    j1 = _create(session, jobs, batch_id=batch_id)
    j2 = _create(session, jobs, batch_id=batch_id)
    _create(session, jobs, batch_id=uuid.uuid4())  # different batch

    result = jobs.list_jobs_for_batch(session, batch_id)

    assert [j.id for j in result] == [j1.id, j2.id]


def test_list_jobs_filters_by_character_version_and_status(session: Session) -> None:
    jobs = GenerationJobService()
    version_id = _real_character_version_id(session)
    match = _create(session, jobs, character_version_id=version_id)
    jobs.mark_running(session, match.id)
    jobs.mark_succeeded(session, match.id, result_asset_id=_real_asset_id(session))
    _create(session, jobs, character_version_id=version_id)  # still pending
    _create(session, jobs, character_version_id=_real_character_version_id(session))  # different version

    result = jobs.list_jobs(
        session, character_version_id=version_id, status=GenerationJobStatus.SUCCEEDED
    )

    assert [j.id for j in result] == [match.id]


def test_list_jobs_filters_by_scene_id(session: Session) -> None:
    jobs = GenerationJobService()
    scene_id = _real_scene_id(session)
    match = _create(session, jobs, scene_id=scene_id, workflow_name="scene_image")
    _create(session, jobs, scene_id=_real_scene_id(session), workflow_name="scene_image")

    result = jobs.list_jobs(session, scene_id=scene_id)

    assert [j.id for j in result] == [match.id]


def test_get_job_not_found(session: Session) -> None:
    jobs = GenerationJobService()
    with pytest.raises(NotFoundError):
        jobs.get_job(session, uuid.uuid4())
