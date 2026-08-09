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
import uuid
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
    "scripts",
    "short_scenes",
    "shorts",
    "songs",
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


# --- Windows/Test Stabilization: approval_records.revision backfill ---
# See docs/engineering/WINDOWS_DEVELOPMENT.md.


def test_approval_records_revision_migration_backfills_existing_history(
    isolated_data_dir: Path,
) -> None:
    """Upgrades a database that already has pre-``revision`` approval
    history (including two decisions sharing one ``decided_at`` — the
    exact case the old ``ORDER BY decided_at`` couldn't resolve), then
    confirms the new column is backfilled deterministically and the
    schema matches what ``alembic check`` expects."""
    pre_revision_result = _run_alembic("upgrade", "8ed8cbd56eee", data_dir=isolated_data_dir)
    assert pre_revision_result.returncode == 0, pre_revision_result.stderr

    db_path = isolated_data_dir / "studio.db"
    entity_id = uuid.uuid4().hex
    tied_at = "2026-08-01 12:00:00.000000"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO approval_records "
            "(id, entity_type, entity_id, decision, decided_by, decided_at, notes, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex, "asset", entity_id, "approved", "founder",
                "2026-08-01 10:00:00.000000", None,
                "2026-08-01 10:00:00.000000", "2026-08-01 10:00:00.000000",
            ),
        )
        # Two decisions on the SAME entity, SAME decided_at — the tie
        # that made "current state" non-deterministic before revision.
        con.execute(
            "INSERT INTO approval_records "
            "(id, entity_type, entity_id, decision, decided_by, decided_at, notes, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex, "asset", entity_id, "needs_changes", "founder",
                tied_at, "fix it", tied_at, tied_at,
            ),
        )
        con.execute(
            "INSERT INTO approval_records "
            "(id, entity_type, entity_id, decision, decided_by, decided_at, notes, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex, "asset", entity_id, "rejected", "founder",
                tied_at, "on reflection, no", tied_at, tied_at,
            ),
        )
        con.commit()

    upgrade_result = _run_alembic("upgrade", "head", data_dir=isolated_data_dir)
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT decision, revision FROM approval_records "
            "WHERE entity_type = 'asset' AND entity_id = ? ORDER BY revision",
            (entity_id,),
        ).fetchall()
    assert [r[1] for r in rows] == [1, 2, 3]  # sequential, no gaps, no duplicates
    assert rows[0][0] == "approved"  # the unambiguously-earliest decision stayed first
    assert {r[0] for r in rows[1:]} == {"needs_changes", "rejected"}  # the tied pair, in some stable order

    check_result = _run_alembic("check", data_dir=isolated_data_dir)
    assert check_result.returncode == 0, check_result.stdout + check_result.stderr


def test_approval_records_revision_migration_downgrade_preserves_rows(
    isolated_data_dir: Path,
) -> None:
    upgrade_result = _run_alembic("upgrade", "head", data_dir=isolated_data_dir)
    assert upgrade_result.returncode == 0, upgrade_result.stderr

    db_path = isolated_data_dir / "studio.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO approval_records "
            "(id, entity_type, entity_id, decision, decided_by, decided_at, notes, "
            "created_at, updated_at, revision) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex, "asset", uuid.uuid4().hex, "approved", "founder",
                "2026-08-01 10:00:00.000000", None,
                "2026-08-01 10:00:00.000000", "2026-08-01 10:00:00.000000", 1,
            ),
        )
        con.commit()

    downgrade_result = _run_alembic(
        "downgrade", "8ed8cbd56eee", data_dir=isolated_data_dir
    )
    assert downgrade_result.returncode == 0, downgrade_result.stderr

    with sqlite3.connect(db_path) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(approval_records)")}
        row_count = con.execute("SELECT count(*) FROM approval_records").fetchone()[0]
    assert "revision" not in columns
    assert row_count == 1  # the row survived, only the column is gone
