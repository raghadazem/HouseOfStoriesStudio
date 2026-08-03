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


# --- Milestone 3.5: AI workflow commands -------------------------------


def test_list_ai_workflows(cli_env: dict[str, str]) -> None:
    result = _run("list-ai-workflows", env=cli_env)
    assert result.returncode == 0
    assert set(result.stdout.split()) == {
        "character_reference_image", "scene_image", "thumbnail", "voice_line",
    }


def test_list_ai_providers(cli_env: dict[str, str]) -> None:
    result = _run("list-ai-providers", env=cli_env)
    assert result.returncode == 0
    assert "mock_provider" in result.stdout
    assert "configured=True" in result.stdout


def test_list_ai_providers_filtered_by_modality(cli_env: dict[str, str]) -> None:
    result = _run("list-ai-providers", "--modality", "image", env=cli_env)
    assert result.returncode == 0
    assert "mock_provider" in result.stdout


def test_run_ai_workflow_thumbnail_and_review_queue(cli_env: dict[str, str]) -> None:
    """Full stack, real subprocess: orchestrator -> MockProvider -> AssetImportService -> review queue."""
    _run("init-db", env=cli_env)
    _run("seed-demo", env=cli_env)

    result = _run("show-episode", "ep001_lost_little_turtle", env=cli_env)
    id_line = next(line for line in result.stdout.splitlines() if line.strip().startswith("id:"))
    episode_id = id_line.split()[-1]

    # Create a global, reusable prompt template to generate against.
    import_script = (
        "from app.core.db.engine import create_db_engine, create_session_factory;"
        "from app.core.db.enums import PromptCategory, PromptType;"
        "from app.core.services.prompt_template_service import PromptTemplateService;"
        "engine = create_db_engine(); factory = create_session_factory(engine);"
        "session = factory();"
        "t = PromptTemplateService().create_prompt_template(session, name='thumb', "
        "category=PromptCategory.THUMBNAIL, prompt_type=PromptType.IMAGE, "
        "text_en='A bright thumbnail.');"
        "session.commit(); print(t.id)"
    )
    result = subprocess.run(
        [sys.executable, "-c", import_script],
        cwd=REPO_ROOT, env=cli_env, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    template_id = result.stdout.strip().splitlines()[-1]

    result = _run(
        "run-ai-workflow", "thumbnail",
        "--prompt-template-id", template_id,
        "--episode-id", episode_id,
        env=cli_env,
    )
    assert result.returncode == 0, result.stderr
    assert "Generated asset" in result.stdout
    assert "mock_provider" in result.stdout

    result = _run("list-review-queue", "--source-tool", "mock_provider", env=cli_env)
    assert result.returncode == 0
    assert "thumbnail" in result.stdout


def test_run_ai_workflow_unknown_workflow_reports_clean_error(cli_env: dict[str, str]) -> None:
    _run("init-db", env=cli_env)
    result = _run(
        "run-ai-workflow", "not_a_real_workflow",
        "--prompt-template-id", "00000000-0000-0000-0000-000000000000",
        env=cli_env,
    )
    assert result.returncode == 1
    assert "Unknown workflow" in result.stdout + result.stderr
    assert "Traceback" not in result.stdout
