"""Provider registry: provider name -> provider class.

Per the founder's approved scope for Milestone 3.5, only the interface
and a fully-working ``MockProvider`` are built now — no structural stub
files for OpenAI/Claude/Gemini/Suno/Google TTS. Adding a real provider
later means: write one new file implementing :class:`AIProvider`, add
one entry here. Nothing above this registry (workflows, the
orchestrator, the future GUI) changes.
"""

from __future__ import annotations

from app.core.ai.provider_interface import AIProvider
from app.core.ai.providers.mock_provider import MockProvider

PROVIDER_REGISTRY: dict[str, type[AIProvider]] = {
    MockProvider.name: MockProvider,
}

__all__ = ["PROVIDER_REGISTRY", "MockProvider"]
