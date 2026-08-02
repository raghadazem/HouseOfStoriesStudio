"""Filename/slug normalization: English, lowercase, snake_case.

Per the project-wide convention (``docs/07_DEVELOPMENT_PLAN.md``), every
file the app creates or manages on disk uses an English lowercase
snake_case name — regardless of what the source file was called, and
even if that original name was Arabic or contained other non-ASCII
text. Arabic content itself is never rejected or mangled; it's simply
never used to build a *filename* — see :func:`normalize_filename`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import PurePath

_UNSAFE_CHARS_RE = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LENGTH = 80


def slugify(text: str, *, fallback_prefix: str = "item", max_length: int = _MAX_SLUG_LENGTH) -> str:
    """Convert arbitrary text into an ASCII lowercase snake_case slug.

    Non-ASCII text (Arabic titles, accented Latin, emoji, ...) is
    stripped rather than transliterated — a best-effort romanization of
    Arabic is out of scope and error-prone. If nothing ASCII-safe
    survives, falls back to ``f"{fallback_prefix}_{short_hash}"`` so the
    result is still non-empty and stable for the same input.

    Args:
        text: Arbitrary human-entered text (a title, a filename stem, ...).
        fallback_prefix: Used to build a fallback slug when ``text``
            contains no usable ASCII characters at all.
        max_length: Truncate the result to this many characters.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _UNSAFE_CHARS_RE.sub("_", ascii_only).strip("_")
    slug = re.sub(r"_+", "_", slug)

    if not slug:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        slug = f"{fallback_prefix}_{digest}"

    return slug[:max_length].strip("_") or f"{fallback_prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"


def normalize_filename(filename: str) -> str:
    """Normalize a filename to ``lowercase_snake_case.ext``.

    The extension is preserved (lowercased); the stem is slugified. The
    *original* filename (Arabic or otherwise) is never lost — callers
    are expected to keep it verbatim in ``Asset.original_filename`` and
    use only this normalized form for the actual on-disk path.

    Examples:
        ``"Melissa Front (1).PNG"`` -> ``"melissa_front_1.png"``
        ``"ميليسا.png"`` -> a stable ``"file_<hash>.png"`` fallback,
        since the stem has no ASCII-safe content to slugify.
    """
    path = PurePath(filename)
    stem = path.stem or filename
    suffix = "".join(ch for ch in path.suffix.lower() if ch.isalnum() or ch == ".")

    slug = slugify(stem, fallback_prefix="file")
    return f"{slug}{suffix}"


def collision_safe_name(desired_name: str, existing_names: set[str]) -> str:
    """Return ``desired_name``, or a numbered variant that avoids ``existing_names``.

    ``melissa_front_v01.png`` -> ``melissa_front_v01.png`` if free,
    otherwise ``melissa_front_v01_2.png``, ``melissa_front_v01_3.png``, ...
    """
    if desired_name not in existing_names:
        return desired_name

    path = PurePath(desired_name)
    stem, suffix = path.stem, path.suffix
    counter = 2
    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if candidate not in existing_names:
            return candidate
        counter += 1
