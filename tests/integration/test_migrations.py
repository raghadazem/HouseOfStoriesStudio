"""Integration tests for the Alembic migration setup.

Runs the real ``alembic`` CLI as a subprocess (rather than calling the
Alembic Python API in-process) so each test gets a fully fresh process —
``app.config.get_config()`` caches its result per-process, and this
avoids that cache leaking a wrong ``HOS_DATA_DIR`` between tests.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_TABLES = {
    "alembic_version",
    "approval_records",
    "assets",
    "character_references",
    "character_versions",
    "characters",
    "episode_characters",
    "episodes",
    "license_records",
    "production_tasks",
    "prompt_templates",
    "scene_characters",
    "scenes",
    "short_scenes",
    "shorts",
}


def _run_alembic(*args: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOS_PROJECT_ROOT"] = str(REPO_ROOT)
    env["HOS_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture()
def isolated_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def test_alembic_upgrade_head_creates_all_tables(isolated_data_dir: Path) -> None:
    result = _run_alembic("upgrade", "head", data_dir=isolated_data_dir)
    assert result.returncode == 0, result.stderr

    db_path = isolated_data_dir / "studio.db"
    assert db_path.exists()

    with sqlite3.connect(db_path) as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert tables == EXPECTED_TABLES


def test_alembic_downgrade_base_drops_all_tables(isolated_data_dir: Path) -> None:
    upgrade_result = _run_alembic("upgrade", "head", data_dir=isolated_data_dir)
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    downgrade_result = _run_alembic("downgrade", "base", data_dir=isolated_data_dir)
    assert downgrade_result.returncode == 0, downgrade_result.stderr

    db_path = isolated_data_dir / "studio.db"
    with sqlite3.connect(db_path) as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert tables == {"alembic_version"}


def test_alembic_check_reports_no_model_migration_drift(isolated_data_dir: Path) -> None:
    """Guards against a model change that was never captured in a migration."""
    upgrade_result = _run_alembic("upgrade", "head", data_dir=isolated_data_dir)
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    check_result = _run_alembic("check", data_dir=isolated_data_dir)
    assert check_result.returncode == 0, check_result.stdout + check_result.stderr
    assert "No new upgrade operations detected" in check_result.stdout
