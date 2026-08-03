"""Persisted GUI preferences, backed by ``QSettings``.

The only place in ``app/gui`` that touches ``QSettings`` directly —
every other module asks :class:`AppSettings` for a value instead of
constructing its own ``QSettings`` instance, so the storage key names
live in exactly one place.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from app.gui.theme.tokens import DEFAULT_THEME_NAME

_ORGANIZATION = "HouseOfStoriesStudio"
_APPLICATION = "Studio"

_KEY_WINDOW_GEOMETRY = "window/geometry"
_KEY_THEME = "appearance/theme"
_KEY_LAST_WORKSPACE = "workspace/last_path"


class AppSettings:
    """Thin, typed wrapper around one ``QSettings`` store."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(_ORGANIZATION, _APPLICATION)

    # --- window geometry (size, position, maximized state) -------------

    def save_window_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue(_KEY_WINDOW_GEOMETRY, geometry)

    def load_window_geometry(self) -> QByteArray | None:
        value = self._settings.value(_KEY_WINDOW_GEOMETRY)
        return value if isinstance(value, QByteArray) else None

    # --- theme -----------------------------------------------------------

    def save_theme(self, theme_name: str) -> None:
        self._settings.setValue(_KEY_THEME, theme_name)

    def load_theme(self) -> str:
        value = self._settings.value(_KEY_THEME, DEFAULT_THEME_NAME)
        return str(value) if value else DEFAULT_THEME_NAME

    # --- last opened workspace -------------------------------------------

    def save_last_workspace(self, path: str) -> None:
        self._settings.setValue(_KEY_LAST_WORKSPACE, path)

    def load_last_workspace(self) -> str | None:
        value = self._settings.value(_KEY_LAST_WORKSPACE)
        return str(value) if value else None

    def sync(self) -> None:
        """Force-flush pending writes (called on application exit)."""
        self._settings.sync()
