"""AIOrchestrator — the one entry point the GUI (and the CLI) call.

Wires together the provider registry, the workflow registry, and
generation logging. Never touches the filesystem or database itself —
every actual side effect happens inside ``AssetImportService`` via the
chosen ``Workflow``. ``app/gui`` (Milestone 4) will only ever import
this class and read-only query helpers — never a provider or workflow
class directly.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.ai.exceptions import ProviderNotConfiguredError, WorkflowError
from app.core.ai.generation_logger import GenerationLogEntry, log_generation_attempt
from app.core.ai.provider_interface import AIProvider, Modality
from app.core.ai.providers import PROVIDER_REGISTRY
from app.core.ai.workflows import (
    CharacterReferenceWorkflow,
    SceneImageWorkflow,
    ThumbnailWorkflow,
    VoiceLineWorkflow,
    Workflow,
    WorkflowContext,
    WorkflowResult,
)
from app.core.models import PromptTemplate
from app.core.services.exceptions import ServiceError, ValidationError

WORKFLOW_REGISTRY: dict[str, type[Workflow]] = {
    CharacterReferenceWorkflow.name: CharacterReferenceWorkflow,
    SceneImageWorkflow.name: SceneImageWorkflow,
    VoiceLineWorkflow.name: VoiceLineWorkflow,
    ThumbnailWorkflow.name: ThumbnailWorkflow,
}


class AIOrchestrator:
    """Looks up a workflow and a provider, runs the workflow, logs the attempt."""

    def __init__(
        self,
        provider_registry: dict[str, type[AIProvider]] | None = None,
        workflow_registry: dict[str, type[Workflow]] | None = None,
    ) -> None:
        self._provider_registry = provider_registry or PROVIDER_REGISTRY
        self._workflow_registry = workflow_registry or WORKFLOW_REGISTRY
        self._provider_instances: dict[str, AIProvider] = {}

    def list_workflows(self) -> list[str]:
        return sorted(self._workflow_registry)

    def list_available_providers(self, modality: Modality) -> list[str]:
        """Providers that both support this modality and report ``is_configured()``."""
        available = []
        for provider_name in self._provider_registry:
            provider = self._get_provider(provider_name)
            if modality in provider.supported_modalities and provider.is_configured():
                available.append(provider_name)
        return sorted(available)

    def run_workflow(
        self,
        session: Session,
        workflow_name: str,
        *,
        provider_name: str,
        prompt_template_id: uuid.UUID,
        variables: dict[str, object] | None = None,
        parameters: dict[str, object] | None = None,
        episode_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
        short_id: uuid.UUID | None = None,
        character_id: uuid.UUID | None = None,
        character_version_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> WorkflowResult:
        """Look up the workflow and provider, build a context, run it, log the attempt.

        Raises:
            ValidationError: Unknown ``workflow_name``/``provider_name``.
            ProviderNotConfiguredError: The provider exists but isn't
                configured (every real, non-mock provider today — none
                are built yet, see ``docs/18``).
            ServiceError: Any domain error the workflow itself raised
                (propagated unchanged, e.g. ``ValidationError``,
                ``NotFoundError``, ``TemplateRenderError``).
            WorkflowError: Any other failure during the run.
        """
        workflow = self._get_workflow(workflow_name)
        provider = self._get_provider_or_raise(provider_name)

        ctx = WorkflowContext(
            session=session,
            provider=provider,
            prompt_template_id=prompt_template_id,
            variables=dict(variables or {}),
            parameters=dict(parameters or {}),
            episode_id=episode_id,
            scene_id=scene_id,
            short_id=short_id,
            character_id=character_id,
            character_version_id=character_version_id,
            notes=notes,
        )

        request_id = uuid.uuid4()
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        outcome = "failure"
        error_category: str | None = None
        imported_asset_id: uuid.UUID | None = None
        temp_output_path = None

        try:
            if not provider.is_configured():
                raise ProviderNotConfiguredError(
                    f"Provider {provider_name!r} is not configured."
                )
            result = workflow.run(ctx)
            imported_asset_id = result.asset.id
            outcome = "success"
            return result
        except ServiceError as err:
            error_category = type(err).__name__
            raise
        except Exception as err:
            error_category = type(err).__name__
            raise WorkflowError(f"Workflow {workflow_name!r} failed: {err}") from err
        finally:
            # Read from ctx, not from a successful `result` — a workflow
            # sets this right after provider.generate() succeeds, before
            # AssetImportService.import_asset() runs, so the provider's
            # temp file is still found (and cleaned up) here even when
            # import_asset fails partway through (e.g. ConflictError on
            # a duplicate) and the workflow never returns normally.
            if ctx.last_generation_result is not None:
                temp_output_path = ctx.last_generation_result.output_path
            ended_at = datetime.now(UTC)
            duration_seconds = time.monotonic() - started_monotonic
            log_generation_attempt(
                GenerationLogEntry(
                    request_id=request_id,
                    workflow_name=workflow_name,
                    provider_name=provider_name,
                    prompt_template_id=prompt_template_id,
                    prompt_template_version=self._template_version(session, prompt_template_id),
                    outcome=outcome,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_seconds=duration_seconds,
                    episode_id=episode_id,
                    scene_id=scene_id,
                    short_id=short_id,
                    character_id=character_id,
                    character_version_id=character_version_id,
                    error_category=error_category,
                    temp_file_name=temp_output_path.name if temp_output_path else None,
                    imported_asset_id=imported_asset_id,
                )
            )
            self._cleanup_temp_file(temp_output_path)

    @staticmethod
    def _template_version(session: Session, prompt_template_id: uuid.UUID) -> str | None:
        template = session.get(PromptTemplate, prompt_template_id)
        return template.version if template is not None else None

    @staticmethod
    def _cleanup_temp_file(temp_path) -> None:
        """Delete the provider's disposable temp output file, if any.

        Unlike a manually imported asset's source file (the founder's
        own download, always left untouched), a provider's temp output
        is ephemeral scratch data with no other purpose once
        ``AssetImportService`` has copied its bytes into managed
        storage — nothing else ever needs it again.
        """
        if temp_path is None:
            return
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _get_workflow(self, workflow_name: str) -> Workflow:
        cls = self._workflow_registry.get(workflow_name)
        if cls is None:
            raise ValidationError(
                f"Unknown workflow {workflow_name!r}. Available: {sorted(self._workflow_registry)}"
            )
        return cls()

    def _get_provider_or_raise(self, provider_name: str) -> AIProvider:
        if provider_name not in self._provider_registry:
            raise ValidationError(
                f"Unknown provider {provider_name!r}. Available: {sorted(self._provider_registry)}"
            )
        return self._get_provider(provider_name)

    def _get_provider(self, provider_name: str) -> AIProvider:
        if provider_name not in self._provider_instances:
            self._provider_instances[provider_name] = self._provider_registry[provider_name]()
        return self._provider_instances[provider_name]
