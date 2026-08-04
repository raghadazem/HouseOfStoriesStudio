"""ReviewQueuePage — approve or reject every draft asset awaiting a decision.

Rows here are a plain ``QFrame`` (not an :class:`~app.gui.widgets.entity_row.EntityRow`
``QPushButton``) specifically because each row needs its own two
*interactive* inline actions (Approve/Reject) — Qt does not cleanly
support a clickable child widget inside a ``QPushButton``, and
``EntityRow`` documents that it's for read-only trailing content only.
Approve/Reject call the new ``ApprovalService.decide_asset_review`` —
the one piece of business logic this milestone had to add to the core
service layer, since nothing previously turned "list the queue" into
"decide on an item in it" (see ``docs/25_MILESTONE_4B_STATUS.md``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.db.enums import ApprovalDecision
from app.core.models import Asset
from app.core.services.exceptions import ServiceError, ValidationError
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    ErrorState,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    SearchBox,
    age_label,
    show_error,
)

_SOURCE_ALL = "__all__"
_SOURCE_MANUAL = "__manual__"

_TYPE_ICON = {
    "image": "🖼", "video": "🎬", "voice": "🎙️", "music": "🎵", "thumbnail": "🏞", "document": "📄",
}


class _RejectReasonDialog(FormDialog):
    def __init__(self, asset_name: str, parent: QWidget | None = None) -> None:
        super().__init__(f"Reject {asset_name}", save_label="Reject", parent=parent)

        self.reason_field = QTextEdit()
        self.reason_field.setPlaceholderText("What needs to change before this can be approved?")
        self.reason_field.setMinimumHeight(100)
        self.add_row("Reason", self.reason_field)

    def validate(self) -> str | None:
        if not self.reason_field.toPlainText().strip():
            return "A reason is required to reject an asset."
        return None

    def reason(self) -> str:
        return self.reason_field.toPlainText().strip()


class ReviewQueuePage(QWidget):
    review_count_updated = Signal(int)

    def __init__(
        self, ctx: ApplicationContext, theme: ThemeManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reviewQueuePage")
        self._ctx = ctx
        self._theme = theme
        self._assets: list[Asset] = []
        self._rows: list[tuple[Asset, QFrame]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_lg, METRICS.spacing_xl, METRICS.spacing_xl
        )
        layout.setSpacing(METRICS.spacing_lg)

        self._header = PageHeader("Review Queue", "Assets awaiting your decision")
        layout.addWidget(self._header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(METRICS.spacing_sm)
        self._search = SearchBox("Search pending assets…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.addWidget(self._search, stretch=1)

        self._source_filter = QComboBox()
        self._source_filter.addItem("Every source", _SOURCE_ALL)
        self._source_filter.addItem("Manually imported", _SOURCE_MANUAL)
        self._source_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._source_filter)
        layout.addLayout(toolbar)

        self._list_container = QVBoxLayout()
        self._list_container.setSpacing(METRICS.spacing_sm)
        layout.addLayout(self._list_container)

        self._empty_state = EmptyState("Nothing waiting — the queue is clear.", icon="✅")
        layout.addWidget(self._empty_state)

        self._error_state = ErrorState("The database has no tables yet.")
        self._error_state.retry_requested.connect(self.refresh)
        layout.addWidget(self._error_state)

        layout.addStretch(1)

        self._overlay = LoadingOverlay(self, theme)

        QShortcut(QKeySequence("F5"), self, activated=self.refresh)

        self.refresh()

    # --- data loading -----------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                self._assets = self._ctx.approval_service.list_pending_review_assets(session)
        except OperationalError:
            self._show_error_state()
            return

        self._error_state.setVisible(False)
        self._rebuild_source_filter()
        self._rebuild_rows()
        self._apply_filters()
        self.review_count_updated.emit(len(self._assets))

    def _rebuild_source_filter(self) -> None:
        current = self._source_filter.currentData()
        self._source_filter.blockSignals(True)
        self._source_filter.clear()
        self._source_filter.addItem("Every source", _SOURCE_ALL)
        self._source_filter.addItem("Manually imported", _SOURCE_MANUAL)
        for source in sorted({a.source_tool for a in self._assets if a.source_tool}):
            self._source_filter.addItem(source, source)
        index = self._source_filter.findData(current)
        self._source_filter.setCurrentIndex(max(index, 0))
        self._source_filter.blockSignals(False)

    def _rebuild_rows(self) -> None:
        while self._list_container.count():
            item = self._list_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []

        for asset in self._assets:
            row = self._build_row(asset)
            self._list_container.addWidget(row)
            self._rows.append((asset, row))

    def _build_row(self, asset: Asset) -> QFrame:
        row = QFrame()
        row.setProperty("class", "reviewRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_sm, METRICS.spacing_md, METRICS.spacing_sm
        )
        row_layout.setSpacing(METRICS.spacing_md)

        icon = QLabel(_TYPE_ICON.get(asset.asset_type.value, "📄"))
        icon.setProperty("class", "iconChip")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(icon)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title = QLabel(asset.original_filename)
        title.setProperty("class", "entityRowTitle")
        text_column.addWidget(title)
        source = asset.source_tool or "Manually imported"
        subtitle = QLabel(f"{source}  ·  {age_label(asset.created_at)}")
        subtitle.setProperty("class", "entityRowSubtitle")
        text_column.addWidget(subtitle)
        row_layout.addLayout(text_column, stretch=1)

        reject_button = QPushButton("Reject")
        reject_button.setProperty("class", "danger")
        reject_button.clicked.connect(lambda _checked=False, a=asset: self._on_reject(a))
        row_layout.addWidget(reject_button)

        approve_button = QPushButton("Approve")
        approve_button.setProperty("class", "primary")
        approve_button.clicked.connect(lambda _checked=False, a=asset: self._on_approve(a))
        row_layout.addWidget(approve_button)

        return row

    def _show_error_state(self) -> None:
        self._empty_state.setVisible(False)
        self._error_state.setVisible(True)
        while self._list_container.count():
            item = self._list_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # --- search / filter ---------------------------------------------------

    def _apply_filters(self, *_args: object) -> None:
        query = self._search.text().strip().lower()
        source = self._source_filter.currentData()

        visible_count = 0
        for asset, row in self._rows:
            matches_query = not query or query in asset.original_filename.lower()
            matches_source = (
                source == _SOURCE_ALL
                or (source == _SOURCE_MANUAL and not asset.source_tool)
                or asset.source_tool == source
            )
            visible = matches_query and matches_source
            row.setVisible(visible)
            visible_count += int(visible)

        self._empty_state.setVisible(visible_count == 0 and not self._error_state.isVisible())
        if self._assets:
            self._empty_state.set_message("No pending assets match your search.")
        else:
            self._empty_state.set_message("Nothing waiting — the queue is clear.")

    # --- decisions -----------------------------------------------------------

    def _on_approve(self, asset: Asset) -> None:
        self._overlay.start("Approving…")
        try:
            with self._ctx.session_scope() as session:
                self._ctx.approval_service.decide_asset_review(
                    session, asset.id, ApprovalDecision.APPROVED
                )
        except (ValidationError, ServiceError) as err:
            show_error(self, "Approve Asset", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()
        self.refresh()

    def _on_reject(self, asset: Asset) -> None:
        dialog = _RejectReasonDialog(asset.original_filename, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return

        self._overlay.start("Rejecting…")
        try:
            with self._ctx.session_scope() as session:
                self._ctx.approval_service.decide_asset_review(
                    session, asset.id, ApprovalDecision.REJECTED, notes=dialog.reason()
                )
        except (ValidationError, ServiceError) as err:
            show_error(self, "Reject Asset", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()
        self.refresh()
