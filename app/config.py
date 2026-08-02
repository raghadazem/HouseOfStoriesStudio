"""Application configuration for House of Stories Studio.

Centralizes filesystem paths and runtime settings so the rest of the
application never hardcodes a path. Every path is resolved relative to
the repository root unless overridden by an environment variable, which
keeps the app portable across machines (including Windows, where the
app must run) and lets tests redirect runtime data to a temporary
directory instead of touching the real ``data/`` folder.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ENV_PROJECT_ROOT = "HOS_PROJECT_ROOT"
_ENV_DATA_DIR = "HOS_DATA_DIR"
_ENV_PRODUCTION_DIR = "HOS_PRODUCTION_DIR"
_ENV_LOG_LEVEL = "HOS_LOG_LEVEL"
_ENV_RESTRICTED_IMPORT_DIRS = "HOS_RESTRICTED_IMPORT_DIRS"

DEFAULT_LOG_LEVEL = "INFO"
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _repo_root() -> Path:
    """Return the repository root, derived from this file's location.

    This module lives at ``<repo_root>/app/config.py``, so the repo
    root is one level up. Deriving it from ``__file__`` (instead of the
    current working directory) keeps path resolution correct no matter
    where the app is launched from.
    """
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    """Resolved filesystem locations and runtime settings for the app.

    All paths are :class:`pathlib.Path` instances so they behave
    correctly on Windows, macOS, and Linux alike. Nothing here is a
    hardcoded absolute path — everything is derived from the repository
    root or from explicit environment variable overrides.
    """

    project_root: Path
    production_dir: Path
    data_dir: Path
    db_path: Path
    log_dir: Path
    log_level: str = DEFAULT_LOG_LEVEL
    # Directories AssetImportService must always refuse to import from —
    # e.g. wherever the founder keeps original personal reference
    # photographs outside this repository. Never hardcoded: configured
    # per-machine via HOS_RESTRICTED_IMPORT_DIRS.
    restricted_import_dirs: tuple[Path, ...] = ()

    def ensure_runtime_dirs(self) -> None:
        """Create the runtime directories (``data/``, ``data/logs/``).

        Safe to call repeatedly. Does not create ``production_dir`` —
        that is expected to already exist as part of the repository,
        and silently creating it here could hide a real setup problem.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    """Build an :class:`AppConfig` from defaults and environment overrides.

    Args:
        env: Mapping to read overrides from. Defaults to
            ``os.environ``; pass a plain ``dict`` in tests to avoid
            mutating real process environment variables.

    Environment variables:
        ``HOS_PROJECT_ROOT``: Overrides the detected repository root.
        ``HOS_DATA_DIR``: Overrides where runtime data (SQLite database,
            logs, local machine config) is stored. Defaults to
            ``<project_root>/data``.
        ``HOS_PRODUCTION_DIR``: Overrides where creative production
            content lives. Defaults to ``<project_root>/production``.
        ``HOS_LOG_LEVEL``: Overrides the default logging level, e.g.
            ``"DEBUG"``.
        ``HOS_RESTRICTED_IMPORT_DIRS``: A list of directories
            ``AssetImportService`` must always refuse to import from
            (e.g. a private folder of original reference photographs),
            separated by ``os.pathsep`` (``;`` on Windows, ``:`` on
            POSIX). Empty/unset means no restricted directories are
            configured.

    Raises:
        ValueError: If ``HOS_LOG_LEVEL`` is set to a value that is not
            a recognized logging level name.
    """
    source: Mapping[str, str] = env if env is not None else os.environ

    project_root = (
        Path(source[_ENV_PROJECT_ROOT]).resolve()
        if _ENV_PROJECT_ROOT in source
        else _repo_root()
    )
    data_dir = (
        Path(source[_ENV_DATA_DIR]).resolve()
        if _ENV_DATA_DIR in source
        else project_root / "data"
    )
    production_dir = (
        Path(source[_ENV_PRODUCTION_DIR]).resolve()
        if _ENV_PRODUCTION_DIR in source
        else project_root / "production"
    )

    log_level = source.get(_ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    if log_level not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid {_ENV_LOG_LEVEL}={log_level!r}. "
            f"Expected one of: {', '.join(_VALID_LOG_LEVELS)}."
        )

    restricted_raw = source.get(_ENV_RESTRICTED_IMPORT_DIRS, "")
    restricted_import_dirs = tuple(
        Path(part).resolve() for part in restricted_raw.split(os.pathsep) if part.strip()
    )

    return AppConfig(
        project_root=project_root,
        production_dir=production_dir,
        data_dir=data_dir,
        db_path=data_dir / "studio.db",
        log_dir=data_dir / "logs",
        log_level=log_level,
        restricted_import_dirs=restricted_import_dirs,
    )


_cached_config: AppConfig | None = None


def get_config(*, force_reload: bool = False) -> AppConfig:
    """Return a process-wide cached :class:`AppConfig`.

    Most application code should call this rather than
    :func:`load_config` directly, so path resolution only happens once
    per run. Tests that need an isolated configuration should call
    :func:`load_config` directly instead of relying on this cache.
    """
    global _cached_config
    if _cached_config is None or force_reload:
        _cached_config = load_config()
    return _cached_config


def resolve_log_level(level_name: str) -> int:
    """Translate a level name like ``"INFO"`` into a ``logging`` constant.

    Raises:
        ValueError: If ``level_name`` is not a recognized logging level.
    """
    level = logging.getLevelName(level_name.upper())
    if not isinstance(level, int):
        # ValueError, not TypeError: level_name has the right type (str),
        # just an unrecognized value.
        raise ValueError(  # noqa: TRY004
            f"Invalid log level {level_name!r}. "
            f"Expected one of: {', '.join(_VALID_LOG_LEVELS)}."
        )
    return level
