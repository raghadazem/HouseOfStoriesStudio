"""Tests for app.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import DEFAULT_LOG_LEVEL, load_config, resolve_log_level


def test_load_config_defaults_to_repo_relative_paths() -> None:
    config = load_config(env={})

    assert config.project_root.is_dir()
    assert config.production_dir == config.project_root / "production"
    assert config.data_dir == config.project_root / "data"
    assert config.db_path == config.data_dir / "studio.db"
    assert config.log_dir == config.data_dir / "logs"
    assert config.log_level == DEFAULT_LOG_LEVEL


def test_load_config_respects_env_overrides(tmp_path: Path) -> None:
    custom_root = tmp_path / "custom_root"
    custom_data = tmp_path / "custom_data"
    custom_root.mkdir()

    config = load_config(
        env={
            "HOS_PROJECT_ROOT": str(custom_root),
            "HOS_DATA_DIR": str(custom_data),
            "HOS_LOG_LEVEL": "debug",
        }
    )

    assert config.project_root == custom_root.resolve()
    assert config.data_dir == custom_data.resolve()
    assert config.log_level == "DEBUG"


def test_load_config_rejects_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="Invalid HOS_LOG_LEVEL"):
        load_config(env={"HOS_LOG_LEVEL": "not_a_real_level"})


def test_ensure_runtime_dirs_creates_data_and_log_dirs(tmp_path: Path) -> None:
    config = load_config(
        env={
            "HOS_PROJECT_ROOT": str(tmp_path),
            "HOS_DATA_DIR": str(tmp_path / "data"),
        }
    )

    assert not config.data_dir.exists()

    config.ensure_runtime_dirs()

    assert config.data_dir.is_dir()
    assert config.log_dir.is_dir()


def test_resolve_log_level_accepts_known_names() -> None:
    import logging

    assert resolve_log_level("info") == logging.INFO
    assert resolve_log_level("ERROR") == logging.ERROR


def test_resolve_log_level_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        resolve_log_level("not_a_level")
