"""Structured logging setup for House of Stories Studio.

Configures a console handler (for interactive use) and a rotating file
handler (for after-the-fact debugging) that share one formatter, so log
lines look identical in a terminal and in ``data/logs/app.log``. The
file handler is UTF-8 so Arabic episode titles and dialogue snippets in
log messages are never mangled.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import AppConfig, get_config, resolve_log_level

LOGGER_NAME = "house_of_stories"

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 2_000_000  # ~2 MB per log file before rotating
_BACKUP_COUNT = 5

_configured = False


def configure_logging(
    config: AppConfig | None = None, *, force: bool = False
) -> logging.Logger:
    """Configure and return the application's root logger.

    Idempotent by default: calling this more than once (e.g. once from
    ``main.py`` and again from a test fixture) will not duplicate
    handlers unless ``force=True`` is passed.

    Args:
        config: Configuration to read the log level and log directory
            from. Defaults to :func:`app.config.get_config`.
        force: Reconfigure and replace handlers even if logging was
            already configured in this process.

    Returns:
        The ``"house_of_stories"`` logger. Application code should log
        through this logger or a child of it, e.g.
        ``logging.getLogger("house_of_stories.asset_service")``.
    """
    global _configured

    cfg = config or get_config()
    logger = logging.getLogger(LOGGER_NAME)

    if _configured and not force:
        return logger

    cfg.ensure_runtime_dirs()

    level = resolve_log_level(cfg.log_level)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_file = cfg.log_dir / "app.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the app logger, or a named child of it.

    Does not configure handlers itself — call :func:`configure_logging`
    once at application startup first.
    """
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
