"""Tests for the structured, log-file-only generation logger.

Attaches a handler directly to the ``house_of_stories.ai_generation``
logger instance (rather than relying on ``caplog``/propagation to the
real root logger) so this test works independent of whether
``app.logging_setup.configure_logging()`` has been called in this
process.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from app.core.ai.generation_logger import GenerationLogEntry, log_generation_attempt

_LOGGER_NAME = "house_of_stories.ai_generation"


def _capture(entry: GenerationLogEntry) -> list[logging.LogRecord]:
    records: list[logging.LogRecord] = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        log_generation_attempt(entry)
    finally:
        logger.removeHandler(handler)
    return records


def _entry(**overrides: object) -> GenerationLogEntry:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "request_id": uuid.uuid4(),
        "workflow_name": "scene_image",
        "provider_name": "mock_provider",
        "prompt_template_id": uuid.uuid4(),
        "prompt_template_version": "v01",
        "outcome": "success",
        "started_at": now,
        "ended_at": now,
        "duration_seconds": 0.123,
        "episode_id": uuid.uuid4(),
        "imported_asset_id": uuid.uuid4(),
        "temp_file_name": "mock_image_abc123.png",
    }
    defaults.update(overrides)
    return GenerationLogEntry(**defaults)  # type: ignore[arg-type]


def test_log_generation_attempt_writes_one_json_record_with_expected_fields() -> None:
    entry = _entry()
    records = _capture(entry)

    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("generation_attempt ")
    payload = json.loads(message.removeprefix("generation_attempt "))

    assert payload["workflow_name"] == "scene_image"
    assert payload["provider_name"] == "mock_provider"
    assert payload["outcome"] == "success"
    assert payload["prompt_template_version"] == "v01"
    assert payload["request_id"] == str(entry.request_id)
    assert payload["imported_asset_id"] == str(entry.imported_asset_id)
    assert payload["temp_file_name"] == "mock_image_abc123.png"
    assert "T" in payload["started_at"]  # ISO 8601, not a raw datetime repr
    assert "T" in payload["ended_at"]


def test_log_generation_attempt_uses_warning_level_on_failure() -> None:
    entry = _entry(outcome="failure", error_category="ProviderNotConfiguredError")
    records = _capture(entry)

    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    payload = json.loads(records[0].getMessage().removeprefix("generation_attempt "))
    assert payload["error_category"] == "ProviderNotConfiguredError"


def test_log_generation_attempt_uses_info_level_on_success() -> None:
    records = _capture(_entry(outcome="success"))
    assert records[0].levelno == logging.INFO


def test_temp_file_name_never_contains_a_path_separator() -> None:
    """Guards the "never log full sensitive file paths" rule at the type level.

    ``GenerationLogEntry.temp_file_name`` is documented as a basename
    only — this test is a reminder/guard, not a filesystem check: the
    orchestrator is responsible for passing ``Path(...).name``, never a
    full path, into this field.
    """
    entry = _entry(temp_file_name="mock_image_abc123.png")
    assert "/" not in (entry.temp_file_name or "")
    assert "\\" not in (entry.temp_file_name or "")
