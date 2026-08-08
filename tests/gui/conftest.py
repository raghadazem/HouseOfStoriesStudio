"""Shared fixtures for GUI tests.

Requires PySide6 + pytest-qt (installed via the ``gui``/``dev`` extras)
— skipped entirely when PySide6 isn't installed, so a plain ``pytest -q``
on a Milestone 1-3-only install (no GUI extras) still passes cleanly,
exactly as ``pyproject.toml``'s ``gui`` extra comment promises.

``QT_QPA_PLATFORM=offscreen`` is set before PySide6 is ever imported so
these tests run without a real display (matches how screenshots for
``docs/22_MILESTONE_4A_STATUS.md`` were captured).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from app.config import AppConfig, load_config
from app.core import models  # noqa: F401 - registers every table on Base.metadata
from app.core.db.base import Base
from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager


@pytest.fixture()
def gui_app_config(tmp_path: Path) -> AppConfig:
    """An isolated AppConfig, same pattern as the core test suite's ``app_config``."""
    production_dir = tmp_path / "production"
    data_dir = tmp_path / "data"
    production_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    return load_config(
        env={
            "HOS_PROJECT_ROOT": str(tmp_path),
            "HOS_DATA_DIR": str(data_dir),
            "HOS_PRODUCTION_DIR": str(production_dir),
        }
    )


@pytest.fixture()
def gui_context(gui_app_config: AppConfig) -> Iterator[ApplicationContext]:
    """A real ApplicationContext with a fresh, fully-migrated schema (no seed data)."""
    ctx = ApplicationContext(gui_app_config)
    Base.metadata.create_all(ctx.engine)
    yield ctx
    ctx.dispose()


@pytest.fixture()
def gui_settings(tmp_path: Path) -> AppSettings:
    """AppSettings backed by a throwaway ini file — never touches the real registry/plist."""
    qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(qsettings)


@pytest.fixture()
def theme(qapp) -> ThemeManager:
    return ThemeManager(qapp, initial_theme="light")


@pytest.fixture(autouse=True)
def _reset_qapplication_style(qapp) -> Iterator[None]:
    """Undo any global QApplication-level styling a test applied.

    ``ThemeManager.__init__``/``set_theme`` (``docs/21_DESIGN_SYSTEM.md``
    §3) call ``QApplication.setStyleSheet(...)`` — the *only* place any
    stylesheet is ever applied in this app. Because the ``QApplication``
    is a process-wide singleton every GUI test shares (pytest-qt's
    ``qapp`` fixture can't create more than one per process), a
    stylesheet set by one test — whether via the ``theme`` fixture above
    or a test constructing its own ``ThemeManager`` directly — silently
    stayed active for every test that ran afterward, changing button/
    font padding (and therefore measured widget sizes) in tests that
    never touched theming themselves. Found via ``PageHeader.resize()``
    measuring ~437px instead of the requested 300px only when run after
    other GUI tests, never in isolation — see
    ``docs/28_ASSET_IMPORT_AND_GUI_TEST_ISOLATION_STATUS.md``.

    Autouse, so every test under ``tests/gui/`` gets this reset without
    needing to remember to request it — the same reason no single test
    file was ever going to reliably self-clean, since none of them knew
    about any other file's leftover state.
    """
    yield
    qapp.setStyleSheet("")
