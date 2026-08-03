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


class AIProvider(ABC):
    """Interface every AI provider (mock or real) must implement.

    ``is_configured()`` lets a caller check availability before calling
    ``generate()`` — a provider with no API key configured should
    report ``False`` rather than let ``generate()`` raise partway
    through.
    """

    name: ClassVar[str]
    supported_modalities: ClassVar[frozenset[str]]

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def supports(self, modality: Modality) -> bool:
        return modality in self.supported_modalities
