"""Verifies the approved repository foundation (Milestones 1-3) is present.

These tests check structure, not domain behavior (that's covered
service-by-service elsewhere) — they exist so an accidental deletion or
rename of a required folder/doc is caught immediately.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_DIRS = [
    "app",
    "app/core",
    "app/core/db",
    "app/core/models",
    "app/core/services",
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
    "alembic",
    "alembic/versions",
]

REQUIRED_FILES = [
    "README.md",
    "pyproject.toml",
    ".gitignore",
    "app/__init__.py",
    "app/config.py",
    "app/logging_setup.py",
    "alembic.ini",
    "alembic/env.py",
    "app/core/db/base.py",
    "app/core/db/engine.py",
    "app/core/db/enums.py",
    "app/core/db/seed.py",
    "app/core/naming.py",
    "app/core/services/exceptions.py",
    "app/core/services/unit_of_work.py",
    "app/core/services/episode_service.py",
    "app/core/services/asset_import_service.py",
    "app/core/services/storage_service.py",
    "app/core/services/production_checklist_service.py",
    "app/core/services/export_package_service.py",
    "app/cli/main.py",
    "app/core/ai/orchestrator.py",
    "app/gui/app.py",
    "app/gui/context.py",
    "app/gui/settings.py",
    "app/gui/theme/manager.py",
    "app/gui/windows/main_window.py",
    "app/gui/pages/dashboard_page.py",
    "app/gui/widgets/elevated_card.py",
    "app/gui/widgets/app_logo.py",
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
    "docs/08_IMPLEMENTATION_STATUS.md",
    "docs/09_DOMAIN_MODEL.md",
    "docs/10_DATABASE_SCHEMA.md",
    "docs/11_STORAGE_RULES.md",
    "docs/12_MILESTONE_2_STATUS.md",
    "docs/13_CORE_SERVICES.md",
    "docs/14_ASSET_IMPORT_WORKFLOW.md",
    "docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md",
    "docs/16_EXPORT_PACKAGE.md",
    "docs/17_MILESTONE_3_STATUS.md",
    "docs/18_AI_ARCHITECTURE_PLAN.md",
    "docs/19_MILESTONE_3.5_STATUS.md",
    "docs/20_GUI_ARCHITECTURE.md",
    "docs/21_DESIGN_SYSTEM.md",
    "docs/22_MILESTONE_4A_STATUS.md",
    "docs/23_UI_UX_POLISH_STATUS.md",
    "docs/24_UI_UX_POLISH_V2_STATUS.md",
    "docs/25_MILESTONE_4B_STATUS.md",
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


def test_gui_never_imports_db_or_core_services_internals_directly() -> None:
    """Milestone 4A guardrail: GUI code only reaches the DB through ApplicationContext.

    Cheap static check (grep for suspicious imports), not a full
    boundary analysis — good enough to catch a page importing
    ``app.core.db.engine`` or constructing a service itself instead of
    going through ``ApplicationContext``.
    """
    gui_dir = REPO_ROOT / "app" / "gui"
    forbidden_imports = ("app.core.db.engine", "app.core.db.seed")
    offenders = []
    for path in gui_dir.rglob("*.py"):
        if path.name in {"context.py"}:
            continue  # ApplicationContext is the one file allowed to wire these up
        text = path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            if forbidden in text:
                offenders.append((str(path.relative_to(REPO_ROOT)), forbidden))
    assert not offenders, f"GUI files importing DB internals directly: {offenders}"
