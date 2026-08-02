"""Shared relative-path validation for any column that stores a managed-storage path.

Used by both :class:`~app.core.models.asset.Asset` (``relative_path``)
and :class:`~app.core.models.license.LicenseRecord`
(``proof_relative_path``) so the two never drift out of sync on what
counts as a safe, portable relative path.
"""

from __future__ import annotations

import re
from pathlib import PurePath

_WINDOWS_ABS_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def looks_absolute(value: str) -> bool:
    """Detect an absolute path under POSIX *or* Windows conventions.

    Uses simple prefix checks (rather than relying solely on
    ``pathlib.PurePath.is_absolute()``) because the app must run on
    Windows, but its tests may run on Linux/macOS, where
    ``PurePath("C:\\\\foo").is_absolute()`` is ``False``.
    """
    if value.startswith(("/", "\\")):
        return True
    if _WINDOWS_ABS_RE.match(value):
        return True
    return PurePath(value).is_absolute()


def validate_relative_path(field_name: str, value: str) -> str:
    """Reject absolute paths and ``..`` traversal; normalize separators to ``/``.

    Raises:
        ValueError: with a message naming ``field_name``, so validation
            errors from different columns are still distinguishable.
    """
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty.")
    if looks_absolute(value):
        raise ValueError(
            f"{field_name} must be relative to production_dir, got an absolute path: {value!r}"
        )
    normalized = value.replace("\\", "/")
    if ".." in PurePath(normalized).parts:
        raise ValueError(f"{field_name} must not contain '..' path traversal: {value!r}")
    return normalized
