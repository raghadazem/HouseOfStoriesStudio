"""Tests for line_performance_overrides: the founder-approved,
line-specific TTS performance registry (Milestone 9 production-safety
checkpoint, 2026-08-15)."""

from __future__ import annotations

import uuid

from app.core.ai.line_performance_overrides import (
    TORTOR_SCENE7_LAUGH_LINE_ID,
    get_line_performance_override,
)


def test_tortor_scene7_line_resolves_to_eleven_v3_laugh_cue() -> None:
    override = get_line_performance_override(TORTOR_SCENE7_LAUGH_LINE_ID)

    assert override is not None
    assert override.model_id == "eleven_v3"
    assert override.provider_bound_text == "[laughs] دبدوبك يحب اللعب في العشب!"


def test_unregistered_line_has_no_override() -> None:
    """Ordinary lines -- including any other line that happens to
    contain هاها-like text -- are never globally transformed; only the
    one explicitly registered line id is affected."""
    assert get_line_performance_override(uuid.uuid4()) is None
