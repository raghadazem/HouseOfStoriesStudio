"""FormDialog — the base for every create-form and read-only detail dialog.

One consistent shell (title, scrollable content area, inline error
line, Cancel/Save or single Close footer) instead of each page building
its own ad hoc ``QDialog``. A create-form subclass overrides
:meth:`validate` to check its fields before ``accept()``; a read-only
detail dialog passes ``show_save=False`` and gets a single "Close"
button.

``QDialog`` gives Escape-to-close and Enter-triggers-the-default-button
for free — no extra keyboard wiring needed here.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.tokens import METRICS


class FormDialog(QDialog):
    def __init__(
        self,
        title: str,
        *,
        save_label: str = "Save",
        show_save: bool = True,
        min_width: int = 460,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg, METRICS.spacing_lg
        )
        outer.setSpacing(METRICS.spacing_md)

        title_label = QLabel(title)
        title_label.setProperty("class", "dialogTitle")
        title_label.setWordWrap(True)
        outer.addWidget(title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("formDialogScroll")
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(METRICS.spacing_md)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self._error_label = QLabel("")
        self._error_label.setProperty("class", "formError")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self._save_button: QPushButton | None = None
        if show_save:
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject)
            footer.addWidget(cancel_button)

            self._save_button = QPushButton(save_label)
            self._save_button.setProperty("class", "primary")
            self._save_button.setDefault(True)
            self._save_button.clicked.connect(self._on_save_clicked)
            footer.addWidget(self._save_button)
        else:
            close_button = QPushButton("Close")
            close_button.setDefault(True)
            close_button.clicked.connect(self.accept)
            footer.addWidget(close_button)
        outer.addLayout(footer)

    def add_row(self, label: str, widget: QWidget) -> None:
        """A labeled field row: a caption above the input, added to `content_layout`."""
        row = QVBoxLayout()
        row.setSpacing(4)
        caption = QLabel(label)
        caption.setProperty("class", "formLabel")
        row.addWidget(caption)
        row.addWidget(widget)
        self.content_layout.addLayout(row)

    def validate(self) -> str | None:
        """Override to check fields before accept(). Return an error message, or None if valid."""
        return None

    def show_form_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def _on_save_clicked(self) -> None:
        error = self.validate()
        if error:
            self.show_form_error(error)
            return
        self._error_label.setVisible(False)
        self.accept()
