"""Verifies the approved Milestone 1 repository foundation is present.

These tests intentionally check structure, not domain behavior (there
is no domain behavior yet) — they exist so an accidental deletion or
rename of a required folder/doc is caught immediately.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_DIRS = [
    "app",
    "app/core",
    "app/core/templates",
    "app/gui",
    "app/cli",
    "production",
    "production/brand",
    "production/characters",
    "production/world",
    "production/prompts",
    "production/episodes",
    "production/channel",
    "docs",
    "tests",
    "data",
]

REQUIRED_FILES = [
    "README.md",
    "pyproject.toml",
    ".gitignore",
    "app/__init__.py",
    "app/config.py",
    "app/logging_setup.py",
]

REQUIRED_DOCS = [
    "docs/00_PROJECT_OVERVIEW.md",
    "docs/01_BRAND_BIBLE.md",
    "docs/02_CHARACTER_BIBLE.md",
    "docs/03_WORLD_BIBLE.md",
    "docs/04_PRODUCTION_PIPELINE.md",
    "docs/05_TECHNICAL_ARCHITECTURE.md",
    "docs/06_CLAUDE_FIRST_TASK.md",
    "docs/07_DEVELOPMENT_PLAN.md",
]


def test_required_directories_exist() -> None:
    missing = [d for d in REQUIRED_DIRS if not (REPO_ROOT / d).is_dir()]
    assert not missing, f"Missing required directories: {missing}"


def test_required_files_exist() -> None:
    missing = [f for f in REQUIRED_FILES if not (REPO_ROOT / f).is_file()]
    assert not missing, f"Missing required files: {missing}"


def test_preexisting_documentation_untouched() -> None:
    """The founder's approved docs must never be deleted or replaced."""
    missing = [d for d in REQUIRED_DOCS if not (REPO_ROOT / d).is_file()]
    assert not missing, f"Missing/removed approved documentation: {missing}"


def test_gui_package_is_still_a_placeholder() -> None:
    """Milestone 1 guardrail: app/gui must stay empty until Milestone 4.

    A full import-boundary check (gui must only call app.core.services,
    never touch the filesystem/DB directly) belongs with the real GUI
    code in Milestone 4; this only guards against Milestone 1
    accidentally starting that work early.
    """
    gui_dir = REPO_ROOT / "app" / "gui"
    python_files = list(gui_dir.rglob("*.py"))
    assert python_files == [gui_dir / "__init__.py"], (
        "app/gui should only contain the placeholder __init__.py until "
        "Milestone 4"
    )
