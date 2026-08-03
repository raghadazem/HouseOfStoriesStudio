"""Tests for AIOrchestrator: lookup, provider/workflow wiring, logging.

Uses fake provider/workflow doubles (not the real filesystem-touching
workflows) so these tests never depend on the process-wide
``app.config.get_config()`` cache — see ``tests/unit/test_ai_workflows.py``
for the real, filesystem-backed end-to-end workflow tests, and
``tests/integration/test_cli.py`` for a true full-stack run through a
fresh subprocess.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy.orm import Session

from app.core.ai.exceptions import ProviderNotConfiguredError, WorkflowError
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult
from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.db.enums import PromptCategory, PromptType
from app.core.services.exceptions import ValidationError
from app.core.services.prompt_template_service import PromptTemplateService


class _FakeConfiguredProvider(AIProvider):
    name = "fake_configured"
    supported_modalities = frozenset({"image"})
    generated_paths: ClassVar[list[Path]] = []

    def is_configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        path = Path(f"/tmp/fake_{uuid.uuid4().hex}.png")
        path.write_bytes(b"fake")
        _FakeConfiguredProvider.generated_paths.append(path)
        return GenerationResult(output_path=path, provider_name=self.name)


class _FakeUnconfiguredProvider(AIProvider):
    name = "fake_unconfigured"
    supported_modalities = frozenset({"image"})

    def is_configured(self) -> bool:
        return False

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise AssertionError("generate() must never be called on an unconfigured provider")


class _FakeAsset:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


class _FakeSucceedingWorkflow(Workflow):
    name = "fake_success"

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        request = GenerationRequest(modality="image", prompt_text="x")
        result = ctx.provider.generate(request)
        return WorkflowResult(
            asset=_FakeAsset(),  # type: ignore[arg-type]
            generation_request=request,
            generation_result=result,
        )


class _FakeFailingWorkflow(Workflow):
    name = "fake_failure"

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        raise RuntimeError("boom")


class _FakeFailingAfterGenerateWorkflow(Workflow):
    """Mimics AssetImportService raising (e.g. ConflictError) *after* a
    successful provider.generate() call — the exact failure shape that
    used to leak the provider's temp file (fixed by ``WorkflowContext
    .last_generation_result``)."""

    name = "fake_failure_after_generate"

    def run(self, ctx: WorkflowContext) -> WorkflowResult:
        request = GenerationRequest(modality="image", prompt_text="x")
        result = ctx.provider.generate(request)
        ctx.last_generation_result = result
        raise RuntimeError("simulated import failure")


def _prompt_template_id(session: Session) -> uuid.UUID:
    template = PromptTemplateService().create_prompt_template(
        session,
        name="fake_template",
        category=PromptCategory.IMAGE,
        prompt_type=PromptType.IMAGE,
        text_en="A picture.",
    )
    return template.id


def _orchestrator() -> AIOrchestrator:
    return AIOrchestrator(
        provider_registry={
            _FakeConfiguredProvider.name: _FakeConfiguredProvider,
            _FakeUnconfiguredProvider.name: _FakeUnconfiguredProvider,
        },
        workflow_registry={
            _FakeSucceedingWorkflow.name: _FakeSucceedingWorkflow,
            _FakeFailingWorkflow.name: _FakeFailingWorkflow,
            _FakeFailingAfterGenerateWorkflow.name: _FakeFailingAfterGenerateWorkflow,
        },
    )


def test_list_workflows(session: Session) -> None:
    assert _orchestrator().list_workflows() == [
        "fake_failure", "fake_failure_after_generate", "fake_success",
    ]


def test_list_available_providers_filters_by_modality_and_configured(session: Session) -> None:
    orchestrator = _orchestrator()
    assert orchestrator.list_available_providers("image") == ["fake_configured"]


def test_run_workflow_unknown_workflow_raises_validation_error(session: Session) -> None:
    with pytest.raises(ValidationError, match="Unknown workflow"):
        _orchestrator().run_workflow(
            session, "not_a_real_workflow", provider_name="fake_configured",
            prompt_template_id=_prompt_template_id(session),
        )


def test_run_workflow_unknown_provider_raises_validation_error(session: Session) -> None:
    with pytest.raises(ValidationError, match="Unknown provider"):
        _orchestrator().run_workflow(
            session, "fake_success", provider_name="not_a_real_provider",
            prompt_template_id=_prompt_template_id(session),
        )


def test_run_workflow_unconfigured_provider_raises(session: Session) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        _orchestrator().run_workflow(
            session, "fake_success", provider_name="fake_unconfigured",
            prompt_template_id=_prompt_template_id(session),
        )


def test_run_workflow_success_returns_result_and_logs(session: Session) -> None:
    logger = logging.getLogger("house_of_stories.ai_generation")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        result = _orchestrator().run_workflow(
            session, "fake_success", provider_name="fake_configured",
            prompt_template_id=_prompt_template_id(session),
        )
    finally:
        logger.removeHandler(handler)

    assert result.generation_result.provider_name == "fake_configured"
    assert len(records) == 1
    assert "generation_attempt" in records[0].getMessage()
    assert '"outcome": "success"' in records[0].getMessage()


def test_run_workflow_wraps_unexpected_exception_as_workflow_error(session: Session) -> None:
    with pytest.raises(WorkflowError):
        _orchestrator().run_workflow(
            session, "fake_failure", provider_name="fake_configured",
            prompt_template_id=_prompt_template_id(session),
        )


def test_run_workflow_cleans_up_temp_file_even_when_import_fails_after_generate(
    session: Session,
) -> None:
    """Regression test: a temp file must not leak when the provider succeeds
    but the workflow fails afterward (e.g. AssetImportService raising
    ConflictError on a duplicate) — caught via manual CLI testing."""
    _FakeConfiguredProvider.generated_paths.clear()

    with pytest.raises(WorkflowError):
        _orchestrator().run_workflow(
            session, "fake_failure_after_generate", provider_name="fake_configured",
            prompt_template_id=_prompt_template_id(session),
        )

    assert len(_FakeConfiguredProvider.generated_paths) == 1
    assert not _FakeConfiguredProvider.generated_paths[0].exists()
