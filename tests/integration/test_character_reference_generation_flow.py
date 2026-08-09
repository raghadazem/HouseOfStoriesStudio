"""Integration test: the full Milestone 7 vertical slice.

Character -> CharacterVersion -> real generation (MockProvider stands
in for Gemini, per "no automated test may call the real API") ->
persistent GenerationJob -> candidate Asset (draft) -> human review ->
approved CharacterReference -> approved/active CharacterVersion.

Exercises every service together against the real service layer, the
same way ``tests/integration/test_production_checklist_service.py``
does for the episode-readiness checklist.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.generation_runner import CandidateBatchRequest, run_character_reference_batch
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.db.enums import (
    ApprovalDecision,
    ApprovalStatus,
    CharacterVersionStatus,
    GenerationJobStatus,
    PromptCategory,
    PromptType,
)
from app.core.services.approval_service import ApprovalService
from app.core.services.asset_import_service import AssetImportService
from app.core.services.character_service import CharacterService
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.prompt_template_service import PromptTemplateService
from app.core.services.storage_service import StorageService


def _workflow_registry_for(app_config: AppConfig):
    asset_import = AssetImportService(app_config, StorageService(app_config))

    class _BoundCharacterReferenceWorkflow(CharacterReferenceWorkflow):
        def __init__(self) -> None:
            super().__init__(asset_import=asset_import)

    return {CharacterReferenceWorkflow.name: _BoundCharacterReferenceWorkflow}


def test_character_reference_generation_full_vertical_slice(
    session: Session, app_config: AppConfig
) -> None:
    characters = CharacterService()
    versions = CharacterVersionService()
    approvals = ApprovalService()
    generation_jobs = GenerationJobService()
    templates = PromptTemplateService()
    orchestrator = AIOrchestrator(workflow_registry=_workflow_registry_for(app_config))

    # 1. Character + CharacterVersion, authored but not yet locked.
    melissa = characters.create_character(session, slug="melissa", name_ar="ميليسا", name_en="Melissa")
    version = versions.create_character_version(
        session,
        melissa.id,
        visual_summary="Two ponytails, denim dress.",
        master_prompt="Melissa: a cheerful 6-year-old girl with two ponytails.",
        negative_prompt="no extra characters, no text overlays",
        color_palette=["denim blue", "sunshine yellow"],
        relative_height="taller than Bilsan",
    )

    # A version can't reach production without an approved reference —
    # and it has none yet: this is exactly the gap real generation exists
    # to fill.
    lock_before = versions.validate_character_lock(session, version.id)
    assert lock_before.is_complete is False
    assert lock_before.missing_fields == ["approved_reference_assets"]

    # But prompt-relevant fields ARE already complete, so real generation
    # is allowed to run against this still-draft version.
    prompt_readiness = versions.validate_prompt_completeness(session, version.id)
    assert prompt_readiness.is_complete is True

    template = templates.create_prompt_template(
        session,
        name="melissa_reference",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="A children's-book illustration of {{ character_master_prompt }}.",
    )

    # 2. Real (here: MockProvider-backed) generation, tracked end to end
    # by persistent GenerationJob provenance.
    request = CandidateBatchRequest(
        provider_name="mock_provider",
        prompt_template_id=template.id,
        character_version_id=version.id,
        character_id=melissa.id,
        candidate_count=2,
    )
    jobs = run_character_reference_batch(
        session, request, orchestrator=orchestrator, generation_jobs=generation_jobs
    )

    assert len(jobs) == 2
    assert len({job.batch_id for job in jobs}) == 1
    assert all(job.status == GenerationJobStatus.SUCCEEDED for job in jobs)
    assert all(job.provider_name == "mock_provider" for job in jobs)
    assert all(job.character_version_id == version.id for job in jobs)
    # Immutable provenance: the rendered prompt is snapshotted onto the
    # job, not left to be re-derived later from a template that could
    # change.
    assert "Melissa" in jobs[0].prompt_text

    # 3. Candidates land as ordinary draft assets, requiring human review.
    candidate_asset_ids = [job.result_asset_id for job in jobs]
    pending = approvals.list_pending_review_assets(session, character_version_id=version.id)
    assert {a.id for a in pending} == set(candidate_asset_ids)
    assert all(a.approval_status == ApprovalStatus.DRAFT for a in pending)
    assert all(a.generation_job_id in {job.id for job in jobs} for a in pending)

    # 4. Human approves one candidate, rejects the other.
    chosen_asset_id, rejected_asset_id = candidate_asset_ids
    approvals.decide_asset_review(
        session, chosen_asset_id, ApprovalDecision.APPROVED, decided_by="founder"
    )
    approvals.decide_asset_review(
        session, rejected_asset_id, ApprovalDecision.REJECTED, decided_by="founder", notes="off-model"
    )

    # 5. Approved candidate becomes canon reference art — still an
    # explicit, separate human action, never automatic.
    reference = versions.add_character_reference(
        session, character_id=melissa.id, character_version_id=version.id, asset_id=chosen_asset_id
    )
    assert reference.asset_id == chosen_asset_id

    # 6. Character Lock is now complete -> version can be approved -> active.
    lock_after = versions.validate_character_lock(session, version.id)
    assert lock_after.is_complete is True

    versions.submit_character_version_for_review(session, version.id)
    versions.approve_character_version(session, version.id, decided_by="founder")
    versions.set_active_character_version(session, melissa.id, version.id)

    assert version.status == CharacterVersionStatus.APPROVED_CANON
    assert melissa.active_version_id == version.id
