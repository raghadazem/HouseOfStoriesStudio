"""The ``AIProvider`` interface: every future AI vendor implements this.

Nothing above this line (workflows, the orchestrator, the future GUI)
is ever allowed to import a provider SDK or know which vendor is in
use — it only ever talks to this interface. See
``docs/18_AI_ARCHITECTURE_PLAN.md`` §5.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Literal

Modality = Literal["text", "image", "video", "voice", "song"]


@dataclass(frozen=True)
class GenerationRequest:
    """Everything a provider needs to attempt one generation.

    ``prompt_text`` arrives already rendered (built by
    :class:`~app.core.ai.prompt_engine.PromptEngine`) — a provider never
    sees a template or template variables, only final text.
    """

    modality: Modality
    prompt_text: str
    negative_prompt_text: str | None = None
    # Managed-relative paths (e.g. character lock reference images), not
    # absolute filesystem paths — kept portable the same way
    # ``Asset.relative_path`` is.
    reference_asset_paths: list[str] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    """What a provider hands back: a local file, ready for ``AssetImportService``."""

    output_path: Path
    provider_name: str
    # Short and loggable — never the full raw provider payload (which
    # could contain anything, including data this project must never
    # log verbatim).
    raw_response_summary: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider's underlying model documents it can accept.

    Deliberately minimal — only the one field Milestone 8 actually
    needs (how many character-consistency reference images a scene
    generation request may include). Object/style reference capacity
    are real, separately-documented Gemini limits, but nothing in this
    codebase sends those categories yet, so no field exists for them —
    adding one later, if a workflow actually needs it, is a pure
    additive change to this dataclass, not a redesign.

    Read only by ``ReferenceSelectionService``/
    ``SceneGenerationReadinessService`` — never hardcoded into the GUI
    or any domain model, so a provider/model capacity change is a
    one-line edit in that provider's own file.
    """

    max_character_references: int | None = None  # None = no known/enforced limit


class AIProvider(ABC):
    """Interface every AI provider (mock or real) must implement.

    ``is_configured()`` lets a caller check availability before calling
    ``generate()`` — a provider with no API key configured should
    report ``False`` rather than let ``generate()`` raise partway
    through.
    """

    name: ClassVar[str]
    supported_modalities: ClassVar[frozenset[str]]
    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities()

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def supports(self, modality: Modality) -> bool:
        return modality in self.supported_modalities
