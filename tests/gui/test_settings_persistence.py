"""AppSettings: every persisted preference round-trips through QSettings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from app.gui.settings import AppSettings


def test_theme_defaults_to_light_when_never_saved(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert settings.load_theme() == "light"


def test_theme_round_trips(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    settings.save_theme("dark")
    assert settings.load_theme() == "dark"


def test_theme_persists_across_new_qsettings_instances_on_same_file(tmp_path: Path) -> None:
    ini_path = str(tmp_path / "s.ini")
    AppSettings(QSettings(ini_path, QSettings.Format.IniFormat)).save_theme("dark")

    reloaded = AppSettings(QSettings(ini_path, QSettings.Format.IniFormat))
    assert reloaded.load_theme() == "dark"


def test_window_geometry_defaults_to_none(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert settings.load_window_geometry() is None


def test_window_geometry_round_trips(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    geometry = QByteArray(b"fake-geometry-bytes")

    settings.save_window_geometry(geometry)

    assert settings.load_window_geometry() == geometry


def test_last_workspace_round_trips(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert settings.load_last_workspace() is None

    settings.save_last_workspace("/some/production/dir")

    assert settings.load_last_workspace() == "/some/production/dir"


def test_sync_does_not_raise(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    settings.save_theme("dark")
    settings.sync()  # should not raise
