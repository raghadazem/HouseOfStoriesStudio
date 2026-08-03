"""Reusable message dialogs: information, warning, error, confirmation.

Every page shows a dialog through these four functions instead of
constructing its own ``QMessageBox`` — keeps button text, icons, and
(later) styling consistent across the whole app.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def show_warning(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def confirm(parent: QWidget | None, title: str, message: str) -> bool:
    result = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


def show_not_implemented(parent: QWidget | None, feature: str) -> None:
    """The one dialog every "coming later" quick action / sidebar item shows."""
    show_info(
        parent,
        feature,
        f"{feature} is coming in Milestone 4B.\n\n"
        "This foundation (Milestone 4A) only wires up the Dashboard and "
        "the actions that already have a working service behind them.",
    )
