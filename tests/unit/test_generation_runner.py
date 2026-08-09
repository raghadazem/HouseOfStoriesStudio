"""Tests for generation_runner: batch grouping, honest cancellation, policy gates.

Exercises the real ``CharacterReferenceWorkflow`` + ``MockProvider`` +
real ``AssetImportService``/``GenerationJobService`` together (like
``tests/unit/test_ai_workflows.py``) rather than fakes, since the whole
point of this module is proving the lifecycle wiring works end to end.
A workflow registry bound to the test's isolated ``app_config`` is
used instead of ``AIOrchestrator``'s default registry, for the same
reason ``test_ai_workflows.py`` builds its own ``AssetImportService``:
the real ``AssetImportService()`` no-arg default reads the process-wide
cached ``AppConfig``, which must never be touched by tests.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.ai.exceptions import ProviderNotConfiguredError, ProviderRequestError
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.generation_runner import (
    CandidateBatchRequest,
    render_preview,
    run_character_reference_batch,
)
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult
from app.core.ai.providers.mock_provider import MockProvider
from app.core.ai.workflows.base import Workflow
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.db.enums import GenerationJobStatus, PromptCategory, PromptType
from app.core.models import Asset, Character, CharacterVersion, PromptTemplate
from app.core.services.asset_import_service import AssetImportService
from app.core.services.exceptions import CharacterLockIncompleteError, ValidationError
from app.core.services.prompt_template_service import PromptTemplateService
from app.core.services.storage_service import StorageService


def _character_version(session: Session, **overrides: object) -> CharacterVersion:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    defaults: dict[str, object] = {
        "character_id": character.id,
        "version_number": "v01",
        "master_prompt": "a young girl with two ponytails",
        "visual_summary": "Two ponytails, denim dress.",
        "negative_prompt": "no extra characters",
        "color_palette": ["#ffcc00"],
        "relative_height": "taller than Bilsan",
    }
    defaults.update(overrides)
    version = CharacterVersion(**defaults)
    session.add(version)
    session.flush()
    return version


def _template(session: Session) -> PromptTemplate:
    return PromptTemplateService().create_prompt_template(
        session,
        name="char_ref",
        category=PromptCategory.CHARACTER,
        prompt_type=PromptType.IMAGE,
        text_en="A picture of {{ character_master_prompt }}.",
    )


def _workflow_registry_for(app_config: AppConfig) -> dict[str, type[Workflow]]:
    """A workflow registry whose CharacterReferenceWorkflow is bound to
    the test's isolated AssetImportService, since AIOrchestrator always
    zero-arg constructs from the registry (see module docstring)."""
    asset_import = AssetImportService(app_config, StorageService(app_config))

    class _BoundCharacterReferenceWorkflow(CharacterReferenceWorkflow):
        def __init__(self) -> None:
            super().__init__(asset_import=asset_import)

    return {CharacterReferenceWorkflow.name: _BoundCharacterReferenceWorkflow}


def _orchestrator(app_config: AppConfig, provider_registry=None) -> AIOrchestrator:
    return AIOrchestrator(
        provider_registry=provider_registry,
        workflow_registry=_workflow_registry_for(app_config),
    )


def _request(session: Session, *, provider_name: str = "mock_provider", **overrides) -> CandidateBatchRequest:
    version = overrides.pop("version", None) or _character_version(session)
    template = overrides.pop("template", None) or _template(session)
    defaults = {
        "provider_name": provider_name,
        "prompt_template_id": template.id,
        "character_version_id": version.id,
    }
    defaults.update(overrides)
    return CandidateBatchRequest(**defaults)


# --- render_preview --------------------------------------------------------


def test_render_preview_matches_what_the_batch_would_send(session: Session) -> None:
    version = _character_version(session)
    template = _template(session)
    request = _request(session, version=version, template=template)

    rendered = render_preview(session, request)

    assert "a young girl with two ponytails" in rendered.prompt_text
    assert rendered.modality == "image"


# --- fail-fast pre-checks ---------------------------------------------------


def test_run_batch_rejects_out_of_range_candidate_count(session: Session, app_config: AppConfig) -> None:
    request = _request(session, candidate_count=5)
    with pytest.raises(ValidationError):
        run_character_reference_batch(
            session, request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
        )


def test_run_batch_rejects_incomplete_character_lock_before_creating_any_job(
    session: Session, app_config: AppConfig
) -> None:
    version = _character_version(session, visual_summary=None)
    request = _request(session, version=version)
    jobs = GenerationJobService()

    with pytest.raises(CharacterLockIncompleteError):
        run_character_reference_batch(
            session, request, orchestrator=_orchestrator(app_config), generation_jobs=jobs
        )

    assert jobs.list_jobs(session) == []


def test_run_batch_rejects_unconfigured_provider_before_creating_any_job(
    session: Session, app_config: AppConfig
) -> None:
    class _UnconfiguredProvider(AIProvider):
        name = "unconfigured"
        supported_modalities = frozenset({"image"})

        def is_configured(self) -> bool:
            return False

        def generate(self, request: GenerationRequest) -> GenerationResult:
            raise AssertionError("must never be called")

    request = _request(session, provider_name="unconfigured")
    jobs = GenerationJobService()
    orchestrator = _orchestrator(app_config, provider_registry={"unconfigured": _UnconfiguredProvider})

    with pytest.raises(ProviderNotConfiguredError):
        run_character_reference_batch(session, request, orchestrator=orchestrator, generation_jobs=jobs)

    assert jobs.list_jobs(session) == []


# --- success + batching -----------------------------------------------------


def test_run_batch_creates_one_job_per_candidate_sharing_a_batch_id(
    session: Session, app_config: AppConfig
) -> None:
    request = _request(session, candidate_count=3)
    jobs = GenerationJobService()
    updates: list[GenerationJobStatus] = []

    result = run_character_reference_batch(
        session,
        request,
        orchestrator=_orchestrator(app_config),
        generation_jobs=jobs,
        on_job_update=lambda job: updates.append(job.status),
    )

    assert len(result) == 3
    assert len({job.batch_id for job in result}) == 1
    assert all(job.status == GenerationJobStatus.SUCCEEDED for job in result)
    assert len({job.result_asset_id for job in result}) == 3  # 3 distinct assets
    # every job passed through pending -> running -> succeeded
    assert updates.count(GenerationJobStatus.RUNNING) == 3
    assert updates.count(GenerationJobStatus.SUCCEEDED) == 3


def test_run_batch_sets_asset_generation_job_id(session: Session, app_config: AppConfig) -> None:
    request = _request(session, candidate_count=1)
    jobs = GenerationJobService()

    result = run_character_reference_batch(
        session, request, orchestrator=_orchestrator(app_config), generation_jobs=jobs
    )

    job = result[0]
    asset = session.get(Asset, job.result_asset_id)
    assert asset.generation_job_id == job.id


def test_run_batch_stores_provider_model_when_provider_has_one(
    session: Session, app_config: AppConfig
) -> None:
    class _ModelledProvider(MockProvider):
        name = "modelled"

        @property
        def model(self) -> str:
            return "fake-model-v1"

    request = _request(session, provider_name="modelled")
    jobs = GenerationJobService()
    orchestrator = _orchestrator(app_config, provider_registry={"modelled": _ModelledProvider})

    result = run_character_reference_batch(
        session, request, orchestrator=orchestrator, generation_jobs=jobs
    )

    assert result[0].provider_model == "fake-model-v1"


def test_run_batch_threads_retry_of_job_id_onto_the_new_job(
    session: Session, app_config: AppConfig
) -> None:
    version = _character_version(session)
    template = _template(session)
    base_request = _request(session, version=version, template=template, candidate_count=1)
    original = run_character_reference_batch(
        session, base_request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
    )[0]

    retry_request = _request(
        session, version=version, template=template, candidate_count=1, retry_of_job_id=original.id
    )
    retried = run_character_reference_batch(
        session, retry_request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
    )[0]

    assert retried.retry_of_job_id == original.id
    assert retried.id != original.id
    assert retried.batch_id == original.batch_id  # stays grouped for the candidate grid


def test_run_batch_provider_model_is_none_for_mock_provider(
    session: Session, app_config: AppConfig
) -> None:
    request = _request(session, candidate_count=1)
    result = run_character_reference_batch(
        session, request, orchestrator=_orchestrator(app_config), generation_jobs=GenerationJobService()
    )
    assert result[0].provider_model is None


# --- provider failure --------------------------------------------------


def test_run_batch_marks_job_failed_when_provider_raises(
    session: Session, app_config: AppConfig
) -> None:
    class _FailingProvider(AIProvider):
        name = "failing"
        supported_modalities = frozenset({"image"})

        def is_configured(self) -> bool:
            return True

        def generate(self, request: GenerationRequest) -> GenerationResult:
            raise ProviderRequestError("simulated provider failure")

    request = _request(session, provider_name="failing", candidate_count=2)
    jobs = GenerationJobService()
    orchestrator = _orchestrator(app_config, provider_registry={"failing": _FailingProvider})

    result = run_character_reference_batch(
        session, request, orchestrator=orchestrator, generation_jobs=jobs
    )

    assert len(result) == 2
    assert all(job.status == GenerationJobStatus.FAILED for job in result)
    assert all(job.error_category == "ProviderRequestError" for job in result)
    assert all("simulated provider failure" in job.error_message for job in result)


# --- honest cancellation -----------------------------------------------


def test_run_batch_skips_job_already_cancelled_while_queued(
    session: Session, app_config: AppConfig
) -> None:
    """Simulates another actor (e.g. the GUI's Cancel button, from a
    different thread/session) cancelling a not-yet-started job before
    its turn comes up in the batch loop."""
    request = _request(session, candidate_count=3)
    jobs = GenerationJobService()
    seen_pending: list[uuid.UUID] = []

    def _on_update(job):
        if job.status == GenerationJobStatus.PENDING and job.id not in seen_pending:
            seen_pending.append(job.id)
            if len(seen_pending) == 2:
                # Cancel the second job the moment it's created, before
                # the batch loop gets to it.
                jobs.request_cancel(session, job.id)

    result = run_character_reference_batch(
        session,
        request,
        orchestrator=_orchestrator(app_config),
        generation_jobs=jobs,
        on_job_update=_on_update,
    )

    statuses = [job.status for job in result]
    assert statuses == [
        GenerationJobStatus.SUCCEEDED,
        GenerationJobStatus.CANCELLED,
        GenerationJobStatus.SUCCEEDED,
    ]
    assert result[1].result_asset_id is None
    assert "ever called" in result[1].error_message


def test_run_batch_discards_result_when_cancelled_while_generating(
    session: Session, app_config: AppConfig
) -> None:
    """Cancellation requested while a job's blocking provider call is in
    flight: the provider still finishes and an asset is genuinely
    created, but the job must end CANCELLED, not SUCCEEDED — see
    GenerationJobService's "honest cancellation" docstring."""
    jobs = GenerationJobService()
    running_job_ids: list[uuid.UUID] = []

    def _on_update(job):
        if job.status == GenerationJobStatus.RUNNING:
            running_job_ids.append(job.id)

    class _CancelMidFlightProvider(MockProvider):
        name = "cancel_mid_flight"

        def generate(self, request: GenerationRequest) -> GenerationResult:
            # Simulate another thread cancelling this exact job while
            # this (synchronous, in-flight) call is still running.
            jobs.request_cancel(session, running_job_ids[-1])
            return super().generate(request)

    request = _request(session, provider_name="cancel_mid_flight", candidate_count=1)
    orchestrator = _orchestrator(
        app_config, provider_registry={"cancel_mid_flight": _CancelMidFlightProvider}
    )

    result = run_character_reference_batch(
        session, request, orchestrator=orchestrator, generation_jobs=jobs, on_job_update=_on_update
    )

    job = result[0]
    assert job.status == GenerationJobStatus.CANCELLED
    assert job.result_asset_id is not None  # the asset genuinely exists
    assert "cancellation was requested" in job.error_message
    # And it must never appear as a normal successful candidate.
    assert jobs.list_jobs(session, status=GenerationJobStatus.SUCCEEDED) == []
