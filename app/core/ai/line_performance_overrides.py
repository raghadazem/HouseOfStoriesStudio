"""line_performance_overrides — founder-approved, line-specific TTS
performance configuration that cannot be expressed as ordinary
pronunciation (``PronunciationOverride`` only ever rewrites *how text
is read*, never *whether it's read as text at all*).

This is a small, explicit, code-level registry — not a database table
(no migration was needed to represent one founder-approved exception)
and not a per-line ``if dialogue_line_id == ...`` branch buried inside
:class:`~app.core.ai.providers.elevenlabs_provider.ElevenLabsProvider`
(which stays fully generic, see its own docstring). It lives at the
workflow/domain layer and is consulted exactly once, by
:func:`app.core.ai.generation_runner.run_voice_line_batch`, which is
already the single place that computes a line's effective
``normalized_text_sent``/``model_id`` for real production generation —
this registry only ever *substitutes* those two values for one
specific line, the same way a human would if driving the provider by
hand, so every existing provenance/candidate-matching mechanism
downstream (``GenerationJob.parameters``,
:class:`~app.core.services.voice_production_candidate_service.VoiceProductionCandidateService`)
sees the true, honest values that were actually sent — nothing needs
to know this registry exists to interpret them correctly.

``DialogueLine.authored_text`` is never read or written here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class LinePerformanceOverride:
    """A one-off, founder-approved provider-bound request shape for one
    :class:`~app.core.models.dialogue_line.DialogueLine`.

    ``model_id`` and ``provider_bound_text`` replace the ordinary
    default model and the ordinary ``normalize_arabic_line`` output for
    this line only — every other line, and every other line spoken by
    the same character, is completely unaffected.
    """

    model_id: str
    provider_bound_text: str
    reason: str


# Scene 7, Tortor: authored_text "هاها! دبدوبك يحب اللعب في العشب!" opens
# with an intended natural laugh, not a spoken word. eleven_multilingual_v2
# has no supported mechanism for non-verbal vocalization (confirmed against
# official ElevenLabs docs and the installed SDK); Eleven v3's bracketed
# audio-tag support does, if the same voice_id is kept. Founder-approved
# after real-audio listening review on 2026-08-15 (Tortor_V3_real_laugh_test.mp3)
# — see memory/tortor_laugh_cue_scene7_locked.md. A global هاها replacement
# or a PronunciationOverride were both explicitly rejected as the wrong
# mechanism: this is a performance cue for one specific line, not a
# pronunciation rule.
TORTOR_SCENE7_LAUGH_LINE_ID = uuid.UUID("ed64c44b-171c-44e2-8965-5c3309728fc0")

LINE_PERFORMANCE_OVERRIDES: dict[uuid.UUID, LinePerformanceOverride] = {
    TORTOR_SCENE7_LAUGH_LINE_ID: LinePerformanceOverride(
        model_id="eleven_v3",
        provider_bound_text="[laughs] دبدوبك يحب اللعب في العشب!",
        reason=(
            "Founder-approved non-verbal laugh performance cue (2026-08-15): "
            "eleven_multilingual_v2 has no supported non-verbal-vocalization "
            "mechanism; the [laughs] audio tag requires eleven_v3, same "
            "locked voice_id. authored_text is unaffected."
        ),
    ),
}


def get_line_performance_override(dialogue_line_id: uuid.UUID) -> LinePerformanceOverride | None:
    """The founder-approved performance override for one line, if any."""
    return LINE_PERFORMANCE_OVERRIDES.get(dialogue_line_id)
