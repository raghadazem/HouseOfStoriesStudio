"""Workflow ABC and the shared context/result types.

Fixed, code-defined workflow classes — not a generic config/DSL-driven
engine, per the founder's approved decision. Each workflow is one
explicit, typed, testable Python class named for the artifact it
produces. Adding a new one later is additive (one new file + one
registry entry in ``app.core.ai.orchestrator``), never a rewrite of
this base or of the service layer beneath it.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from sqlalchemy.orm import Session

from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult
from app.core.models import Asset


@dataclass
class WorkflowContext:
    """Everything one ``Workflow.run()`` call needs.

    Not every field is used by every workflow — each workflow validates
    which of ``episode_id``/``scene_id``/``character_version_id`` (etc.)
    it actually requires and raises :class:`~app.core.services.exceptions.ValidationError`
    if a required one is missing.
    """

    session: Session
    provider: AIProvider
    # Optional (Milestone 8): a workflow that renders its own prompt
    # directly from already-authored text (see ``rendered_prompt_text``
    # below) never needs a ``PromptTemplate`` row at all. Every
    # template-based workflow (``CharacterReferenceWorkflow`` and
    # friends) still requires a real id at its own call site — this
    # field only becomes optional so a caller with nothing to put here
    # doesn't have to invent one.
    prompt_template_id: uuid.UUID | None = None
    variables: dict[str, object] = field(default_factory=dict)
    parameters: dict[str, object] = field(default_factory=dict)
    episode_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None = None
    short_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    character_version_id: uuid.UUID | None = None
    notes: str | None = None
    # The direct-prompt path (Milestone 8): already-final text a
    # workflow sends to the provider verbatim, bypassing PromptEngine/
    # PromptTemplate entirely. Set together — a workflow that supports
    # this path (SceneImageWorkflow) checks ``rendered_prompt_text is
    # not None`` to choose it over the legacy template path; every
    # other workflow never reads these fields at all.
    rendered_prompt_text: str | None = None
    rendered_negative_prompt_text: str | None = None
    rendered_reference_asset_paths: list[str] = field(default_factory=list)
    # Set by a Workflow immediately after a successful provider.generate()
    # call, *before* AssetImportService.import_asset() runs — so the
    # orchestrator can still find (and clean up) the provider's temp
    # output file even if import_asset then fails partway through (e.g.
    # ConflictError on a duplicate). Not meant to be set by callers.
    last_generation_result: GenerationResult | None = field(default=None, init=False)


@dataclass(frozen=True)
class WorkflowResult:
    """What a completed workflow run produced."""

    asset: Asset
    generation_request: GenerationRequest
    generation_result: GenerationResult


class Workflow(ABC):
    """One generation task: prompt -> provider -> imported ``Asset``."""

    name: ClassVar[str]

    @abstractmethod
    def run(self, ctx: WorkflowContext) -> WorkflowResult: ...
