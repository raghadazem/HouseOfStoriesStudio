"""AssetsPage — browse, search, and import media assets.

The Dashboard's "Import Asset" quick action has shown "coming soon"
since Milestone 4A even though ``AssetImportService`` has been real
since Milestone 3 — this page is where that finally becomes a working
screen instead of a placeholder. Real thumbnails are loaded straight
from managed storage (``StorageService``) where the file exists on
disk; nothing here shows a generated/fake preview.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset
from app.core.services.asset_import_service import ImportRequest
from app.core.services.exceptions import (
    ConflictError,
    PrivacyViolationError,
    ServiceError,
    ValidationError,
)
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    EntityCard,
    ErrorState,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    ResponsiveGrid,
    SearchBox,
    StatusBadge,
    ToolbarRow,
    show_error,
)

_TYPE_ALL = "all"
_STATUS_ALL = "all"

_TYPE_ICON = {
    AssetType.IMAGE: "🖼",
    AssetType.VIDEO: "🎬",
    AssetType.VOICE: "🎙️",
    AssetType.MUSIC: "🎵",
    AssetType.THUMBNAIL: "🏞",
    AssetType.DOCUMENT: "📄",
}
_STATUS_VARIANT = {
    ApprovalStatus.DRAFT: "warning",
    ApprovalStatus.IN_REVIEW: "info",
    ApprovalStatus.APPROVED: "success",
    ApprovalStatus.REJECTED: "danger",
}
_PREVIEWABLE_TYPES = {AssetType.IMAGE, AssetType.THUMBNAIL}


def type_label(asset_type: AssetType) -> str:
    return asset_type.value.replace("_", " ").title()


def status_label(status: ApprovalStatus) -> str:
    return status.value.replace("_", " ").title()


class _ImportAssetDialog(FormDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Import Asset", icon="📥", subtitle="Bring a file into managed storage",
            save_label="Import", parent=parent,
        )
        self.selected_path: Path | None = None

        file_row = QHBoxLayout()
        self._file_label = QLabel("No file selected")
        self._file_label.setProperty("class", "muted")
        file_row.addWidget(self._file_label, stretch=1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._on_browse)
        file_row.addWidget(browse_button)
        file_wrap = QWidget()
        file_wrap.setLayout(file_row)
        self.add_row("Source file", file_wrap)

        self.type_field = QComboBox()
        for asset_type in AssetType:
            self.type_field.addItem(type_label(asset_type), asset_type)
        self.add_row("Asset type", self.type_field)

        self.notes_field = QLineEdit()
        self.notes_field.setPlaceholderText("Optional notes for reviewers")
        self.add_row("Notes", self.notes_field)

    def _on_browse(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(self, "Select a file to import")
        if path_str:
            self.selected_path = Path(path_str)
            self._file_label.setText(self.selected_path.name)
            self._file_label.setProperty("class", "")
            self.style().unpolish(self._file_label)
            self.style().polish(self._file_label)

    def validate(self) -> str | None:
        if self.selected_path is None:
            return "Choose a file to import first."
        return None

    def result_request(self) -> ImportRequest:
        assert self.selected_path is not None
        return ImportRequest(
            source_path=self.selected_path,
            # QComboBox.currentData() round-trips a str-subclassed Python
            # enum (AssetType(str, enum.Enum)) as a plain str, not the
            # enum member — PySide6/shiboken's QVariant packing sees the
            # str base type and stores/returns that instead. Re-wrapping
            # through the enum constructor restores a real AssetType,
            # which AssetImportService.import_asset requires via an
            # explicit isinstance() check.
            asset_type=AssetType(self.type_field.currentData()),
            notes=self.notes_field.text().strip() or None,
        )


class _AssetDetailDialog(FormDialog):
    def __init__(self, asset: Asset, preview: QPixmap | None, parent: QWidget | None = None) -> None:
        super().__init__(asset.original_filename, show_save=False, min_width=480, parent=parent)

        if preview is not None:
            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview_label.setPixmap(
                preview.scaledToWidth(280, Qt.TransformationMode.SmoothTransformation)
            )
            self.content_layout.addWidget(preview_label)

        meta_row = QHBoxLayout()
        meta_row.addWidget(StatusBadge(type_label(asset.asset_type), "neutral"))
        meta_row.addWidget(
            StatusBadge(status_label(asset.approval_status), _STATUS_VARIANT[asset.approval_status])
        )
        meta_row.addStretch(1)
        meta_wrap = QWidget()
        meta_wrap.setLayout(meta_row)
        self.add_row("Status", meta_wrap)

        path_field = QLineEdit(asset.relative_path)
        path_field.setReadOnly(True)
        self.add_row("Managed path", path_field)

        if asset.source_tool:
            source_field = QLineEdit(asset.source_tool)
            source_field.setReadOnly(True)
            self.add_row("Source tool", source_field)

        if asset.notes:
            notes_field = QLineEdit(asset.notes)
            notes_field.setReadOnly(True)
            self.add_row("Notes", notes_field)


class AssetsPage(QWidget):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("assetsPage")
        self._ctx = ctx
        self._theme = theme
        self._on_feedback = on_feedback
        self._assets: list[Asset] = []
        self._cards: list[tuple[Asset, EntityCard]] = []

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

        self._header = PageHeader(
            "Assets", "Every imported and generated file", primary_label="+ Import Asset"
        )
        self._header.primary_action_triggered.connect(self._on_import_asset)
        layout.addWidget(self._header)

        toolbar = ToolbarRow()
        self._search = SearchBox("Search assets…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.add_widget(self._search, stretch=1)

        self._type_filter = QComboBox()
        self._type_filter.addItem("All types", _TYPE_ALL)
        for asset_type in AssetType:
            self._type_filter.addItem(type_label(asset_type), asset_type)
        self._type_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.add_widget(self._type_filter)

        self._status_filter = QComboBox()
        self._status_filter.addItem("All statuses", _STATUS_ALL)
        for status in ApprovalStatus:
            self._status_filter.addItem(status_label(status), status)
        self._status_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.add_widget(self._status_filter)
        layout.addWidget(toolbar)

        self._count_label = QLabel("")
        self._count_label.setProperty("class", "resultCount")
        layout.addWidget(self._count_label)

        self._grid = ResponsiveGrid(card_min_width=180)
        layout.addWidget(self._grid)

        self._empty_state = EmptyState(
            "No assets yet — import a file or run an AI workflow to get started.",
            icon="🖼",
            action_label="+ Import Asset",
        )
        self._empty_state.action_triggered.connect(self._on_import_asset)
        layout.addWidget(self._empty_state)

        self._error_state = ErrorState("The database has no tables yet.")
        self._error_state.retry_requested.connect(self.refresh)
        layout.addWidget(self._error_state)

        layout.addStretch(1)

        self._overlay = LoadingOverlay(self, theme)

        self.refresh()

    # --- data loading -----------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                self._assets = session.query(Asset).order_by(Asset.created_at.desc()).all()
        except OperationalError:
            self._show_error_state()
            return

        self._error_state.setVisible(False)
        self._rebuild_cards()
        self._apply_filters()

    def _rebuild_cards(self) -> None:
        cards: list[tuple[Asset, EntityCard]] = []
        for asset in self._assets:
            card = EntityCard(
                _TYPE_ICON.get(asset.asset_type, "📄"), asset.original_filename, type_label(asset.asset_type)
            )
            pixmap = self._load_thumbnail(asset)
            if pixmap is not None:
                card.set_thumbnail(pixmap)
            card.add_trailing_widget(
                StatusBadge(status_label(asset.approval_status), _STATUS_VARIANT[asset.approval_status])
            )
            card.clicked.connect(lambda _checked=False, a=asset: self._open_detail(a))
            cards.append((asset, card))
        self._cards = cards
        self._grid.set_cards([card for _asset, card in cards])

    def _load_thumbnail(self, asset: Asset) -> QPixmap | None:
        if asset.asset_type not in _PREVIEWABLE_TYPES:
            return None
        try:
            path = self._ctx.storage_service.resolve_managed_path(asset.relative_path)
        except ValidationError:
            return None
        if not path.is_file():
            return None
        pixmap = QPixmap(str(path))
        return pixmap if not pixmap.isNull() else None

    def _show_error_state(self) -> None:
        self._empty_state.setVisible(False)
        self._error_state.setVisible(True)
        self._cards = []
        self._grid.set_cards([])

    # --- search / filter ---------------------------------------------------

    def _apply_filters(self, *_args: object) -> None:
        query = self._search.text().strip().lower()
        asset_type = self._type_filter.currentData()
        status = self._status_filter.currentData()

        visible_count = 0
        for asset, card in self._cards:
            matches_query = not query or query in asset.original_filename.lower()
            matches_type = asset_type == _TYPE_ALL or asset.asset_type == asset_type
            matches_status = status == _STATUS_ALL or asset.approval_status == status
            visible = matches_query and matches_type and matches_status
            card.setVisible(visible)
            visible_count += int(visible)

        self._empty_state.setVisible(visible_count == 0 and not self._error_state.isVisible())
        if self._assets:
            self._empty_state.set_message("No assets match your search or filters.", show_action=False)
        else:
            self._empty_state.set_message(
                "No assets yet — import a file or run an AI workflow to get started."
            )
        self._count_label.setVisible(bool(self._assets))
        self._count_label.setText(f"{visible_count} of {len(self._assets)} assets")

    # --- detail / import ----------------------------------------------------

    def _open_detail(self, asset: Asset) -> None:
        preview = self._load_thumbnail(asset)
        dialog = _AssetDetailDialog(asset, preview, parent=self)
        dialog.exec()

    def _on_import_asset(self) -> None:
        dialog = _ImportAssetDialog(parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return

        request = dialog.result_request()
        self._overlay.start("Importing asset…")
        try:
            with self._ctx.open_session() as session:
                self._ctx.asset_import_service.import_asset(session, request)
        except (ConflictError, ValidationError, PrivacyViolationError, ServiceError) as err:
            show_error(self, "Import Asset", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()

        self.refresh()
        if self._on_feedback:
            self._on_feedback("Asset imported.", "success")
