"""AI provider abstraction and workflow orchestration layer (Milestone 3.5).

See ``docs/18_AI_ARCHITECTURE_PLAN.md`` for the approved architecture
and ``docs/19_MILESTONE_3.5_STATUS.md`` for what was actually built.
Nothing in this package makes a real network call — ``MockProvider`` is
the only fully-implemented provider today. Real providers are added
later purely by implementing ``AIProvider`` (``provider_interface.py``)
and registering the class in ``app.core.ai.providers.PROVIDER_REGISTRY``
— no change to the workflow layer, the orchestrator, the CLI, or (in
Milestone 4) the GUI is required.
"""

from __future__ import annotations

from app.core.ai.orchestrator import AIOrchestrator

__all__ = ["AIOrchestrator"]
