"""Provider registry: provider name -> provider class.

Per the founder's approved scope for Milestone 3.5, only the interface
and a fully-working ``MockProvider`` were built first — no structural
stub files for every future vendor. Adding a real provider means:
write one new file implementing :class:`AIProvider`, add one entry
here. Nothing above this registry (workflows, the orchestrator, the
GUI) changes — confirmed true again in Milestone 7, which adds
``GeminiProvider`` this exact way.
"""

from __future__ import annotations

from app.core.ai.provider_interface import AIProvider
from app.core.ai.providers.gemini_provider import GeminiProvider
from app.core.ai.providers.mock_provider import MockProvider

PROVIDER_REGISTRY: dict[str, type[AIProvider]] = {
    MockProvider.name: MockProvider,
    GeminiProvider.name: GeminiProvider,
}

__all__ = ["PROVIDER_REGISTRY", "GeminiProvider", "MockProvider"]
