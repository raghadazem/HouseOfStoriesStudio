"""Structured, log-file-only recording of every AI generation attempt.

Per the founder's explicit decision (``docs/18_AI_ARCHITECTURE_PLAN.md``
§11), Milestone 3.5 does **not** add a persistent ``GenerationLog``
database table — every :meth:`~app.core.ai.orchestrator.AIOrchestrator.run_workflow`
attempt is instead written as one structured line through the
application's existing logger (``app/logging_setup.py``), as a child
logger so it lands in the same ``data/logs/app.log`` file. A persistent
database history may be added later, once a real provider is wired up
and cost-per-call becomes a real question worth tracking in the
database rather than the log file.

**Never logged, by construction:** API keys/secrets (nothing in this
module ever receives one — no real provider exists yet), personal
photographs (impossible in this pipeline; see
``docs/11_STORAGE_RULES.md``), or full/absolute file paths — a
generated file's path is logged as its filename only, never its full
filesystem location, since that could leak local username/folder
structure from the founder's machine.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from app.logging_setup import get_logger

_LOGGER_NAME = "ai_generation"


@dataclass(frozen=True)
class GenerationLogEntry:
    """One record of one ``run_workflow()`` attempt, success or failure."""

    request_id: uuid.UUID
    workflow_name: str
    provider_name: str
    prompt_template_id: uuid.UUID | None
    prompt_template_version: str | None
    outcome: str  # "success" | "failure"
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    episode_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None = None
    short_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    character_version_id: uuid.UUID | None = None
    error_category: str | None = None
    # Basename only — see module docstring.
    temp_file_name: str | None = None
    imported_asset_id: uuid.UUID | None = None


def log_generation_attempt(entry: GenerationLogEntry) -> None:
    """Write one structured JSON line describing a completed ``run_workflow()`` attempt."""
    logger = get_logger(_LOGGER_NAME)
    payload = {
        key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, uuid.UUID) else value)
        for key, value in asdict(entry).items()
    }
    level = logging.INFO if entry.outcome == "success" else logging.WARNING
    logger.log(level, "generation_attempt %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
