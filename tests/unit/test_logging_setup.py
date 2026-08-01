"""Tests for app.logging_setup."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import load_config
from app.logging_setup import configure_logging, get_logger


def _isolated_config(tmp_path: Path):
    return load_config(
        env={
            "HOS_PROJECT_ROOT": str(tmp_path),
            "HOS_DATA_DIR": str(tmp_path / "data"),
            "HOS_LOG_LEVEL": "DEBUG",
        }
    )


def test_configure_logging_creates_log_file(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)

    logger = configure_logging(config, force=True)
    logger.info("milestone 1 smoke test message")
    for handler in logger.handlers:
        handler.flush()

    log_file = config.log_dir / "app.log"
    assert log_file.exists()
    assert "milestone 1 smoke test message" in log_file.read_text(encoding="utf-8")


def test_configure_logging_is_idempotent_without_force(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)

    logger_first = configure_logging(config, force=True)
    handler_count_first = len(logger_first.handlers)

    logger_second = configure_logging(config)

    assert logger_second is logger_first
    assert len(logger_second.handlers) == handler_count_first


def test_configure_logging_supports_arabic_text(tmp_path: Path) -> None:
    config = _isolated_config(tmp_path)

    logger = configure_logging(config, force=True)
    logger.info("العنوان: ميليسا وبيلسان والسلحفاة الصغيرة الضائعة")
    for handler in logger.handlers:
        handler.flush()

    log_file = config.log_dir / "app.log"
    content = log_file.read_text(encoding="utf-8")
    assert "ميليسا وبيلسان" in content


def test_get_logger_returns_named_child() -> None:
    child = get_logger("asset_service")
    assert child.name == "house_of_stories.asset_service"

    root = get_logger()
    assert root.name == "house_of_stories"
    assert root.level == logging.NOTSET or isinstance(root.level, int)
