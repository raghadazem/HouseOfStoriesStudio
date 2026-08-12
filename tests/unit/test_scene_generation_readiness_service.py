"""Tests for SceneGenerationReadinessService: actionable, per-scene generation blockers."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.provider_interface import (
    AIProvider,
    GenerationRequest,
    GenerationResult,
    ProviderCapabilities,
)
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode, Scene
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.exceptions import NotFoundError
from app.core.services.reference_selection_service import ReferenceSelectionService
from app.core.services.scene_generation_readiness_service import SceneGenerationReadinessService

_LOCK_FIELDS = {
    "visual_summary": "Two ponytails, denim dress.",
    "master_prompt": "Melissa: 6yo girl...",
    "negative_prompt": "no extra characters",
    "color_palette": ["denim blue", "red"],
    "relative_height": "taller than Bilsan",
}


class _CapacityLimitedProvider(AIProvider):
    """A fake provider with a tiny character-reference capacity, so the
    capacity-exceeded branch can be tested without needing 5 real
    characters."""

    name = "capacity_limited"
    supported_modalities = frozenset({"image"})
    capabilities = ProviderCapabilities(max_character_references=1)

    def is_configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:  # pragma: no cover
        raise NotImplementedError


def _orchestrator() -> AIOrchestrator:
    return AIOrchestrator()


def _ready_character(
    session: Session, cvs: CharacterVersionService, slug: str, name_en: str
) -> Character:
    character = Character(slug=slug, name_ar=slug, name_en=name_en)
    session.add(character)
    session.flush()
    version = cvs.create_character_version(session, character.id, **_LOCK_FIELDS)
    asset = Asset(
        asset_type=AssetType.IMAGE,
        original_filename="ref.png",
        relative_path=f"characters/{slug}/versions/{version.id}/ref.png",
        checksum=uuid.uuid4().hex.ljust(64, "0"),
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(asset)
    session.flush()
    reference = cvs.add_character_reference(
        session, character_id=character.id, character_version_id=version.id, asset_id=asset.id
    )
    cvs.set_canon_reference(session, reference.id)
    cvs.submit_character_version_for_review(session, version.id)
    cvs.approve_character_version(session, version.id, decided_by="founder")
    cvs.set_active_character_version(session, character.id, version.id)
    return character


def _scene(session: Session, characters: list[Character], **overrides) -> Scene:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    defaults = {"episode_id": episode.id, "order_index": 1, "prompt_text": "A quiet forest."}
    defaults.update(overrides)
    scene = Scene(**defaults)
    scene.characters_present = characters
    session.add(scene)
    session.flush()
    return scene


def test_evaluate_raises_not_found_for_unknown_scene(session: Session) -> None:
    service = SceneGenerationReadinessService()
    with pytest.raises(NotFoundError):
        service.evaluate(
            session, uuid.uuid4(), provider_name="mock_provider", orchestrator=_orchestrator()
        )


def test_evaluate_is_ready_for_fully_prepared_scene(session: Session) -> None:
    cvs = CharacterVersionService()
    melissa = _ready_character(session, cvs, "melissa", "Melissa")
    bilsan = _ready_character(session, cvs, "bilsan", "Bilsan")
    scene = _scene(session, [melissa, bilsan])
    service = SceneGenerationReadinessService(references=ReferenceSelectionService(cvs))

    report = service.evaluate(
        session, scene.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert report.is_ready, report.blocking_messages


def test_evaluate_blocks_on_missing_prompt(session: Session) -> None:
    scene = _scene(session, [], prompt_text=None)
    service = SceneGenerationReadinessService()

    report = service.evaluate(
        session, scene.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("no composed prompt" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_and_names_character_missing_canon_reference(session: Session) -> None:
    cvs = CharacterVersionService()
    character = Character(slug="melissa", name_ar="م", name_en="Melissa")
    session.add(character)
    session.flush()
    scene = _scene(session, [character])
    service = SceneGenerationReadinessService(references=ReferenceSelectionService(cvs))

    report = service.evaluate(
        session, scene.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("Melissa" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_when_provider_not_configured(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hermetic regardless of the real machine's ambient environment (a
    # real GEMINI_API_KEY may legitimately be configured there) — see
    # tests/gui/test_dashboard.py's dashboard fixture for the same
    # pattern established after Milestone 7's real-key smoke test.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    scene = _scene(session, [])
    service = SceneGenerationReadinessService()

    report = service.evaluate(
        session, scene.id, provider_name="gemini", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("gemini" in msg and "not configured" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_when_over_reference_capacity(session: Session) -> None:
    cvs = CharacterVersionService()
    melissa = _ready_character(session, cvs, "melissa", "Melissa")
    bilsan = _ready_character(session, cvs, "bilsan", "Bilsan")
    scene = _scene(session, [melissa, bilsan])
    orchestrator = AIOrchestrator(
        provider_registry={"capacity_limited": _CapacityLimitedProvider}
    )
    service = SceneGenerationReadinessService(references=ReferenceSelectionService(cvs))

    report = service.evaluate(
        session, scene.id, provider_name="capacity_limited", orchestrator=orchestrator
    )

    assert not report.is_ready
    assert any("supports at most 1" in msg for msg in report.blocking_messages)


def test_evaluate_blocks_when_a_job_is_already_in_flight(session: Session) -> None:
    scene = _scene(session, [])
    jobs = GenerationJobService()
    jobs.create_job(
        session,
        workflow_name="scene_image",
        provider_name="mock_provider",
        provider_model=None,
        batch_id=uuid.uuid4(),
        prompt_text="x",
        scene_id=scene.id,
    )
    service = SceneGenerationReadinessService(generation_jobs=jobs)

    report = service.evaluate(
        session, scene.id, provider_name="mock_provider", orchestrator=_orchestrator()
    )

    assert not report.is_ready
    assert any("already pending/running" in msg for msg in report.blocking_messages)
