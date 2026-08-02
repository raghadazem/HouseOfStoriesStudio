"""CLI smoke tests: run every command as a real subprocess against an isolated project.

Mirrors ``tests/integration/test_migrations.py``'s approach (subprocess,
not in-process) so each command gets a fully fresh process and there's
no risk of ``app.config.get_config()``'s cache leaking a wrong
``HOS_DATA_DIR`` between commands.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def cli_env(tmp_path: Path) -> dict[str, str]:
    production_dir = tmp_path / "production"
    data_dir = tmp_path / "data"
    production_dir.mkdir()
    data_dir.mkdir()
    env = dict(os.environ)
    env["HOS_PROJECT_ROOT"] = str(tmp_path)
    env["HOS_DATA_DIR"] = str(data_dir)
    env["HOS_PRODUCTION_DIR"] = str(production_dir)
    return env


def _run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli.main", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_init_db_and_seed_demo(cli_env: dict[str, str]) -> None:
    result = _run("init-db", env=cli_env)
    assert result.returncode == 0, result.stderr

    result = _run("seed-demo", env=cli_env)
    assert result.returncode == 0, result.stderr
    assert "melissa" in result.stdout
    assert "ep001_lost_little_turtle" in result.stdout


def test_list_and_show_episode(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("list-episodes", env=cli_env)
    assert result.returncode == 0
    assert "ep001_lost_little_turtle" in result.stdout

    result = _run("show-episode", "ep001_lost_little_turtle", env=cli_env)
    assert result.returncode == 0
    assert "Melissa and Bilsan and the Lost Little Turtle" in result.stdout
    assert "ميليسا وبيلسان" in result.stdout
    assert "shorts: 3" in result.stdout


def test_show_episode_not_found_reports_clean_error(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("show-episode", "does_not_exist", env=cli_env)
    assert result.returncode == 1
    assert "not found" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout


def test_check_episode(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("check-episode", "ep001_lost_little_turtle", env=cli_env)
    assert result.returncode == 0
    assert "Readiness:" in result.stdout
    assert "NOT READY" in result.stdout


def test_create_default_tasks(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("create-default-tasks", "ep001_lost_little_turtle", env=cli_env)
    assert result.returncode == 0
    assert "Created 15 task(s)" in result.stdout


def test_import_asset_and_list_assets(cli_env: dict[str, str], tmp_path: Path) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    source = tmp_path / "test_image.png"
    source.write_bytes(b"fake png bytes")

    result = _run(
        "import-asset", "--source", str(source), "--asset-type", "image",
        "--source-tool", "test_tool", env=cli_env,
    )
    assert result.returncode == 0, result.stderr
    assert "Imported asset" in result.stdout

    result = _run("list-assets", env=cli_env)
    assert result.returncode == 0
    assert "image" in result.stdout


def test_export_episode_preview(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("export-episode", "ep001_lost_little_turtle", "--preview", env=cli_env)
    assert result.returncode == 0, result.stderr
    assert "Export written to" in result.stdout

    export_dir = Path(cli_env["HOS_PRODUCTION_DIR"]) / "episodes/ep001_lost_little_turtle/exports/preview"
    assert (export_dir / "title_ar.txt").exists()


def test_export_episode_final_blocked_without_preview(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("export-episode", "ep001_lost_little_turtle", env=cli_env)
    assert result.returncode == 1
    assert "Refusing final export" in result.stdout + result.stderr
