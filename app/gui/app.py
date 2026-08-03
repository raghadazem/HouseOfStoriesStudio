"""GUI entry point.

Usage (from the repository root, inside the venv, with the ``gui``
extra installed)::

    python -m app.gui.app
    hos-gui
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app import __version__
from app.gui.context import ApplicationContext
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.windows.main_window import MainWindow

ORGANIZATION_NAME = "HouseOfStoriesStudio"
APPLICATION_NAME = "Studio"


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APPLICATION_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationVersion(__version__)

    settings = AppSettings()
    ctx = ApplicationContext()
    theme = ThemeManager(app, initial_theme=settings.load_theme())

    window = MainWindow(ctx, theme, settings)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
