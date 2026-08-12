"""text_normalization — Arabic dialogue text normalization for voice generation.

A pure function, not a service: no database access, no side effects.
Takes a :class:`~app.core.models.dialogue_line.DialogueLine`'s
``authored_text`` and the currently-configured global pronunciation
overrides (see ``app.core.services.pronunciation_override_service``)
and returns the exact text to send to a voice provider. The authored
text itself is never mutated by this — only the (separately snapshotted,
see ``GenerationJob.parameters["normalized_text_sent"]``) string handed
to the provider.

Deliberately minimal: whitespace collapsing and pronunciation-override
substitution only. No destructive rewriting, no full diacritization of
ordinary prose, no punctuation-conversion rules invented without
evidence a real provider actually needs them — extend this only when
real ElevenLabs output demonstrates a concrete need, per the founder's
explicit "keep it small" instruction.
"""

from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_arabic_line(text: str, *, pronunciation_overrides: dict[str, str] | None = None) -> str:
    """Return the exact text that should be sent to the voice provider.

    ``pronunciation_overrides`` is a plain ``{term: replacement}`` dict
    (already loaded from :class:`~app.core.models.pronunciation_override.PronunciationOverride`
    rows by the caller — this function has no database access of its
    own) applied as whole-substring replacement, longest terms first so
    a shorter term can never partially clobber a longer one that
    contains it.
    """
    normalized = _WHITESPACE_RE.sub(" ", text.strip())
    overrides = pronunciation_overrides or {}
    for term in sorted(overrides, key=len, reverse=True):
        normalized = normalized.replace(term, overrides[term])
    return normalized
