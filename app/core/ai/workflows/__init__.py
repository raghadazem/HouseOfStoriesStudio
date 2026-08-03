"""The four Milestone 3.5 workflows.

Song generation is deliberately not included: the founder's decision
keeps it a manual process for now, since Suno has no free integration
stable enough to build this architecture's automated path against.
Adding it later is a new file in this package plus one registry entry
in ``app.core.ai.orchestrator`` — not a change to anything else.
"""

from __future__ import annotations

from app.core.ai.workflows.base import Workflow, WorkflowContext, WorkflowResult
from app.core.ai.workflows.character_reference_workflow import CharacterReferenceWorkflow
from app.core.ai.workflows.scene_image_workflow import SceneImageWorkflow
from app.core.ai.workflows.thumbnail_workflow import ThumbnailWorkflow
from app.core.ai.workflows.voice_line_workflow import VoiceLineWorkflow

__all__ = [
    "CharacterReferenceWorkflow",
    "SceneImageWorkflow",
    "ThumbnailWorkflow",
    "VoiceLineWorkflow",
    "Workflow",
    "WorkflowContext",
    "WorkflowResult",
]
